# Kế hoạch Phân chia Công việc Tuần 3 - Nhóm AIE1 (JIRA TODO)

Tài liệu này chứa nội dung chi tiết các công việc tuần 3 (21/07 – 25/07/2026) được thiết kế dưới dạng các ticket **JIRA TODO** cho 3 thành viên: **Khoa** (Leader), **Thịnh**, và **Kiên**. 

Kế hoạch đã được tối ưu hóa triệt để để giảm tải công việc ("giảm bớt công việc thừa"), loại bỏ các phần không thuộc phạm vi của nhóm AIE1:
1. **Loại bỏ Shopping Copilot (Phần B):** Chỉ tập trung đánh giá 2 bề mặt của dịch vụ `product-reviews` (Tóm tắt review tự động và Trợ lý hỏi đáp Ask AI).
2. **Loại bỏ việc tự xây dựng AIOps Engine / Detector độc lập:** Trách nhiệm này thuộc nhóm AIOps của Task Force. Nhóm AIE1 chỉ tập trung xây dựng **Cổng điều khiển sự cố (Actuator)**, **Failure Injection Mode** và **Custom Telemetry Metrics** ngay bên trong mã nguồn `product-reviews`.
3. **Tái sử dụng tối đa code eval hiện có:** Không viết lại script eval từ đầu mà tận dụng/đóng gói `run_eval_guardrail.py` và `eval_fidelity.py` đã hoàn thiện ở tuần trước.

> **Deadline cứng:** Thứ Bảy **25/07/2026** — Hoàn thành và nộp `AI MANDATE #14` và `AI MANDATE #22`.

---

## 🔴 PHÂN TÍCH TIẾN ĐỘ & GAP THỰC TẾ (Tính đến 21/07)

### Đã hoàn thành tốt (Tuần 1 & 2) ✅
- ADR 0001–0005 đã được phê duyệt và commit trong [docs/adr/](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/adr/).
- Guardrails 4 tầng và Fallback 3 tầng đã hoạt động tốt trên `product-reviews`.
- Script đánh giá chất lượng `eval_fidelity.py` và script test an sau `run_eval_guardrail.py` đã hoàn chỉnh.
- Dữ liệu 200 cases (`dataset.jsonl`) đã được commit và sẵn sàng chạy thử nghiệm.

### Các khoảng trống (Gap) cần xử lý tuần này ❌
- **Mandate #14 (AI Eval Standard):**
  - Thiếu case kiểm thử **PII-in-review (Loại B - PII nhúng trong nội dung review)** trong `dataset.jsonl` để test khả năng lọc PII khi tóm tắt.
  - Thiếu tệp `human_labeled_cases.jsonl` (≥ 10 cases) và cơ chế tính toán độ khớp (Agreement Rate) giữa LLM Judge và con người.
  - Chưa đóng gói Makefile một lệnh chạy cho cả 2 surface (summary và ask-ai).
  - Chưa đo lường latency/cost **Before Caching** để làm đối chứng.
- **Mandate #22 (Closed-Loop Mitigation):**
  - Dịch vụ `product-reviews` chưa có Actuator (cổng nhận lệnh) để tự chuyển sang PostgreSQL Cache/Fallback động.
  - Chưa có cơ chế giả lập lỗi kết nối LLM (Failure Injection Mode) để đội AIOps kích hoạt kịch bản replay.
  - Chưa xuất custom metric lỗi LLM (như `app_ai_fallback_total`) để Prometheus thu thập.

---

## 📋 PHÂN CHIA CÔNG VIỆC TỔNG QUAN

| Người | Vai trò chính tuần 3 | Phạm vi thực hiện |
|-------|-------------------|-------------------|
| **Thịnh** | Hoàn thiện Eval Harness (summary & ask-ai) + Dataset bổ sung + Đo lường Judge-Human Agreement | Repro / Evaluator |
| **Khoa** | Triển khai Caching (Redis + is_safe) + Đo lường Cost/Latency Before/After | Product-Reviews Service |
| **Kiên** | Xây dựng Actuator (Redis key) + Telemetry Metrics + Failure Injection (Closed-Loop) | Product-Reviews Service |

---

## TICKET 1: Hoàn thiện Eval Harness & Đóng gói MANDATE #14 (Tính năng Product-Review)
* **Người thực hiện (Assignee):** Thịnh
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #14 AI Eval Standard (Tuần 3)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m14`

