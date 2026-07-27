# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #24

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả đo lường quan sát hệ thống AI (LLM Observability & Traceability), khả năng truy vết black-box trace record qua gRPC metadata `x-trace-id`, các HTTP endpoints `/trace/{trace_id}` & `/replay` (cổng HTTP 8086), và kiểm toán an toàn của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #24`**.

---

## 👥 1. Thông Tin Thành Viên Thực Hiện (Task Force AIE1)
*   **Lê Hải Khoa** - Leader AIE1
*   **Ngô Thanh Kiên** - Thành viên AIE1
*   **Nguyễn Tiến Hoàng Thịnh** - Thành viên AIE1

---

## 🔗 2. Các Commit & PR Liên Quan
*   **Commit Tích Hợp LLM Observability & HTTP Trace Server:** [ab5913c](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ab5913c) (Tích hợp Tracing layer, HTTP handler port 8086, và Redis Dual-Key persistence).
*   **Commit Cập Nhật ADR 0008 & Telemetry Trace Schema:** [a033b35](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/a033b35)
*   **Nhánh làm việc chính thức:** `feature/product-review`

---

## 🛠️ 3. Lệnh Tái Tạo & Harness Kiểm Thử Trace HTTP Endpoints (Repro & Harness)

### A. Lệnh khởi chạy HTTP Trace Server & Khôi Phục Replay (Port 8086)
Bật các biến môi trường cấu hình cổng HTTP phụ và token bảo mật (tùy chọn):
```powershell
$env:PRODUCT_REVIEWS_TRACE_HTTP_PORT="8086"
$env:PRODUCT_REVIEWS_TRACE_HTTP_ALLOW_UNAUTHENTICATED="true"
```

### B. Lệnh Test Harness Truy Vấn Trace & Replay
1.  **Gửi Request Giả Lập Replay (`POST /replay`):**
    ```powershell
    curl.exe -X POST `
      -H "Content-Type: application/json" `
      -d "{\"question\":\"Do reviewers say the kit removes dust?\",\"product_id\":\"L9ECAV7KIM\",\"user_id\":\"jira-smoke\",\"session_id\":\"ai-124\"}" `
      http://localhost:8086/replay
    ```
2.  **Truy Vấn Black-box Trace Record Nhận Được (`GET /trace/{trace_id}`):**
    ```powershell
    curl.exe http://localhost:8086/trace/<trace-id>
    ```

---

## 📁 4. Đường Dẫn Mã Nguồn Trace & Báo Cáo Trong Repo

### A. Mã nguồn logic Trace & HTTP Server
*   **Logic Tracing & Audit-Safe Record Generator:** [guardrails/llm_trace.py](../../techx-corp-platform/src/product-reviews/guardrails/llm_trace.py)
*   **Logic gRPC Metadata Trailing & Class `LLMTraceHTTPHandler`:** [product_reviews_server.py](../../techx-corp-platform/src/product-reviews/product_reviews_server.py)
*   **Mã nguồn kiểm thử tự động Tracing:** [test_runtime_guardrails.py](../../techx-corp-platform/src/product-reviews/test_runtime_guardrails.py)

### B. Báo cáo kiến trúc & Tài liệu liên quan
*   **Tài liệu Kiến trúc ADR 0008 (Runtime LLM Trace):** [0008-runtime-llm-trace-auditability.md](../adr/0008-runtime-llm-trace-auditability.md)
*   **Chỉ thị gốc Mandate 24:** [MANDATE-24-llm-observability.md](../../mandates/MANDATE-24-llm-observability.md)

---

## 🔍 5. Đặc Điểm Kiến Trúc Observability & Security Compliance

### A. Quản Lý Trace ID & Trích Xuất Biên
- **OpenTelemetry Context Integration:** Tự động trích xuất `current_trace_id()` từ OpenTelemetry Context trong `get_ai_assistant_response()`.
- **gRPC Trailing Metadata `x-trace-id`:** Trả vết `x-trace-id` về gRPC client qua Trailing Metadata của gRPC response, cho phép client truy vết chính xác cuộc gọi.

### B. Dual-Key Redis Trace Storage (`TTL 86400s`)
Mỗi request được lưu song song dưới 2 khóa Redis để phục vụ cả truy vấn nội bộ lẫn HTTP API:
- `product_reviews:llm_trace:{trace_id}` (Key nội bộ theo namespace)
- `trace:{trace_id}` (Key chuẩn mở cho HTTP GET /trace/{trace_id})

### C. Bảo Mật An Toàn Thông Tin (Audit-Safe Compliance)
- **Tuyệt Đối Không Lưu PII / Raw Text:** Trace record **KHÔNG lưu trữ** văn bản thô của câu hỏi người dùng, câu trả lời LLM, review thô hay thông tin PII.
- **Mã Hóa Hash Bằng SHA-256:** Lưu vết dưới dạng SHA-256 Hash (`question_sha256`, `response_sha256`, `key_sha256`) đảm bảo khả năng đối soát kiểm toán (Auditability) mà không vi phạm quy định bảo mật dữ liệu.
- **Thống Kê Token & Chi Phí Thực Tế:** Ghi nhận đầy đủ token tiêu thụ (`input_tokens`, `output_tokens`, `total_tokens`), latency thực tế (`latency_ms`), mô hình sử dụng (Nova Lite / Nova Micro) và ước tính chi phí USD.

---

## 📊 6. Cấu Trúc Trace Record Chi Tiết (Trace JSON Schema)

```json
{
  "schema_version": 1,
  "trace_id": "6430920be99810c6d6255d620292a695",
  "trace_id_source": "otel",
  "service": "product-reviews",
  "operation": "AskProductAIAssistant",
  "product_id": "L9ECAV7KIM",
  "question_sha256": "8f9b...",
  "candidate": {
    "provider": "bedrock",
    "model": "amazon.nova-lite-v1:0",
    "total_usage": {
      "call_count": 1,
      "input_tokens": 123,
      "output_tokens": 45,
      "total_tokens": 168,
      "latency_ms": 900.12,
      "estimated_cost_usd": 0.000018
    }
  },
  "judge": {
    "provider": "bedrock",
    "model": "amazon.nova-micro-v1:0",
    "status": "approved",
    "total_usage": {
      "call_count": 1,
      "input_tokens": 456,
      "output_tokens": 78,
      "total_tokens": 534,
      "latency_ms": 700.34,
      "estimated_cost_usd": 0.000027
    }
  },
  "guardrails": {
    "input_safe": true,
    "output_filtered": true,
    "runtime_fidelity_gate": "approved"
  },
  "cache": {
    "hit": false,
    "key_sha256": "3a1c...",
    "source_trace_id": null
  },
  "outcome": "grounded_answer",
  "fallback_reason": null,
  "response_class": "grounded_answer",
  "response_sha256": "e2f4...",
  "total_latency_ms": 1750.46
}
```

---

## 📁 7. Các Tài Liệu Minh Chứng & ADR Đi Kèm (Artifacts)
*   **ADR 0008 (Runtime LLM Trace & Auditability):** [0008-runtime-llm-trace-auditability.md](../adr/0008-runtime-llm-trace-auditability.md)
*   **Mandate 24 Specification:** [MANDATE-24-llm-observability.md](../../mandates/MANDATE-24-llm-observability.md)
