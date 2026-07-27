# Báo Cáo & Minh Chứng Implement Subtask 3.2: Tool Arguments Schema Validation & Boundary Guardrail

Tài liệu này tổng hợp phân tích chi tiết đối chiếu mã nguồn file [tool_validator.py](../techx-corp-platform/src/product-reviews/guardrails/tool_validator.py) với các yêu cầu của **Subtask 3.2 (Ticket 3 - Mandate #25)**.

---

## 1. Yêu Cầu Subtask 3.2 (Theo JIRA TODO Week 4)

- **An Toàn Biên JSON Decode**: Bọc khối lệnh parse JSON arguments `json.loads(tool_call.function.arguments)` bằng try-except `json.JSONDecodeError` để tránh crash gRPC server khi LLM trả về chuỗi JSON bị hỏng hoặc không đúng định dạng.
- **Kiểm Tra Schema Đối Số**: Viết hàm validate schema đối số: kiểm tra kiểu dữ liệu của `product_id` trong `function_args`, đảm bảo nó là chuỗi ký tự (`string`) hợp lệ, không rỗng, độ dài cho phép (≤ 64 ký tự), và không chứa ký tự độc hại (SQL Injection, XSS, Path Traversal).
- **Chuyển Hướng Fallback Khi Gặp Argument Rác**: Nếu đối số rác/không hợp lệ, lập tức chặn thực thi Tool Call, xuất telemetry metric `app_ai_fallback_total{source="malformed_tool_args"}` và đi ngay sang đường dẫn Fallback tĩnh.

---

## 2. Đối Chiếu Chi Tiết Mã Nguồn Đã Triển Khai

### 2.1. Module Xử Lý Biên: [tool_validator.py](../techx-corp-platform/src/product-reviews/guardrails/tool_validator.py)

Vị trí: `techx-corp-platform/src/product-reviews/guardrails/tool_validator.py`

#### A. Hàm `validate_tool_arguments(raw_arguments)`
- **Parse JSON an toàn**: Bọc `json.loads` trong khối `try...except (json.JSONDecodeError, TypeError, ValueError)`. Trả về `False, None, "json_decode_error"` nếu JSON hỏng, ngăn ngừa tuyệt đối ngoại lệ crash server.
- **Kiểm tra kiểu dữ liệu**: Đảm bảo kết quả parse JSON là một `dict` (JSON Object).
- **Kiểm tra Schema**: Tự động gọi `validate_product_id_argument()` khi tham số `product_id` xuất hiện trong đối số.

```python
def validate_tool_arguments(raw_arguments: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    if not isinstance(raw_arguments, str):
        return False, None, "invalid_arguments_type"

    try:
        parsed_args = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError, ValueError) as decode_err:
        return False, None, "json_decode_error"

    if not isinstance(parsed_args, dict):
        return False, None, "non_dict_arguments"

    if "product_id" in parsed_args:
        valid_pid, pid_err = validate_product_id_argument(parsed_args["product_id"])
        if not valid_pid:
            return False, parsed_args, f"invalid_schema:{pid_err}"

    return True, parsed_args, None
```

#### B. Hàm `validate_product_id_argument(product_id)`
Thực hiện 5 lớp bảo vệ nghiêm ngặt cho `product_id`:
1. **Dữ liệu phải là Chuỗi**: `isinstance(product_id, str)`.
2. **Không Rỗng**: `product_id.strip()` không được rỗng.
3. **Giới Hạn Độ Dài**: `len(stripped) <= 64`.
4. **Ký Tự Hợp Lệ (Regex)**: `PRODUCT_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]+$")` (chỉ chấp nhận chữ cái, chữ số, gạch ngang, gạch dưới).
5. **Chống Injection (Blacklist Keywords)**: Chặn các chuỗi độc hại như `<script`, `javascript:`, `../`, `..\`, `SELECT `, `DROP `, `INSERT `, `DELETE `, `UNION `, `' or '1'='1`.

---

### 2.2. Tích Hợp Vào gRPC Server: [product_reviews_server.py](../techx-corp-platform/src/product-reviews/product_reviews_server.py)

Vị trí: `techx-corp-platform/src/product-reviews/product_reviews_server.py`

Trước khi đưa tool call vào `ThreadPoolExecutor` thực thi, server tiến hành thẩm định schema đối số ở biên:

```python
with futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
    for tool_call in tool_calls:
        raw_args = getattr(getattr(tool_call, "function", None), "arguments", "")
        is_valid_args, function_args, val_err = validate_tool_arguments(raw_args)
        if not is_valid_args:
            logger.error(f"[MALFORMED_TOOL_ARGS] Invalid tool arguments: {val_err}")
            span.set_attribute("app.fallback.triggered", True)
            span.set_attribute("app.fallback.source", "malformed_tool_args")
            product_review_svc_metrics["app_ai_fallback_total"].add(
                1,
                {"source": "malformed_tool_args", "error": val_err or "invalid_schema"},
            )
            product_review_svc_metrics["app_ai_assistant_counter"].add(1, {'product.id': request_product_id})
            return finalize_response(
                FALLBACK_SUMMARY_MESSAGE,
                outcome="fallback",
                fallback_reason="malformed_tool_args",
            )
```

---

## 3. Kết Quả Kiểm Thử (Unit Tests Verification)

Tất cả 10 unit test cases trong [test_tool_validator.py](../techx-corp-platform/src/product-reviews/test_tool_validator.py) đã **PASSED 100%**:

```bash
============================= test session starts =============================
platform win32 -- Python 3.11.5, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\ASUS\OneDrive\Obsidian Vault\XBrain-Phase3\AIO02_TF3_Phase3\AIE1
collected 10 items

techx-corp-platform\src\product-reviews\test_tool_validator.py .......... [100%]

============================= 10 passed in 1.18s ==============================
```

### Danh Sách Các Test Cases Khai Thác Biên:
1. `test_validate_product_id_valid`: Tham số đúng chuẩn -> PASS.
2. `test_validate_product_id_invalid_type`: Nhập int thay vì str -> REJECT.
3. `test_validate_product_id_empty`: Chuỗi khoảng trắng rỗng -> REJECT.
4. `test_validate_product_id_too_long`: Độ dài > 64 ký tự -> REJECT.
5. `test_validate_product_id_special_chars`: Ký tự SQL Injection (`; DROP TABLE`) -> REJECT.
6. `test_validate_product_id_injection_patterns`: Thẻ XSS (`<script>`) -> REJECT.
7. `test_validate_tool_arguments_valid_json`: Chuỗi JSON hợp lệ -> PASS & Parsed Dict.
8. `test_validate_tool_arguments_malformed_json`: Chuỗi JSON bị hỏng (`json_decode_error`) -> REJECT không crash.
9. `test_validate_tool_arguments_non_dict_json`: Chuỗi JSON dạng Array -> REJECT (`non_dict_arguments`).
10. `test_validate_tool_arguments_invalid_product_id`: JSON chứa Path Traversal (`../etc/passwd`) -> REJECT (`invalid_schema`).

---

## 4. Kết Luận Đánh Giá

> [!IMPORTANT]
> File [tool_validator.py](../techx-corp-platform/src/product-reviews/guardrails/tool_validator.py) đã **ĐÁP ỨNG CHÍNH XÁC 100% NỘI DUNG MONG MUỐN CỦA SUBTASK 3.2**.


- ✅ Parse JSON an toàn bằng try-except, chống crash server khi LLM trả JSON rác.
- ✅ Ràng buộc chặt chẽ Schema đối số `product_id` (độ dài, regex, loại bỏ XSS/SQLi/Path Traversal).
- ✅ Tích hợp hoàn chỉnh vào luồng gRPC Server, lập tức chuyển hướng sang Fallback tĩnh và xuất Prometheus metrics khi gặp argument lỗi.