### Mô tả công việc (Description)
Tận dụng các script đánh giá an toàn (`run_eval_guardrail.py`) và độ trung thực (`eval_fidelity.py`) sẵn có để đóng gói thành công cụ kiểm thử tự động một lệnh. Bổ sung tập dữ liệu human labels, xây dựng cơ chế đo độ khớp Judge-Human và thu thập bằng chứng chạy thật.

### Các tác vụ con (Sub-tasks)

#### Sub-task 1.1: Tận dụng và cấu hình eval runner [Thứ 2] — Priority: Highest
> Blocker cho toàn bộ Ticket 1.
- Nghiên cứu tham số đầu vào của `run_eval_guardrail.py` và `eval_fidelity.py`.
- Tối ưu hóa việc lọc tập test cases từ `dataset.jsonl` dựa trên các nhãn hành vi có sẵn.

#### Sub-task 1.2: Bổ sung PII-in-review (Loại B) và routing surface vào dataset [Thứ 2–3] — Priority: Highest
> Bắt buộc để vượt qua bộ ca ẩn của BTC.
- Thêm các ca kiểm thử **Review chứa PII (Loại B)** vào `repro/datasets/dataset.jsonl` (ví dụ: review của khách chứa SĐT/Email thật). Đảm bảo LLM tóm tắt không bị rò rỉ các thông tin này.
- Thêm trường `"surface"` vào từng dòng JSONL để phân biệt case nào chạy cho `"summary"` và case nào chạy cho `"ask-ai"`.

#### Sub-task 1.3: Đo lường độ khớp Judge-Human (Agreement Rate) [Thứ 3] — Priority: High
> Yêu cầu bắt buộc của Mandate #14 đối với LLM Judge.
- Viết script `repro/eval_support/judge_agreement.py` để chạy LLM Judge trên 10 cases trong `human_labeled_cases.jsonl` (do cả nhóm gán nhãn từ Ticket 4).
- So sánh kết quả chấm điểm của Judge với nhãn của con người và tính toán tỷ lệ khớp (`Agreement Rate = Số ca khớp / Tổng số ca >= 80%`). Xuất kết quả ra dạng bảng.

#### Sub-task 1.4: Fix Normal & Toxic Pass Rate & Timeout [Thứ 3–4] — Priority: High
- Điều chỉnh prompt của Judge để loại bỏ các phán quyết `UNVERIFIED` sai lệch.
- Thiết lập gRPC timeout ở mức hợp lý (45s cho harness kiểm thử để tránh rớt do mạng chậm, giữ 3s cho client thực tế).

#### Sub-task 1.5: Makefile repro [Thứ 4] — Priority: Medium
Cấu hình target trong `Makefile` ở thư mục root để chạy toàn bộ suite kiểm thử bằng 1 lệnh:
```makefile
eval-mandate14:
	python repro/run_eval_guardrail.py --dataset repro/datasets/dataset.jsonl --out repro/artifacts/guardrail_results.json
```

#### Sub-task 1.6: Thu thập bằng chứng chạy thật cho Jira (Evidence #3) [Thứ 5] — Priority: Highest
> Thiếu bằng chứng chạy thật ticket sẽ bị mentor từ chối duyệt.
- Chạy thử nghiệm e2e trên EKS/local. Chụp lại kết quả output từ terminal (tổng số case, pass rate, block rate).
- Ghi nhận đường dẫn tệp JSON artifact chứa kết quả đánh giá chi tiết.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Tập dữ liệu `dataset.jsonl` có đầy đủ ca kiểm thử PII-in-review và multi-turn injection.
- [ ] Script `eval_support/judge_agreement.py` chạy thành công, xuất ra bảng so sánh và tỷ lệ khớp đạt ≥ 80%.
- [ ] Target `eval-mandate14` trong Makefile chạy thành công, không gặp lỗi runtime.
- [ ] Ảnh chụp màn hình và log chạy thật được đính kèm đầy đủ vào Jira ticket.

---

## TICKET 2: Triển khai Caching (ADR 0005) & Đo lường Cost/Latency
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Tối ưu hóa Hiệu năng AI (Tuần 3)
* **Ưu tiên:** High (P0)

