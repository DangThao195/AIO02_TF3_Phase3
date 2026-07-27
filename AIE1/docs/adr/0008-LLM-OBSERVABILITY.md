# ADR 0008: Khả năng quan sát LLM (Runtime LLM Trace & Auditability) cho Product Reviews

> [!NOTE]
> * Trạng thái: Đã phê duyệt (Approved)
> * Tác giả: Thịnh (AIE1) và Khoa (Leader AIE1)
> * Ngày tạo: 2026-07-27
> * Ngày cập nhật: 2026-07-27
> * Dự án: AIE1 - Tối ưu & Vận hành Tầng AI (Task Force 1 - Mandate #24)

---

## 1. Bối cảnh
Tính năng Đánh giá Sản phẩm (Product Reviews) có ba bề mặt kiểm chứng độc lập:
- Luồng người dùng thực tế tại `product_reviews_server.py`;
- Đánh giá guardrail ngoại tuyến (offline) tại `repro/run_eval_guardrail.py`;
- Đánh giá mức độ trung thực/judge ngoại tuyến tại `repro/eval_fidelity.py`.

Các file kiểm chứng ngoại tuyến chứng minh được hoạt động của hệ thống (harness) và benchmark, nhưng tự chúng không thể chứng minh chính xác câu trả lời thực tế (runtime answer) nào đã được trả về cho người dùng. Để lấp đầy khoảng trống khả năng quan sát đó, hệ thống thực tế cần một ID theo dõi (trace id) có thể trả về cho client và sau đó dùng để truy xuất bản ghi trace dưới dạng hộp đen.

## 2. Giải pháp đề xuất & Quyết định kiến trúc

Bổ sung một lớp theo dõi (trace layer) thực tế cho `AskProductAIAssistant`:

1. Trích xuất trace ID hiện tại của OpenTelemetry bên trong `get_ai_assistant_response()` và trả về cho caller dưới dạng gRPC trailing metadata `x-trace-id`.
2. Lưu trữ bản ghi trace hộp đen (black-box trace record) vào Redis dưới cả 2 keys:
   ```text
   product_reviews:llm_trace:{trace_id}
   trace:{trace_id}
   ```
   `product_reviews:llm_trace:{trace_id}` là khóa nội bộ phân vùng (namespaced internal key).
   `trace:{trace_id}` là khóa truy xuất/phát lại (replay/fetch key) được yêu cầu bởi HTTP trace task.

3. Chỉ lưu trữ các metadata an toàn cho kiểm toán:
   - ID sản phẩm (product id);
   - Mã băm SHA-256 của câu hỏi người dùng;
   - Mã băm SHA-256 / phân loại của câu trả lời cuối cùng;
   - Model/provider của candidate và token/độ trễ/chi phí ước tính khi provider cung cấp thông tin sử dụng;
   - Model/provider của judge và token/độ trễ/chi phí ước tính khi judge được gọi;
   - Trạng thái cache hit;
   - Kết quả runtime guardrail/fidelity;
   - Lý do dự phòng (fallback) khi fallback được sử dụng.

4. **Không** lưu trữ raw prompts (lệnh gốc), raw reviews (đánh giá gốc), câu hỏi người dùng gốc, câu trả lời gốc của model, thông tin đăng nhập, hoặc payload danh mục sản phẩm vào bản ghi trace.

5. Cung cấp một HTTP handler tùy chọn dựa trên thư viện tiêu chuẩn `http.server.BaseHTTPRequestHandler`, được phục vụ bởi `ThreadingHTTPServer` trên một luồng daemon `threading.Thread`. Cổng HTTP trace mặc định là `8086`.

6. Cung cấp các HTTP endpoint cần thiết cho việc phát lại/kiểm toán luồng chạy nội bộ:
   ```text
   POST /replay
   GET /trace/{trace_id}
   ```
   `POST /replay` nhận `{question, product_id, user_id, session_id}`, gọi cùng đường dẫn thực tế `get_ai_assistant_response()` bên trong được dùng bởi gRPC, và trả về `{"response": "...", "cache": "hit|miss", "trace_id": "..."}`.
   
   `GET /trace/{trace_id}` đọc JSON nguyên bản từ Redis với khóa `trace:{trace_id}` và trả về 404 khi không tìm thấy trace.
   
   Endpoint tương thích/gỡ lỗi hiện tại vẫn được giữ lại:
   ```text
   GET /debug/llm-traces/{trace_id}
   ```
   Dịch vụ HTTP chỉ được bật khi biến `PRODUCT_REVIEWS_TRACE_HTTP_TOKEN` được thiết lập, trừ khi việc gỡ lỗi không xác thực tại local được bật tường minh qua `PRODUCT_REVIEWS_TRACE_HTTP_ALLOW_UNAUTHENTICATED=true`.

### 2.1 Hệ quả (Consequences)
**Lợi ích:**
- Một câu trả lời thực tế có thể được gắn kết với một trace id cụ thể.
- Bằng chứng có thể cho thấy liệu câu trả lời đến từ cache, fallback, logic xác định, luồng chỉ candidate, hay luồng candidate + runtime judge.
- Token, độ trễ, và chi phí sơ bộ được ghi nhận khi nhà cung cấp model trả về siêu dữ liệu sử dụng. Đa luồng gọi candidate/judge được giữ trong `calls` và tổng hợp trong `total_usage`.
- Cache-hit traces có thể trỏ ngược về `source_trace_id` ban đầu đã tạo ra câu trả lời được lưu cache.
- Không có câu hỏi/review/câu trả lời nguyên bản nào của người dùng được lưu trữ trong Redis traces.

**Đánh đổi và các giới hạn chấp nhận được:**
- Endpoint HTTP phụ thuộc vào tính khả dụng của Redis; việc ghi trace ở dạng fail-open (nếu lỗi ghi log thì bỏ qua, không chết ứng dụng) và không được chặn phản hồi đến người dùng.
- Endpoint HTTP chỉ dành cho việc gỡ lỗi local/nội bộ. Mặc định nó bị tắt và bảo vệ bằng token; không nên đưa trực tiếp ra ngoài public.
- Chi phí chỉ là ước tính dựa trên bảng giá công khai của Nova Lite/Micro, không phải nguồn tính cước chính xác. Đủ để đưa ra số liệu chứng minh tối ưu hóa trước/sau, nhưng không dùng để đối chiếu hóa đơn AWS.
- Traces dạng cache-hit không có thông tin sử dụng token candidate/judge mới vì không có LLM call nào thực hiện. Việc chấm lại (re-judge) mọi cache hit sẽ phá vỡ mục đích tối ưu chi phí/độ trễ.
- Câu hỏi, review, và câu trả lời raw cố ý không được lưu để bảo mật. Debug cần đối chiếu mã hash.

### 2.2 Tóm tắt Lược đồ Trace (Trace schema summary)
Ví dụ các trường (fields):
```json
{
  "schema_version": 1,
  "trace_id": "otel-or-generated-id",
  "trace_id_source": "otel",
  "service": "product-reviews",
  "operation": "AskProductAIAssistant",
  "product_id": "L9ECAV7KIM",
  "question_sha256": "...",
  "candidate": {
    "provider": "bedrock",
    "model": "amazon.nova-lite-v1:0",
    "calls": [
      {
        "call_index": 1,
        "provider": "bedrock",
        "model": "amazon.nova-lite-v1:0",
        "input_tokens": 123,
        "output_tokens": 45,
        "total_tokens": 168,
        "latency_ms": 900.12,
        "estimated_cost_usd": 0.000018
      }
    ],
    "total_usage": {
      "call_count": 1,
      "input_tokens": 123,
      "output_tokens": 45,
      "total_tokens": 168,
      "latency_ms": 900.12,
      "estimated_cost_usd": 0.000018,
      "cost_source": "static_price_table"
    }
  },
  "judge": {
    "provider": "bedrock",
    "model": "amazon.nova-micro-v1:0",
    "status": "approved",
    "calls": [
      {
        "call_index": 1,
        "provider": "bedrock",
        "model": "amazon.nova-micro-v1:0",
        "input_tokens": 456,
        "output_tokens": 78,
        "total_tokens": 534,
        "latency_ms": 700.34,
        "estimated_cost_usd": 0.000027
      }
    ],
    "total_usage": {
      "call_count": 1,
      "input_tokens": 456,
      "output_tokens": 78,
      "total_tokens": 534,
      "latency_ms": 700.34,
      "estimated_cost_usd": 0.000027,
      "cost_source": "static_price_table"
    }
  },
  "guardrails": {
    "input_safe": true,
    "output_filtered": true,
    "runtime_fidelity_gate": "approved"
  },
  "cache": {
    "hit": false,
    "key_sha256": "...",
    "source_trace_id": null
  },
  "outcome": "grounded_answer",
  "fallback_reason": null,
  "response_class": "grounded_answer",
  "response_sha256": "...",
  "total_latency_ms": 1750.46
}
```

### 2.3 Ghi chú vận hành (Operational notes)
Để bật endpoint HTTP trace nội bộ tại local:
```powershell
$env:PRODUCT_REVIEWS_TRACE_HTTP_PORT="8086"
$env:PRODUCT_REVIEWS_TRACE_HTTP_TOKEN="<internal-token>"
```
Lấy thông tin Trace từ Redis (theo id):
```powershell
curl.exe -H "x-trace-token: <internal-token>" http://localhost:8086/trace/<trace-id>
```
Ghi đè TTL của Redis (mặc định 86400 giây):
```powershell
$env:PRODUCT_REVIEWS_TRACE_TTL_SECONDS="86400"
```

## 3. Thống kê Chi phí Lũy kế & Token Usage theo Model

Bảng tổng hợp dựa trên báo cáo kiểm thử và đơn giá dự kiến của Amazon Nova:

| Vai trò (Role) | Mô hình (Model) | Số lượt gọi (Calls) | Input Tokens | Output Tokens | Tổng Token (Total) | Chi phí ước tính (USD) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Candidate | `amazon.nova-lite-v1:0` | 70 | 118,259 | 1,749 | 120,008 | $0.0075153 |
| Judge | `amazon.nova-micro-v1:0` | 37 | 63,711 | 6,715 | 70,426 | $0.0031700 |
| **Tổng cộng** | | **107** | **181,970** | **8,464** | **190,434** | **$0.0106853** |

## 4. Bằng chứng kiểm chứng thực tế

| Công việc | Bằng chứng runtime |
|---|---|
| AI-121: Trích xuất OTel Trace ID và trả về qua gRPC metadata | `product_reviews_server.py` gọi `current_trace_id()` và `attach_trace_metadata(context, trace_id)` bên trong `get_ai_assistant_response()`; metadata key là `x-trace-id`. |
| AI-122: Ghi black-box trace vào Redis | `guardrails/llm_trace.py` ghi bản ghi JSON an toàn cho kiểm toán vào `product_reviews:llm_trace:{trace_id}` và `trace:{trace_id}` qua `write_llm_trace()`. |
| AI-123: HTTP replay và fetch trace endpoint | `product_reviews_server.py` định nghĩa `LLMTraceHTTPHandler`, `_ReplayContext`, và `start_llm_trace_http_server()`; các route là `POST /replay`, `GET /trace/{trace_id}`, và route tương thích `/debug/llm-traces/{trace_id}`. |
| AI-124: Đánh giá ADR | Chính tài liệu ADR này mô tả lược đồ, đường dẫn truy cập và các hạn chế. |

### 4.1 Quy trình Smoke-test
Bài kiểm tra smoke-test yêu cầu:
1. Dịch vụ Product Reviews đang chạy với cấu hình Bedrock candidate/judge.
2. Có thể kết nối Redis từ Product Reviews.
3. Bật endpoint Trace bằng biến môi trường.
4. Gửi một request UI/gRPC tới `AskProductAIAssistant`.
5. Gọi `curl` tới cổng 8086 để fetch metadata tương ứng với mã trace trả về.

### 4.2 Bảng phân tích log kiểm thử hệ thống (Smoke-test Timeline)

Bài kiểm tra smoke-test thực tế đã chạy trên container Product Reviews bản rebuild (`aie1-product-reviews:trace-current`) cho câu hỏi: *"Do reviewers say the kit removes dust and fingerprints without leaving residue?"* (product_id=`L9ECAV7KIM`).

Toàn bộ vòng đời sinh log quan sát được ghi nhận chi tiết như sau:

| Trace ID | Bước (Phase) | Trạng thái | Chi tiết kỹ thuật | Kết quả (Verdict) |
| :--- | :---: | :---: | :--- | :---: |
| `6430920b...` | `init` | `OK` | Nhận gRPC Request. OTel sinh trace ID (x-trace-id) | Bắt đầu xử lý |
| `6430920b...` | `candidate` | `OK` | Gọi `amazon.nova-lite-v1:0` qua Bedrock | Tiêu thụ **1290 tokens** |
| `6430920b...` | `judge` | `OK` | Gọi `amazon.nova-micro-v1:0` qua Bedrock | Tiêu thụ **1970 tokens** |
| `6430920b...` | `guardrails` | `OK` | Gate: `runtime_fidelity_gate = approved` | **Grounded Answer** |
| `6430920b...` | `persist` | `OK` | Ghi siêu dữ liệu hộp đen vào Redis | Lưu vết thành công |

**Smoke-test cho kịch bản Cache-hit (Hỏi lại cùng câu hỏi trên):**

| Trace ID | Bước (Phase) | Trạng thái | Chi tiết kỹ thuật | Kết quả (Verdict) |
| :--- | :---: | :---: | :--- | :---: |
| `4e4cd351...` | `init` | `OK` | Nhận gRPC Request. OTel sinh trace ID mới | Bắt đầu xử lý |
| `4e4cd351...` | `cache` | `HIT` | Phát hiện câu hỏi trùng khớp trong Redis Cache | Bypass LLM |
| `4e4cd351...` | `persist` | `OK` | Lưu vết trace trỏ ngược về `source_trace_id=6430920b...` | Lưu vết thành công |
