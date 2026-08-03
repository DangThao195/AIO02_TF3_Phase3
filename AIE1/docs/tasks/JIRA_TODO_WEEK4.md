# Kế hoạch Phân chia Công việc Tuần 4 - Nhóm AIE1 (JIRA TODO)

Tài liệu này chứa nội dung chi tiết các công việc tuần 4 (26/07 – 01/08/2026) được chuyển giao từ tuần 3 và các backlog quan trọng từ AI Baseline Report, thiết kế dưới dạng các ticket **JIRA TODO** cho 3 thành viên: **Khoa** (Leader), **Thịnh**, và **Kiên| Ticket | Tên Công Việc | Người thực hiện (Assignee) | Trụ cột ảnh hưởng |
|:---:|:---|:---:|:---|
| **T1** | Caching & Ranh giới Người dùng (Mandate #23) (🟢 **HOÀN THÀNH**) | **Khoa (Leader)** | Performance & Caching |
| **T2** | Observability & Trace log (Mandate #24) (🟢 **HOÀN THÀNH**) | **Thịnh** | Telemetry & Observability |
| **T3** | Circuit Breaker & Arguments Validation (Mandate #25) (🟢 **HOÀN THÀNH**) | **Kiên** | Resilience & Safety |
| **T4** | Tối ưu hóa chất lượng LLM & Hiệu chuẩn Prompt Judge (🟢 **HOÀN THÀNH**) | **Thịnh** | Quality & Accuracy |
| **T5** | Triển khai PostgreSQL Static Summary Fallback (Tầng 2) (🟢 **HOÀN THÀNH**) | **Kiên** | Resilience & Fallback |

---

## TICKET 1: Tích hợp Bộ nhớ đệm (Caching) & Đảm bảo Ranh giới Người dùng (MANDATE #23) (🟢 HOÀN THÀNH)
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Epic:** AIE1 - Mandate #23 GenAI Caching & Memory (Tuần 4)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m23`

### Mô tả công việc (Description)
Tận dụng lớp Caching bằng Redis sẵn có của `product-reviews`. Do dịch vụ `product-reviews` là dạng hỏi đáp đơn lượt (Single-Turn Q&A), Mentor đã xác nhận **không cần triển khai bộ nhớ ngắn hạn và dài hạn (Memory)**. Nhóm chỉ tập trung vào cơ chế trả cờ cache và cách ly cache theo ranh giới người dùng.

### Các tác vụ con (Sub-tasks)
* **[x] Sub-task 1.1: Thiết lập cờ trạng thái Cache qua gRPC Metadata (Trailing Headers)**
  - Chỉnh sửa hàm `get_ai_assistant_response` trong `product_reviews_server.py`.
  - Khi có Cache Hit (tìm thấy dữ liệu trong Redis cache), thiết lập trailing metadata `cache = hit` bằng cách gọi `context.set_trailing_metadata([('cache', 'hit')])`.
  - Khi có Cache Miss (gọi LLM và được Judge duyệt), thiết lập trailing metadata `cache = miss` bằng cách gọi `context.set_trailing_metadata([('cache', 'miss')])`.
  - Đảm bảo trong mọi trường hợp rẽ nhánh (bao gồm cả trường hợp deterministic hoặc fallback), cờ `cache: miss` vẫn được trả về đầy đủ mà không gây lỗi runtime.
* **[x] Sub-task 1.2: Phân tách ranh giới và cách ly Cache theo `user_id`**
  - Trích xuất `user_id` từ gRPC invocation metadata bằng cách duyệt qua `context.invocation_metadata()` để tìm khóa `x-user-id` hoặc `user-id`.
  - Sửa hàm `generate_cache_key` trong `guardrails/cache.py` để nhận thêm tham số `user_id` (nếu có).
  - Tích hợp `user_id` vào chuỗi băm tạo key: `SHA256(product_id + review_version + model_id + question + user_id)`.
  - Nếu request không chứa `user_id`, sử dụng một giá trị mặc định là `"anonymous"` để tránh lỗi chuỗi `None`.
* **[x] Sub-task 1.3: Đo lường chỉ số & Soạn thảo ADR 0005**
  - Thực hiện chạy bộ ca test có lặp để đo lường và thống kê `cache hit-rate`, so sánh latency/cost trước/sau cache.
  - Lưu kết quả benchmark đối chứng vào tệp tin JSON trong thư mục `repro/artifacts/`.
  - Cập nhật tài liệu quyết định kiến trúc `docs/adr/0005-CACHING-STRATEGY.md` giải thích thuật toán sinh key cách ly theo user và cơ chế invalidation theo `review_version`.

---

## TICKET 2: Dựng Hộp Đen Giám Sát LLM & Cổng Replay/Fetch Trace (MANDATE #24) (🟢 HOÀN THÀNH)
* **Người thực hiện (Assignee):** Thịnh
* **Epic:** AIE1 - Mandate #24 LLM Observability (Tuần 4)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m24`

### Mô tả công việc (Description)
Xây dựng hệ thống Trace cho mọi cuộc gọi LLM (Candidate + Judge), trả về `trace-id` cho client, lưu vết chi tiết (token, cost, latency, outcome) xuống Redis và cung cấp cổng HTTP phụ để truy vấn trace chi tiết theo ID.

### Các tác vụ con (Sub-tasks)
* **[x] Sub-task 2.1: Trích xuất OTel Trace ID và trả về qua gRPC Metadata**
  - Trong hàm `get_ai_assistant_response`, import thư viện OpenTelemetry `trace`.
  - Lấy span hiện tại bằng `trace.get_current_span()` và trích xuất `trace_id` thông qua `span.get_span_context().trace_id`.
  - Định dạng `trace_id` sang dạng chuỗi hexa 32 ký tự (`format(trace_id, '032x')`).
  - Trả về trace ID cho Client bằng cách set trailing metadata: `context.set_trailing_metadata([('trace-id', trace_id_str)])`.
* **[x] Sub-task 2.2: Ghi nhận Trace chi tiết (Black Box) vào Redis**
  - Sau mỗi cuộc gọi LLM (Candidate + Judge), tạo cấu trúc dữ liệu JSON để lưu trữ thông tin trace chi tiết bao gồm: `trace_id`, `timestamp` (ISO 8601), `model` + `version`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `outcome` (OK/Error/Fallback), `session_id`, `user_id` và `masked_prompt`.
  - Đảm bảo prompt và câu hỏi được chạy qua hàm làm sạch `_sanitize_prompt_value` để xóa bỏ PII và các ký tự độc hại trước khi ghi trace log.
  - Sử dụng Redis client để lưu bản ghi JSON này dưới khóa `trace:{trace_id}` với thời gian hết hạn (TTL) là 24 giờ.
* **[x] Sub-task 2.3: Xây dựng Cổng HTTP Replay & Fetch Trace**
  - Viết một class HTTP handler sử dụng thư viện chuẩn `http.server.BaseHTTPRequestHandler` chạy trên một luồng riêng (`threading.Thread`) song song trên cổng `8086`.
  - Triển khai endpoint `POST /replay`: nhận `{question, product_id, user_id, session_id}`, gọi hàm xử lý AI nội bộ, trả về phản hồi JSON dạng `{"response": "...", "cache": "hit|miss", "trace_id": "..."}`.
  - Triển khai endpoint `GET /trace/<trace_id>`: đọc trace tương ứng từ Redis bằng lệnh `redis_client.get(f"trace:{trace_id}")` và trả về JSON thô cho Client (trả về 404 nếu không tìm thấy).
* **[x] Sub-task 2.4: Soạn thảo ADR 0008 & View tổng hợp**
  - Soạn thảo tài liệu quyết định kiến trúc `docs/adr/0008-llm-observability.md` mô tả cấu trúc của bản ghi trace, cơ chế truyền trace-id và cách thức ẩn danh/mask PII.
  - Thống kê và hiển thị chi phí lũy kế, token usage theo model trong view tổng hợp.

---

## TICKET 3: Tích hợp Circuit Breaker & Chặn Arguments Rác (MANDATE #25) (🟢 HOÀN THÀNH)
* **Người thực hiện (Assignee):** Kiên
* **Epic:** AIE1 - Mandate #25 AI Resilience & Fallback (Tuần 4)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m25`

### Mô tả công việc (Description)
Nâng cấp độ bền vững của `product-reviews` khi model bị lỗi (timeout, rate-limit, 5xx) hoặc trả về output bị hỏng/sai JSON schema khi gọi tool.

### Các tác vụ con (Sub-tasks)
* **[x] Sub-task 3.1: Tích hợp Circuit Breaker tự phục hồi**
  - Viết một class `CircuitBreaker` quản lý trạng thái (`CLOSED`, `OPEN`, `HALF-OPEN`) lưu trữ trong Redis hoặc bộ nhớ trong của server.
  - Khi có lỗi kết nối LLM hoặc các lỗi tạm thời (429, 5xx, timeout) ghi nhận trong hàm gọi LLM Bedrock/OpenAI, tăng biến đếm lỗi liên tiếp (`consecutive_failures`).
  - Nếu `consecutive_failures >= 5`, chuyển trạng thái sang `OPEN` và đặt thời gian hết hạn (cool-down) là 30 giây. Mọi yêu cầu gRPC tới LLM trong thời gian này sẽ bị chặn ngay lập tức và đi thẳng vào tầng Fallback tĩnh.
  - Sau 30 giây, chuyển sang `HALF-OPEN`. Nếu request thành công, reset biến đếm lỗi và đưa trạng thái về `CLOSED`. Nếu tiếp tục lỗi, đưa về `OPEN`.
* **[x] Sub-task 3.2: Chặn Arguments Rác & Validate Tool Call Schema ở biên**
  - Bọc khối lệnh parse JSON arguments: `json.loads(tool_call.function.arguments)` bằng try-except `json.JSONDecodeError` để tránh crash gRPC server khi LLM trả JSON hỏng, chuyển hướng sang fallback.
  - Viết hàm validate schema đối số: kiểm tra kiểu dữ liệu của `product_id` trong `function_args`, đảm bảo nó là chuỗi ký tự hợp lệ, không rỗng, và không chứa ký tự độc hại. Nếu đối số không hợp lệ (arguments rác), chặn thực thi tool và đi sang fallback path.
* **[x] Sub-task 3.3: Cổng ép lỗi giả lập (Failure & Malformed Output Injection)**
  - Tích hợp endpoint `POST /inject` trên cổng HTTP Server phụ (cổng `8086`) nhận cấu hình lỗi giả lập bao gồm:
    - `{"inject_error": "timeout"|"429"|"500"}`: Lưu cấu hình này vào Redis. Khi server gọi LLM, nếu phát hiện cấu hình, chủ động nâng Exception tương ứng để kích hoạt Circuit Breaker.
    - `{"inject_malformed_tool_args": true}`: Lưu cấu hình. Khi nhận phản hồi có chứa tool call, giả lập ghi đè `tool_call.function.arguments` bằng một chuỗi JSON lỗi để kiểm chứng khả năng chịu lỗi.
* **[x] Sub-task 3.4: Soạn thảo ADR 0007 (Mở rộng)**
  - Cập nhật tài liệu `docs/adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md` bổ sung thiết kế Circuit Breaker, mô tả cơ chế validate JSON schema biên cho tool arguments, và kịch bản phục hồi lỗi có kiểm soát.

---

## TICKET 4: Tối ưu hóa chất lượng LLM & Hiệu chuẩn Prompt Judge (RAG Quality Optimization) (🟢 HOÀN THÀNH)
* **Người thực hiện (Assignee):** Thịnh
* **Epic:** AIE1 - Tối ưu hóa Hiệu năng & Chất lượng AI (Tuần 4)
* **Ưu tiên:** High (P1)
* **Label Jira:** `ai-quality`, `rag-opt`

### Mô tả công việc (Description)
Rà soát và cải tiến chất lượng sinh câu trả lời (RAG Accuracy) của LLM Candidate và hiệu chuẩn mô hình Judge để tăng tỷ lệ Pass Rate thực tế (hiện đang ở mức 83.3% trong baseline caching lên ≥ 90%). Khắc phục triệt để các trường hợp Judge từ chối nhầm các câu trả lời tốt (False Positive) hoặc Candidate bịa đặt thông tin khi dữ liệu review ít.

### Các tác vụ con (Sub-tasks)

* **[x] Sub-task 4.1: Cải tiến Prompt System & Context cho Candidate (`product_reviews_server.py`)**
  - **Vị trí code**: Chỉnh sửa các hàm `build_system_prompt()` và `build_runtime_prompts()` trong [product_reviews_server.py](../../techx-corp-platform/src/product-reviews/product_reviews_server.py).
  - **Ranh giới thông tin (Grounding Bound)**: Ràng buộc chặt chẽ trong System Prompt: Chỉ tóm tắt các khía cạnh có bằng chứng trực tiếp (`Direct Evidence`) từ danh sách review. Nếu câu hỏi yêu cầu khía cạnh không có trong dữ liệu -> bắt buộc trả về sentinel `NO_INFO`.
  - **Cấu trúc lại Context**: Định dạng lại chuỗi Grounded Context truyền sang Candidate với cấu trúc rõ ràng: `[Rating/Score]`, `[User]`, `[Review Title]`, `[Review Content]`.
  - **Xử lý dữ liệu thưa (Sparse Evidence)**: Tinh chỉnh chỉ dẫn cho các sản phẩm chỉ có 1-2 review hoặc review không có text (chỉ có sao rating), ngăn LLM Candidate tự suy diễn hoặc phóng đại các tính năng sản phẩm không có thật.

* **[x] Sub-task 4.2: Hiệu chuẩn Tiêu chuẩn & Prompt của Judge (`guardrails/evaluator.py`)**
  - **Vị trí code**: Chỉnh sửa hằng số `JUDGE_SYSTEM_PROMPT` và hàm `_build_prompt()` trong [evaluator.py](../../techx-corp-platform/src/product-reviews/guardrails/evaluator.py).
  - **Quy tắc Paraphrase & Đa ngôn ngữ (Cross-language)**: Bổ sung chỉ dẫn không bắt lỗi (False Positive) với các câu trả lời diễn đạt lại (Paraphrase) hoặc dịch nghĩa tương đương giữa tiếng Anh và tiếng Việt.
  - **Quy tắc Tổng hợp Logic (Conservative Synthesis)**: Cho phép tổng hợp các ý tương đồng từ nhiều review (Reasonable Synthesis) nếu không tự sáng tạo ra chi tiết mới ngoài dữ liệu review.
  - **Kiểm tra chỉ số định lượng (Rating/Score Alignment)**: Ràng buộc Judge đối chiếu các tuyên bố về số sao/điểm số dựa trên dữ liệu chuẩn `trusted_derived_review_facts` (`review_count`, `average_score`, `negative_review_count` với score < 3.0).
  - **Chuẩn hóa Tool Call Schema**: Ép mô hình Judge trả kết quả qua tool `submit_fidelity_result` (dạng JSON object `claims: [{text, label, evidence}]`) để loại bỏ hoàn toàn lỗi parse markdown code fences.

* **[x] Sub-task 4.3: Bổ sung Dataset Edge Cases & Đo lường Tỷ lệ Khớp (Agreement Rate)**
  - **Vị trí code**: Tệp [dataset.jsonl](../../repro/datasets/dataset.jsonl), script [eval_fidelity.py](../../repro/eval_fidelity.py), và `judge_agreement.py`.
  - **Ca kiểm thử biên (Edge Cases)**: Thêm 15–20 ca test biên phức tạp vào `dataset.jsonl` (sản phẩm 0 review, sản phẩm review chỉ có rating không có text, review chứa PII SĐT/Email - Loại B, review mâu thuẫn khen/chê).
  - **Mục tiêu Pass Rate**: Chạy lại bộ eval harness và báo cáo Pass Rate cải thiện sau khi tối ưu hóa Prompt (đạt **≥ 90%**).
  - **Đo lường Judge-Human Agreement**: Chạy `eval_support/judge_agreement.py` so sánh phán quyết của Judge với nhãn thủ công trong `human_labeled_cases.jsonl` để đạt tỷ lệ đồng thuận **≥ 85%**.

---

## TICKET 5: Triển khai PostgreSQL Static Summary Fallback (Tầng 2) (🟢 HOÀN THÀNH)
* **Người thực hiện (Assignee):** Kiên
* **Epic:** AIE1 - Mandate #22 Closed-Loop Mitigation (Tuần 4)
* **Ưu tiên:** High (P1)
* **Label Jira:** `ai-mandate`, `m22`

### Mô tả công việc (Description)
Hoàn thiện kiến trúc Fallback 3 tầng thực tế theo đúng thiết kế ban đầu tại ADR 0002. Tích hợp tầng 2 bằng cách truy vấn bảng `product_summaries` từ PostgreSQL ở runtime và thực hiện cơ chế ghi đè tóm tắt khi LLM thành công.

### Các tác vụ con (Sub-tasks)
* **[x] Sub-task 5.1: Thiết kế bảng `product_summaries` (Kiên)**
  - Tạo cấu trúc bảng lưu trữ các bản tóm tắt tĩnh được phê duyệt: `product_id` (PK), `summary_text`, `rating_distribution`, `review_version`, `updated_at`.
* **[x] Sub-task 5.2: Triển khai logic ghi đè tóm tắt (Kiên)**
  - Khi LLM và Judge thành công (Pass), tiến hành lưu/ghi đè bản tóm tắt mới nhất vào bảng `product_summaries` để cập nhật dữ liệu.
* **[x] Sub-task 5.3: Tích hợp truy vấn Tầng 2 ở runtime (Kiên)**
  - Cập nhật cơ chế fallback: Khi cuộc gọi LLM Bedrock/OpenAI bị lỗi (gặp ngoại lệ mạng/timeout/Rate limit và Circuit Breaker đang OPEN), trước khi trả về tin nhắn lỗi tĩnh (Tầng 3), hãy thực hiện truy vấn bảng `product_summaries`. Nếu tìm thấy bản tóm tắt cũ của sản phẩm đó → trả về kết quả này (Tầng 2), ngược lại mới trả về generic error message (Tầng 3).

---

## 📅 LỊCH SPRINT CHI TIẾT THEO NGÀY (TUẦN 4)

| Ngày | Khoa (Leader) | Thịnh | Kiên |
|------|---------------|-------|------|
| **T2 26/07** | - Thiết lập cờ cache hit/miss qua gRPC metadata (1.1)<br>- Cách ly cache theo `user_id` (1.2) | - Trích xuất OTel Trace ID qua metadata gRPC (2.1)<br>- Thiết lập trace JSON lưu Redis (2.2)<br>- Dựng HTTP server phụ cổng 8086 (2.3) | - Thiết kế & triển khai class `CircuitBreaker` (3.1)<br>- Validate arguments & bọc try-except JSON tool calls (3.2) |
| **T3 27/07** | **[DEADLINE T1]**<br>- Đo lường cache hit-rate & latency (1.3)<br>- Viết/cập nhật ADR 0005 (1.3)<br>- Nghiệm thu hoàn tất Ticket 1 (Mandate 23) | **[DEADLINE T2]**<br>- Hoàn thiện HTTP server, code endpoint `/replay` & `/trace` (2.3)<br>- Soạn thảo ADR 0008 (2.4)<br>- Nghiệm thu hoàn tất Ticket 2 (Mandate 24) | **[DEADLINE T3]**<br>- Tạo cổng nạp lỗi giả lập `POST /inject` (3.3)<br>- Viết/cập nhật ADR 0007 (3.4)<br>- Nghiệm thu hoàn tất Ticket 3 (Mandate 25) |
| **T4 28/07** | - Hỗ trợ review, kiểm định chéo và kiểm thử tích hợp | - Phân tích prompt Candidate & cases Judge từ chối nhầm (4.1 & 4.2) | - Thiết kế schema bảng `product_summaries` (5.1)<br>- Code logic ghi đè tóm tắt khi LLM Pass (5.2) |
| **T5 29/07** | - Tải kiểm thử (Load test) caching & hỗ trợ team | - Tinh chỉnh prompt Candidate & Judge (4.1 & 4.2) | - Tích hợp fallback Tầng 2 Postgres ở runtime (5.3) |
| **T6 30/07** | - Nghiệm thu tích hợp & kiểm thử chéo | - Bổ sung edge cases & Chạy test-suite đánh giá (4.3)<br>- Hoàn tất Ticket 4 | - Chạy liên kết e2e Closed-loop với AIOps<br>- Hoàn tất Ticket 5 |
| **T7 31/07** | - Nghiệm thu tổng thể & Nộp bài | - Nghiệm thu tổng thể & Nộp bài | - Nghiệm thu tổng thể & Nộp bài |