### Mô tả công việc (Description)
Triển khai thiết kế bộ nhớ đệm 2 tầng (LLM response cache bằng Redis và Regex filter cache bằng DB Column `is_safe`) theo ADR 0005 để tối ưu hóa latency và chi phí token. Tích hợp các giải pháp chống thừng nghẽn Cache Stampede và Asynchronous Logging cho AWS RDS theo tài liệu [PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/analysis/PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md). Thực hiện đo đạc đối chứng Cost/Latency trước và sau khi có cache.

### Các tác vụ con (Sub-tasks)

#### Sub-task 2.0: Đo baseline "Before Caching" [Thứ 2 sáng] — Priority: Highest
> Bắt buộc phải làm trước khi sửa code, nếu không sẽ mất số liệu đối chứng.
- Ghi nhận kết quả đo benchmark latency p95, p99 và token usage khi chưa bật cache.
- Lưu trữ kết quả chính xác vào file `repro/artifacts/cost_latency_BEFORE_cache.json` (Đã hoàn thành và push lên Git).

#### Sub-task 2.1: PostgreSQL Migration cột `is_safe` & Background Worker [Thứ 2 sáng] — Priority: Medium (Đã hoàn thành)
- [x] Tạo file script SQL di dân `migration.sql` thêm cột `is_safe BOOLEAN DEFAULT TRUE` và index `productreviews_prod_safe_idx` vào bảng `reviews.productreviews`.
- [x] Tạo background worker script `db_migration_worker.py` chạy theo batch (kèm sleep) để quét toàn bộ review cũ và cập nhật `is_safe = FALSE` nếu vi phạm bộ lọc Regex Guardrail.
- [x] Cập nhật các SQL query trong `database.py` để chỉ đọc các review sạch (`WHERE is_safe = TRUE`).

#### Sub-task 2.2: Cấu hình Redis & logic Cache Key / Invalidation / Lock [Thứ 2 chiều - Thứ 3] — Priority: Highest
> Cấu trúc hạ tầng dùng chung cho cả Caching và Closed-Loop.
- Thêm thư viện `redis` và cấu hình service Redis/Valkey kết nối bảo mật bằng SSL/TLS (`rediss://`).
- Viết module `guardrails/cache.py` định nghĩa Cache Key động: `SHA256(product_id + review_version + model_id + question)`.
- Triển khai hàm `get_review_version(product_id)` trong `database.py` dựa trên `COUNT(*)` và `MAX(id)` để tự động invalidation khi có review mới hoặc thay đổi trạng thái an toàn.
- Triển khai cơ chế **chống Cache Stampede (Thundering Herd)** bằng khóa phân tán Redis `SET NX EX 10` để chỉ 1 request đồng thời gọi LLM khi cache miss.
- Thiết lập cơ chế **Fail-Open** (Redis sập, dịch vụ vẫn gọi LLM bình thường).

#### Sub-task 2.3: Tích hợp Cache & Asynchronous Logging vào server [Thứ 3] — Priority: High (Đã hoàn thành)
- [x] Tích hợp kiểm tra cache ở đầu hàm `AskProductAIAssistant` (Cache Hit -> trả kết quả trong < 10ms).
- [x] Áp dụng Cache Policy (Chỉ cache khi Judge duyệt thành công `approved == True`, không cache thông báo lỗi/lạc đề/thiếu thông tin).
- [x] Triển khai **Asynchronous Logging** bằng `ThreadPoolExecutor` để thực hiện ghi log kiểm toán Fidelity Audit xuống PostgreSQL (AWS RDS) chạy nền, tránh nghẽn I/O trên luồng gRPC chính.

#### Sub-task 2.4: Đo Cost/Latency After Caching & So sánh [Thứ 4] — Priority: High (Đã hoàn thành)
- [x] Chạy lại benchmark đo lường sau khi tích hợp cache.
- [x] So sánh số liệu trước/sau và lưu kết quả đối chiếu vào `repro/artifacts/cost_latency_comparison.json`.

