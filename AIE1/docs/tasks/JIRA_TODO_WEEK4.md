# Kế hoạch Phân chia Công việc Tuần 4 - Nhóm AIE1 (JIRA TODO)

Tài liệu này chứa nội dung chi tiết các công việc tuần 4 (26/07 – 01/08/2026) được chuyển giao từ tuần 3, thiết kế dưới dạng các ticket **JIRA TODO** cho 3 thành viên: **Khoa** (Leader), **Thịnh**, và **Kiên**.

Các ticket này tập trung vào tối ưu hóa Caching nâng cao, hoàn thiện bộ giám sát Observability và nâng cao khả năng chịu lỗi Resilience (Circuit Breaker & Validation).

---

## 📋 PHÂN CHIA CÔNG VIỆC TỔNG QUAN (TUẦN 4)

| Người | Vai trò chính tuần 4 | Phạm vi thực hiện |
|-------|-------------------|-------------------|
| **Khoa** | Tối ưu Caching & Cách ly Ranh giới Người dùng | Caching & User Boundary (Mandate #23) |
| **Thịnh** | Hoàn thiện Trace Logger & Cổng Replay HTTP | LLM Observability & Replay (Mandate #24) |
| **Kiên** | Hoàn thiện Circuit Breaker tự phục hồi & Chặn Arguments Rác | AI Resilience (Mandate #25) |

---

## TICKET 1: Tích hợp Bộ nhớ đệm (Caching) & Đảm bảo Ranh giới Người dùng (MANDATE #23)
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #23 GenAI Caching & Memory (Tuần 4)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m23`

### Mô tả công việc (Description)
Tận dụng lớp Caching bằng Redis sẵn có của `product-reviews`. Do dịch vụ `product-reviews` là dạng hỏi đáp đơn lượt (Single-Turn Q&A), Mentor đã xác nhận **không cần triển khai bộ nhớ ngắn hạn và dài hạn (Memory)**. Nhóm chỉ tập trung vào cơ chế trả cờ cache và cách ly cache theo ranh giới người dùng.

### Các tác vụ con (Sub-tasks)
* **Sub-task 1.1: Thiết lập cờ trạng thái Cache qua gRPC Metadata (Trailing Headers)**
  - Chỉnh sửa hàm `get_ai_assistant_response` trong `product_reviews_server.py`.
  - Khi có Cache Hit (tìm thấy dữ liệu trong Redis cache), thiết lập trailing metadata `cache = hit` bằng cách gọi `context.set_trailing_metadata([('cache', 'hit')])`.
  - Khi có Cache Miss (gọi LLM và được Judge duyệt), thiết lập trailing metadata `cache = miss` bằng cách gọi `context.set_trailing_metadata([('cache', 'miss')])`.
  - Đảm bảo trong mọi trường hợp rẽ nhánh (bao gồm cả trường hợp deterministic hoặc fallback), cờ `cache: miss` vẫn được trả về đầy đủ mà không gây lỗi runtime.
* **Sub-task 1.2: Phân tách ranh giới và cách ly Cache theo `user_id`**
  - Trích xuất `user_id` từ gRPC invocation metadata bằng cách duyệt qua `context.invocation_metadata()` để tìm khóa `x-user-id` hoặc `user-id`.
  - Sửa hàm `generate_cache_key` trong `guardrails/cache.py` để nhận thêm tham số `user_id` (nếu có).
  - Tích hợp `user_id` vào chuỗi băm tạo key: `SHA256(product_id + review_version + model_id + question + user_id)`.
  - Nếu request không chứa `user_id`, sử dụng một giá trị mặc định là `"anonymous"` để tránh lỗi chuỗi `None`.
* **Sub-task 1.3: Đo lường chỉ số & Soạn thảo ADR 0005**
  - Thực hiện chạy bộ ca test có lặp để đo lường và thống kê `cache hit-rate`, so sánh latency/cost trước/sau cache.
  - Lưu kết quả benchmark đối chứng vào tệp tin JSON trong thư mục `repro/artifacts/`.
  - Cập nhật tài liệu quyết định kiến trúc `docs/adr/0005-CACHING-STRATEGY.md` giải thích thuật toán sinh key cách ly theo user và cơ chế invalidation theo `review_version`.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Cờ `cache: hit` hoặc `cache: miss` hoạt động chính xác trên từng request.
- [ ] Cache được cách ly độc lập theo `user_id` để tránh rò rỉ chéo thông tin.
- [ ] Có báo cáo số liệu hit-rate và so sánh hiệu năng thực tế.

---

## TICKET 2: Dựng Hộp Đen Giám Sát LLM & Cổng Replay/Fetch Trace (MANDATE #24)
* **Người thực hiện (Assignee):** Thịnh
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #24 LLM Observability (Tuần 4)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m24`

### Mô tả công việc (Description)
Xây dựng hệ thống Trace cho mọi cuộc gọi LLM (Candidate + Judge), trả về `trace-id` cho client, lưu vết chi tiết (token, cost, latency, outcome) xuống Redis và cung cấp cổng HTTP phụ để truy vấn trace chi tiết theo ID.

### Các tác vụ con (Sub-tasks)
* **Sub-task 2.1: Trích xuất OTel Trace ID và trả về qua gRPC Metadata**
  - Trong hàm `get_ai_assistant_response`, import thư viện OpenTelemetry `trace`.
  - Lấy span hiện tại bằng `trace.get_current_span()` và trích xuất `trace_id` thông qua `span.get_span_context().trace_id`.
  - Định dạng `trace_id` sang dạng chuỗi hexa 32 ký tự (`format(trace_id, '032x')`).
  - Trả về trace ID cho Client bằng cách set trailing metadata: `context.set_trailing_metadata([('trace-id', trace_id_str)])`.
* **Sub-task 2.2: Ghi nhận Trace chi tiết (Black Box) vào Redis**
  - Sau mỗi cuộc gọi LLM (Candidate + Judge), tạo cấu trúc dữ liệu JSON để lưu trữ thông tin trace chi tiết bao gồm: `trace_id`, `timestamp` (ISO 8601), `model` + `version`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `outcome` (OK/Error/Fallback), `session_id`, `user_id` và `masked_prompt`.
  - Đảm bảo prompt và câu hỏi được chạy qua hàm làm sạch `_sanitize_prompt_value` để xóa bỏ PII và các ký tự độc hại trước khi ghi trace log.
  - Sử dụng Redis client để lưu bản ghi JSON này dưới khóa `trace:{trace_id}` với thời gian hết hạn (TTL) là 24 giờ.
* **Sub-task 2.3: Xây dựng Cổng HTTP Replay & Fetch Trace**
  - Viết một class HTTP handler sử dụng thư viện chuẩn `http.server.BaseHTTPRequestHandler` chạy trên một luồng riêng (`threading.Thread`) song song trên cổng `8086`.
  - Triển khai endpoint `POST /replay`: nhận `{question, product_id, user_id, session_id}`, gọi hàm xử lý AI nội bộ, trả về phản hồi JSON dạng `{"response": "...", "cache": "hit|miss", "trace_id": "..."}`.
  - Triển khai endpoint `GET /trace/<trace_id>`: đọc trace tương ứng từ Redis bằng lệnh `redis_client.get(f"trace:{trace_id}")` và trả về JSON thô cho Client (trả về 404 nếu không tìm thấy).
* **Sub-task 2.4: Soạn thảo ADR 0008 & View tổng hợp**
  - Soạn thảo tài liệu quyết định kiến trúc `docs/adr/0008-llm-observability.md` mô tả cấu trúc của bản ghi trace, cơ chế truyền trace-id và cách thức ẩn danh/mask PII.
  - Thống kê và hiển thị chi phí lũy kế, token usage theo model trong view tổng hợp.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Trả về đúng `trace-id` qua metadata gRPC hoặc HTTP replay.
- [ ] Endpoint `GET /trace/<trace_id>` trả về đúng trace đầy đủ các trường cốt lõi.
- [ ] Dữ liệu prompt trong trace được che (mask/hash) hoàn toàn các thông tin PII/secret.

---

## TICKET 3: Tích hợp Circuit Breaker & Chặn Arguments Rác (MANDATE #25)
* **Người thực hiện (Assignee):** Kiên
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #25 AI Resilience & Fallback (Tuần 4)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m25`

### Mô tả công việc (Description)
Nâng cấp độ bền vững của `product-reviews` khi model bị lỗi (timeout, rate-limit, 5xx) hoặc trả về output bị hỏng/sai JSON schema khi gọi tool.

### Các tác vụ con (Sub-tasks)
* **Sub-task 3.1: Tích hợp Circuit Breaker tự phục hồi**
  - Viết một class `CircuitBreaker` quản lý trạng thái (`CLOSED`, `OPEN`, `HALF-OPEN`) lưu trữ trong Redis hoặc bộ nhớ trong của server.
  - Khi có lỗi kết nối LLM hoặc các lỗi tạm thời (429, 5xx, timeout) ghi nhận trong hàm gọi LLM Bedrock/OpenAI, tăng biến đếm lỗi liên tiếp (`consecutive_failures`).
  - Nếu `consecutive_failures >= 5`, chuyển trạng thái sang `OPEN` và đặt thời gian hết hạn (cool-down) là 30 giây. Mọi yêu cầu gRPC tới LLM trong thời gian này sẽ bị chặn ngay lập tức và đi thẳng vào tầng Fallback tĩnh.
  - Sau 30 giây, chuyển sang `HALF-OPEN`. Nếu request thành công, reset biến đếm lỗi và đưa trạng thái về `CLOSED`. Nếu tiếp tục lỗi, đưa về `OPEN`.
* **Sub-task 3.2: Chặn Arguments Rác & Validate Tool Call Schema ở biên**
  - Bọc khối lệnh parse JSON arguments: `json.loads(tool_call.function.arguments)` bằng try-except `json.JSONDecodeError` để tránh crash gRPC server khi LLM trả JSON hỏng, chuyển hướng sang fallback.
  - Viết hàm validate schema đối số: kiểm tra kiểu dữ liệu của `product_id` trong `function_args`, đảm bảo nó là chuỗi ký tự hợp lệ, không rỗng, và không chứa ký tự độc hại. Nếu đối số không hợp lệ (arguments rác), chặn thực thi tool và đi sang fallback path.
* **Sub-task 3.3: Cổng ép lỗi giả lập (Failure & Malformed Output Injection)**
  - Tích hợp endpoint `POST /inject` trên cổng HTTP Server phụ (cổng `8086`) nhận cấu hình lỗi giả lập bao gồm:
    - `{"inject_error": "timeout"|"429"|"500"}`: Lưu cấu hình này vào Redis. Khi server gọi LLM, nếu phát hiện cấu hình, chủ động nâng Exception tương ứng để kích hoạt Circuit Breaker.
    - `{"inject_malformed_tool_args": true}`: Lưu cấu hình. Khi nhận phản hồi có chứa tool call, giả lập ghi đè `tool_call.function.arguments` bằng một chuỗi JSON lỗi để kiểm chứng khả năng chịu lỗi.
* **Sub-task 3.4: Soạn thảo ADR 0007 (Mở rộng)**
  - Cập nhật tài liệu `docs/adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md` bổ sung thiết kế Circuit Breaker, mô tả cơ chế validate JSON schema biên cho tool arguments, và kịch bản phục hồi lỗi có kiểm soát.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Khi LLM lỗi liên tục, Circuit Breaker mở ra chặn dội request, hệ thống phản hồi fallback nhanh.
- [ ] LLM sinh output JSON hỏng hoặc đối số tool rác không làm gRPC server crash, tool không bị thực thi với đối số rác.
- [ ] Inject lỗi giả lập hoạt động đúng kịch bản test của Mentor.

---

## 📅 LỊCH SPRINT CHI TIẾT THEO NGÀY (TUẦN 4)

| Ngày | Khoa (Leader) | Thịnh | Kiên |
|------|---------------|-------|------|
| **T2 26/07** | - Thiết lập cờ cache hit/miss qua gRPC metadata (1.1) | - Trích xuất OTel Trace ID qua metadata gRPC (2.1) | - Họp thiết kế logic Circuit Breaker (3.1) |
| **T3 27/07** | - Sửa hàm `generate_cache_key` cách ly theo `user_id` (1.2) | - Thiết lập trace JSON lưu Redis (2.2) | - Triển khai class `CircuitBreaker` (3.1) |
| **T4 28/07** | - Chạy thử nghiệm đo lường cache hit-rate & latency (1.3) | - Code endpoint `POST /replay` (2.3) | - Bọc try-except parse JSON arguments biên (3.2) |
| **T5 29/07** | - Soạn thảo ADR 0005 cập nhật (1.3) | - Code endpoint `GET /trace/<trace_id>` (2.3) | - Tạo cổng nạp lỗi giả lập `POST /inject` (3.3) |
| **T6 30/07** | - Kiểm định chéo và tối ưu hóa | - Soạn thảo ADR 0008 và view chi phí (2.4) | - Cập nhật mở rộng ADR 0007 (3.4) |
| **T7 31/07** | - Nghiệm thu & Nghiệm thu | - Nghiệm thu & Nghiệm thu | - Nghiệm thu & Nghiệm thu |