#### Sub-task 2.5: Đóng gói, Viết ADR 0006 và Tạo Jira Ticket `AI MANDATE #14 [TF3]` [Thứ 5] — Priority: Highest
- Soạn thảo tài liệu ADR 0006 trong `docs/adr/` ký tên đầy đủ các thành viên.
- Tạo Jira ticket và đính kèm đầy đủ 4 evidences yêu cầu của BTC.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Có file baseline `cost_latency_BEFORE_cache.json` trước khi sửa code.
- [x] Redis cache hoạt động với cơ chế Fail-Open, TLS bảo mật (`rediss://`) và phản hồi Cache Hit < 10ms.
- [x] Logic sinh Cache Key chứa `review_version` (tự động invalidate) và `model_id`.
- [x] Triển khai thành công khóa phân tán chống Cache Stampede.
- [x] Cột `is_safe` và index được thêm vào DB thành công; queries lọc review sạch hoàn tất.
- [x] Tích hợp Asynchronous Logging ghi audit log xuống RDS chạy nền.
- [x] File đối chiếu latency/cost after cache được xuất ra.
- [x] ADR 0006 được phê duyệt và commit.
- [ ] Jira ticket được tạo đúng format với đầy đủ bằng chứng.

---

## TICKET 3: Thiết lập Cổng điều khiển Sự cố (Actuator) & Telemetry cho Closed-Loop (MANDATE #22)
* **Người thực hiện (Assignee):** Kiên
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #22 Closed-Loop Mitigation (Tuần 3)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m22`

### Mô tả công việc (Description)
Không tự xây dựng AIOps Engine (detector độc lập). Nhiệm vụ của AIE1 là tinh chỉnh mã nguồn `product-reviews` để: (1) Nhận lệnh từ Redis key để tự động kích hoạt fallback/cache động, (2) Xuất custom metrics lỗi kết nối Bedrock để AIOps giám sát, (3) Triển khai chế độ bơm lỗi giả lập để test kịch bản và (4) Viết ADR 0007.

### Các tác vụ con (Sub-tasks)

#### Sub-task 3.1: Thống nhất Redis key schema & Thiết kế [Thứ 2] — Priority: Highest
- Họp sync với Khoa thống nhất schema Redis key điều khiển: `product_reviews:fallback_override` (String, `"true"` hoặc `"false"`).
- Thống nhất các metric sẽ xuất ra cho Prometheus và viết tài liệu thiết kế ADR 0007.

#### Sub-task 3.2: Triển khai Cổng nhận lệnh (Actuator) trong product_reviews_server.py [Thứ 3] — Priority: Highest
> Trái tim của cơ chế tự dập sự cố.
- Sửa hàm `get_ai_assistant_response` để kiểm tra Redis key `product_reviews:fallback_override` trước khi gọi Bedrock.
- Nếu key là `"true"` hoặc `"1"` -> lập tức kích hoạt luồng fallback PostgreSQL Cache (hoặc Static summary), bypass hoàn toàn cuộc gọi Bedrock.

#### Sub-task 3.3: Triển khai Failure Injection Mode [Thứ 3] — Priority: Highest
> Bắt buộc để phục vụ kịch bản replay test của BTC và đội AIOps.
- Viết cơ chế cho phép ép lỗi kết nối Bedrock (giả lập lỗi Rate Limit 429 hoặc timeout) khi nhận được tín hiệu đặc biệt (ví dụ: qua feature flag `llmRateLimitError` của flagd hoặc một gRPC header/metadata đặc thù).

#### Sub-task 3.4: Bổ dung Custom Telemetry Metrics [Thứ 4] — Priority: High
- Cấu hình file `metrics.py` và `product_reviews_server.py` để xuất custom metric Prometheus đếm số lỗi kết nối LLM (ví dụ: `app_ai_fallback_total{source="rate_limit", error="429"}`).
- Đảm bảo metric này được hiển thị đầy đủ trên endpoint metrics của pod.

#### Sub-task 3.5: Phối hợp kiểm thử E2E & Tạo Jira Ticket `AI MANDATE #22 [TF3]` [Thứ 5] — Priority: Highest
- Phối hợp với đội AIOps chạy kịch bản replay: Bơm lỗi -> AIOps Detector phát hiện -> AIOps Controller set Redis key thành true -> product-reviews tự chuyển sang Cache -> AIOps verify lỗi giảm -> Rollback (delete Redis key) -> Hệ thống tự phục hồi.
- Đảm bảo file `audit_log.json` ghi nhận đầy đủ chuỗi: trigger -> action -> verify -> rollback.
- Tạo Jira ticket và đính kèm đầy đủ 4 evidences.

#### Sub-task 3.6: Triển khai Graceful Shutdown & Reconnection Logic [Thứ 4] — Priority: High
- Thiết lập gRPC Health Check status thành `NOT_SERVING` và bắt tín hiệu hệ thống (như SIGTERM/SIGINT) để kích hoạt `server.stop(grace=5.0)` cho phép gRPC server đóng kết nối một cách êm ái khi AIOps Engine yêu cầu hạ tải hoặc bảo trì.
- Viết logic tự động kết nối lại (auto-reconnection) với các phụ thuộc (PostgreSQL, Redis, Product Catalog) khi khởi động lại dịch vụ để tránh crash pod lúc startup.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Actuator nhận lệnh từ Redis key hoạt động đúng (key = true -> bypass Bedrock).
- [ ] Chế độ Failure Injection hoạt động tốt khi bật flag giả lập lỗi.
- [ ] Custom metrics xuất ra đúng định dạng và thu thập được từ Prometheus.
- [ ] Cơ chế Graceful Shutdown đóng kết nối êm ái khi nhận tín hiệu tắt; gRPC Health Check báo đúng trạng thái.
- [ ] Hệ thống tự động kết nối lại cơ sở dữ liệu và Redis khi restart dịch vụ.
- [ ] Test E2E thành công với đội AIOps, có log rollback hoạt động.
- [ ] ADR 0007 được commit đúng format và ký tên.
- [ ] Jira ticket được tạo với đầy đủ bằng chứng chạy thật.

---

## TICKET 4: Nghiên cứu tài liệu LLM-as-a-Judge & Thống nhất bộ rubric đánh giá
* **Người thực hiện (Assignee):** Cả nhóm (Thịnh, Khoa, Kiên)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #14 AI Eval Standard (Tuần 3)
* **Ưu tiên:** High (P1)
* **Label Jira:** `ai-mandate`, `m14`, `research`

### Mô tả công việc (Description)
Cả nhóm nghiên cứu tài liệu `D:\AI\Book\LLM-as-a-Judge.pdf` với mục tiêu hiểu rõ được các tiêu chí, nguyên tắc khi xây dựng và tích hợp LLM-as-a-judge vào trong **ngữ cảnh chính** của hệ thống (đánh giá chất lượng tóm tắt reviews và trợ lý hỏi đáp Ask AI). Từ đó thống nhất phương pháp thiết kế prompt cho LLM Judge, rubric chấm điểm và cơ chế gán nhãn của con người (human labels) để kiểm chứng độ chính xác của judge (Agreement Rate).

### Các tác vụ con (Sub-tasks)

#### Sub-task 4.1: Nghiên cứu tài liệu LLM-as-a-Judge [Thứ 2 sáng] — Priority: High
- Đọc tài liệu tại `D:\AI\Book\LLM-as-a-Judge.pdf`.
- Xác định và làm rõ các tiêu chí chấm điểm tự động (rubrics) phù hợp với ngữ cảnh chính (Product Reviews & Ask AI).
- Nắm rõ cách xử lý các bias của LLM Judge (verbosity bias, position bias, self-enhancement bias) để hiệu chuẩn prompt của Judge.

#### Sub-task 4.2: Họp sync thống nhất bộ Rubric & Gán nhãn thủ công [Thứ 2 chiều] — Priority: High
- Cả nhóm họp sync ngắn thống nhất bộ tiêu chí (rubric) chấm Fidelity (faithfulness, aspect_coverage, sentiment_alignment) trong ngữ cảnh chính của hệ thống.
- Chọn ra ít nhất 10 cases thực tế từ reviews để cả nhóm cùng đánh giá bằng tay (human grading) và lưu vào `repro/datasets/human_labeled_cases.jsonl` để làm mốc tính Agreement Rate cho Thịnh.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Cả 3 thành viên hoàn thành đọc và thảo luận tài liệu và hiểu rõ các tiêu chí áp dụng cho ngữ cảnh chính của dự án.
- [x] Bộ rubrics đánh giá được ghi nhận chi tiết trong ADR 0006.
- [x] Tệp `repro/datasets/human_labeled_cases.jsonl` được tạo thành công với ≥ 10 cases được đồng thuận nhãn.

---

## TICKET 5: Tích hợp Bộ nhớ đệm (Caching) & Đảm bảo Ranh giới Người dùng (MANDATE #23)
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #23 GenAI Caching & Memory (Tuần 3)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m23`

### Mô tả công việc (Description)
Tận dụng lớp Caching bằng Redis sẵn có của `product-reviews`. Do dịch vụ `product-reviews` là dạng hỏi đáp đơn lượt (Single-Turn Q&A), Mentor đã xác nhận **không cần triển khai bộ nhớ ngắn hạn và dài hạn (Memory)**. Nhóm chỉ tập trung vào cơ chế trả cờ cache và cách ly cache theo ranh giới người dùng.

### Các tác vụ con (Sub-tasks)
* **Sub-task 5.1: Thiết lập cờ trạng thái Cache qua gRPC Metadata (Trailing Headers)**
  - Chỉnh sửa hàm `get_ai_assistant_response` trong `product_reviews_server.py`.
  - Khi có Cache Hit (tìm thấy dữ liệu trong Redis cache), thiết lập trailing metadata `cache = hit` bằng cách gọi `context.set_trailing_metadata([('cache', 'hit')])`.
  - Khi có Cache Miss (gọi LLM và được Judge duyệt), thiết lập trailing metadata `cache = miss` bằng cách gọi `context.set_trailing_metadata([('cache', 'miss')])`.
  - Đảm bảo trong mọi trường hợp rẽ nhánh (bao gồm cả trường hợp deterministic hoặc fallback), cờ `cache: miss` vẫn được trả về đầy đủ mà không gây lỗi runtime.
* **Sub-task 5.2: Phân tách ranh giới và cách ly Cache theo `user_id`**
  - Trích xuất `user_id` từ gRPC invocation metadata bằng cách duyệt qua `context.invocation_metadata()` để tìm khóa `x-user-id` hoặc `user-id`.
  - Sửa hàm `generate_cache_key` trong `guardrails/cache.py` để nhận thêm tham số `user_id` (nếu có).
  - Tích hợp `user_id` vào chuỗi băm tạo key: `SHA256(product_id + review_version + model_id + question + user_id)`.
  - Nếu request không chứa `user_id`, sử dụng một giá trị mặc định là `"anonymous"` để tránh lỗi chuỗi `None`.
* **Sub-task 5.3: Đo lường chỉ số & Soạn thảo ADR 0005**
  - Thực hiện chạy bộ ca test có lặp để đo lường và thống kê `cache hit-rate`, so sánh latency/cost trước/sau cache.
  - Lưu kết quả benchmark đối chứng vào tệp tin JSON trong thư mục `repro/artifacts/`.
  - Cập nhật tài liệu quyết định kiến trúc `docs/adr/0005-CACHING-STRATEGY.md` giải thích thuật toán sinh key cách ly theo user và cơ chế invalidation theo `review_version`.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Cờ `cache: hit` hoặc `cache: miss` hoạt động chính xác trên từng request.
- [ ] Cache được cách ly độc lập theo `user_id` để tránh rò rỉ chéo thông tin.
- [ ] Có báo cáo số liệu hit-rate và so sánh hiệu năng thực tế.

---

## TICKET 6: Dựng Hộp Đen Giám Sát LLM & Cổng Replay/Fetch Trace (MANDATE #24)
* **Người thực hiện (Assignee):** Thịnh
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #24 LLM Observability (Tuần 3)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m24`

### Mô tả công việc (Description)
Xây dựng hệ thống Trace cho mọi cuộc gọi LLM (Candidate + Judge), trả về `trace-id` cho client, lưu vết chi tiết (token, cost, latency, outcome) xuống Redis và cung cấp cổng HTTP phụ để truy vấn trace chi tiết theo ID.

### Các tác vụ con (Sub-tasks)
* **Sub-task 6.1: Trích xuất OTel Trace ID và trả về qua gRPC Metadata**
  - Trong hàm `get_ai_assistant_response`, import thư viện OpenTelemetry `trace`.
  - Lấy span hiện tại bằng `trace.get_current_span()` và trích xuất `trace_id` thông qua `span.get_span_context().trace_id`.
  - Định dạng `trace_id` sang dạng chuỗi hexa 32 ký tự (`format(trace_id, '032x')`).
  - Trả về trace ID cho Client bằng cách set trailing metadata: `context.set_trailing_metadata([('trace-id', trace_id_str)])`.
* **Sub-task 6.2: Ghi nhận Trace chi tiết (Black Box) vào Redis**
  - Sau mỗi cuộc gọi LLM (Candidate + Judge), tạo cấu trúc dữ liệu JSON để lưu trữ thông tin trace chi tiết bao gồm: `trace_id`, `timestamp` (ISO 8601), `model` + `version`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `outcome` (OK/Error/Fallback), `session_id`, `user_id` và `masked_prompt`.
  - Đảm bảo prompt và câu hỏi được chạy qua hàm làm sạch `_sanitize_prompt_value` để xóa bỏ PII và các ký tự độc hại trước khi ghi trace log.
  - Sử dụng Redis client để lưu bản ghi JSON này dưới khóa `trace:{trace_id}` với thời gian hết hạn (TTL) là 24 giờ.
* **Sub-task 6.3: Xây dựng Cổng HTTP Replay & Fetch Trace**
  - Viết một class HTTP handler sử dụng thư viện chuẩn `http.server.BaseHTTPRequestHandler` chạy trên một luồng riêng (`threading.Thread`) song song trên cổng `8086`.
  - Triển khai endpoint `POST /replay`: nhận `{question, product_id, user_id, session_id}`, gọi hàm xử lý AI nội bộ, trả về phản hồi JSON dạng `{"response": "...", "cache": "hit|miss", "trace_id": "..."}`.
  - Triển khai endpoint `GET /trace/<trace_id>`: đọc trace tương ứng từ Redis bằng lệnh `redis_client.get(f"trace:{trace_id}")` và trả về JSON thô cho Client (trả về 404 nếu không tìm thấy).
* **Sub-task 6.4: Soạn thảo ADR 0008 & View tổng hợp**
  - Soạn thảo tài liệu quyết định kiến trúc `docs/adr/0008-llm-observability.md` mô tả cấu trúc của bản ghi trace, cơ chế truyền trace-id và cách thức ẩn danh/mask PII.
  - Thống kê và hiển thị chi phí lũy kế, token usage theo model trong view tổng hợp.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Trả về đúng `trace-id` qua metadata gRPC hoặc HTTP replay.
- [ ] Endpoint `GET /trace/<trace_id>` trả về đúng trace đầy đủ các trường cốt lõi.
- [ ] Dữ liệu prompt trong trace được che (mask/hash) hoàn toàn các thông tin PII/secret.

---

## TICKET 7: Tích hợp Circuit Breaker & Chặn Arguments Rác (MANDATE #25)
* **Người thực hiện (Assignee):** Kiên
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #25 AI Resilience & Fallback (Tuần 3)
* **Ưu tiên:** High (P0)
* **Label Jira:** `ai-mandate`, `m25`

### Mô tả công việc (Description)
Nâng cấp độ bền vững của `product-reviews` khi model bị lỗi (timeout, rate-limit, 5xx) hoặc trả về output bị hỏng/sai JSON schema khi gọi tool.

### Các tác vụ con (Sub-tasks)
* **Sub-task 7.1: Tích hợp Circuit Breaker tự phục hồi**
  - Viết một class `CircuitBreaker` quản lý trạng thái (`CLOSED`, `OPEN`, `HALF-OPEN`) lưu trữ trong Redis hoặc bộ nhớ trong của server.
  - Khi có lỗi kết nối LLM hoặc các lỗi tạm thời (429, 5xx, timeout) ghi nhận trong hàm gọi LLM Bedrock/OpenAI, tăng biến đếm lỗi liên tiếp (`consecutive_failures`).
  - Nếu `consecutive_failures >= 5`, chuyển trạng thái sang `OPEN` và đặt thời gian hết hạn (cool-down) là 30 giây. Mọi yêu cầu gRPC tới LLM trong thời gian này sẽ bị chặn ngay lập tức và đi thẳng vào tầng Fallback tĩnh.
  - Sau 30 giây, chuyển sang `HALF-OPEN`. Nếu request thành công, reset biến đếm lỗi và đưa trạng thái về `CLOSED`. Nếu tiếp tục lỗi, đưa về `OPEN`.
* **Sub-task 7.2: Chặn Arguments Rác & Validate Tool Call Schema ở biên**
  - Bọc khối lệnh parse JSON arguments: `json.loads(tool_call.function.arguments)` bằng try-except `json.JSONDecodeError` để tránh crash gRPC server khi LLM trả JSON hỏng, chuyển hướng sang fallback.
  - Viết hàm validate schema đối số: kiểm tra kiểu dữ liệu của `product_id` trong `function_args`, đảm bảo nó là chuỗi ký tự hợp lệ, không rỗng, và không chứa ký tự độc hại. Nếu đối số không hợp lệ (arguments rác), chặn thực thi tool và đi sang fallback path.
* **Sub-task 7.3: Cổng ép lỗi giả lập (Failure & Malformed Output Injection)**
  - Tích hợp endpoint `POST /inject` trên cổng HTTP Server phụ (cổng `8086`) nhận cấu hình lỗi giả lập bao gồm:
    - `{"inject_error": "timeout"|"429"|"500"}`: Lưu cấu hình này vào Redis. Khi server gọi LLM, nếu phát hiện cấu hình, chủ động nâng Exception tương ứng để kích hoạt Circuit Breaker.
    - `{"inject_malformed_tool_args": true}`: Lưu cấu hình. Khi nhận phản hồi có chứa tool call, giả lập ghi đè `tool_call.function.arguments` bằng một chuỗi JSON lỗi để kiểm chứng khả năng chịu lỗi.
* **Sub-task 7.4: Soạn thảo ADR 0007 (Mở rộng)**
  - Cập nhật tài liệu `docs/adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md` bổ sung thiết kế Circuit Breaker, mô tả cơ chế validate JSON schema biên cho tool arguments, và kịch bản phục hồi lỗi có kiểm soát.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Khi LLM lỗi liên tục, Circuit Breaker mở ra chặn dội request, hệ thống phản hồi fallback nhanh.
- [ ] LLM sinh output JSON hỏng hoặc đối số tool rác không làm gRPC server crash, tool không bị thực thi với đối số rác.
- [ ] Inject lỗi giả lập hoạt động đúng kịch bản test của Mentor.

---

## 📅 LỊCH SPRINT CHI TIẾT THEO NGÀY (Tuần 3 - Cập nhật)

| Ngày         | Khoa (Leader)                                                                                                                                             | Thịnh                                                                                                                                                | Kiên                                                                                                                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **T2 21/07** | - Đo baseline Before (2.0)<br>- DB Migration `is_safe` (2.1)<br>- Đọc tài liệu LLM Judge (4.1)<br>- Họp sync rubrics & gán nhãn (4.2)                     | - Thiết kế cấu hình harness (1.1)<br>- Thêm surface field vào dataset (1.2)<br>- Đọc tài liệu LLM Judge (4.1)<br>- Họp sync rubrics & gán nhãn (4.2) | - Thống nhất Redis key schema với Khoa (3.1)<br>- Thiết kế & viết ADR 0007 (3.1)<br>- Đọc tài liệu LLM Judge (4.1)<br>- Họp sync rubrics & gán nhãn (4.2)                             |
| **T3 22/07** | - Viết module `cache.py` (2.2)<br>- Đồng bộ Redis key cho Closed-Loop                                                                                     | - Bổ sung PII-in-review cases (1.2)<br>- Viết script `eval_support/judge_agreement.py` (1.3)                                                         | - Triển khai Redis Actuator trong product_reviews_server.py (3.2)<br>- Thêm Failure Injection Mode (3.3)                                                                              |
| **T4 23/07** | - Đo After + So sánh before/after (2.4)<br>- Viết ADR 0006 (2.5)                                                                                          | - Fix timeout & UNVERIFIED pass rate (1.4)<br>- Đóng gói Makefile (1.5)                                                                              | - Tích hợp Custom Prometheus Metrics (3.4)<br>- Graceful Shutdown & Reconnect (3.6)<br>- Viết logic log kiểm toán (3.5)                                                               |
| **T5 24/07** | - Tích hợp cờ cache hit/miss qua gRPC metadata (5.1)<br>- Cách ly cache theo `user_id` (5.2)<br>- Thu thập kết quả đo lường Caching & viết ADR 0005 (5.3) | - Triển khai cổng HTTP phụ (8086) cho `/replay` và `/trace` (6.3)<br>- Lưu trace JSON vào Redis (6.2)<br>- Trả trace-id qua gRPC metadata (6.1)      | - Thiết kế & Code logic Circuit Breaker (7.1)<br>- Validate arguments gọi tool & bọc try-except (7.2)<br>- Tạo cổng nạp lỗi giả lập `POST /inject` (7.3)<br>- Cập nhật ADR 0007 (7.4) |
| **T6 25/07** | - Hỗ trợ review, kiểm định chéo các tính năng caching                                                                                                     | - Dựng view tổng hợp cost/latency và viết ADR 0008 (6.4)<br>- Nộp Jira Ticket #14 & #24                                                              | - Phối hợp test E2E với AIOps<br>- Nộp Jira Ticket #22 & #25                                                                                                                          |
