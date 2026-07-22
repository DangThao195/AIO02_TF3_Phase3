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
Triển khai thiết kế bộ nhớ đệm 2 tầng (LLM response cache bằng Redis và Regex filter cache bằng DB Column `is_safe`) theo ADR 0005 để tối ưu hóa latency và chi phí token. Thực hiện đo đạc so sánh số liệu Cost/Latency trước và sau khi tích hợp cache.

### Các tác vụ con (Sub-tasks)

#### Sub-task 2.0: Đo baseline "Before Caching" [Thứ 2 sáng] — Priority: Highest
> Bắt buộc phải làm trước khi sửa code, nếu không sẽ mất số liệu đối chứng.
- Chạy benchmark đo latency p95, p99 và token usage khi chưa bật cache.
- Ghi nhận kết quả vào file `repro/artifacts/cost_latency_BEFORE_cache.json`.

#### Sub-task 2.1: PostgreSQL Migration cột `is_safe` [Thứ 2 sáng] — Priority: Medium
- Tạo và chạy migration script thêm cột `is_safe BOOLEAN DEFAULT TRUE` vào bảng `reviews.productreviews`.
- Viết background worker chạy một lần quét và cập nhật `is_safe` cho các review cũ dựa trên regex guardrail.
- Sửa các SQL query trong `database.py` để lọc `WHERE is_safe = TRUE`.

#### Sub-task 2.2: Cấu hình Redis & Caching logic [Thứ 2 chiều - Thứ 3] — Priority: Highest
> Cấu trúc hạ tầng dùng chung cho cả Caching và Closed-Loop.
- Thêm thư viện `redis` và cấu hình service Redis vào local docker-compose/K8s.
- Viết module `guardrails/cache.py` dùng băm `SHA256` của input làm cache key. Thiết lập cơ chế Fail-Open (Redis sập, dịch vụ vẫn gọi LLM bình thường).
- Dành riêng Redis key `product_reviews:fallback_override` làm cổng điều phối Closed-loop cho Kiên.

#### Sub-task 2.3: Tích hợp Cache vào product_reviews_server.py [Thứ 3] — Priority: High
- Tích hợp kiểm tra cache ở đầu hàm `AskProductAIAssistant` (Cache Hit -> trả kết quả trong < 10ms).
- Lưu kết quả vào Redis sau khi LLM Judge duyệt thành công (`approved == True`).

#### Sub-task 2.4: Đo Cost/Latency After Caching & So sánh [Thứ 4] — Priority: High
- Chạy lại benchmark khi đã có cache.
- So sánh số liệu Cost/Latency before/after và lưu kết quả đối chiếu vào `repro/artifacts/cost_latency_comparison.json`.

#### Sub-task 2.5: Đóng gói, Viết ADR 0006 và Tạo Jira Ticket `AI MANDATE #14 [TF3]` [Thứ 5] — Priority: Highest
- Soạn thảo tài liệu ADR 0006 trong `docs/adr/` ký tên đầy đủ các thành viên.
- Tạo Jira ticket và đính kèm đầy đủ 4 evidences yêu cầu của BTC.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Có file baseline `cost_latency_BEFORE_cache.json` trước khi sửa code.
- [ ] Redis cache hoạt động ổn định với cơ chế Fail-Open và phản hồi Cache Hit < 10ms.
- [ ] Cột `is_safe` được thêm vào DB thành công và tích hợp vào SQL query.
- [ ] File đối chiếu latency/cost after cache được xuất ra.
- [ ] ADR 0006 được phê duyệt và commit.
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
- [ ] Cả 3 thành viên hoàn thành đọc và thảo luận tài liệu và hiểu rõ các tiêu chí áp dụng cho ngữ cảnh chính của dự án.
- [ ] Bộ rubrics đánh giá được ghi nhận chi tiết trong ADR 0006.
- [ ] Tệp `repro/datasets/human_labeled_cases.jsonl` được tạo thành công với ≥ 10 cases được đồng thuận nhãn.

---

## 📅 LỊCH SPRINT CHI TIẾT THEO NGÀY (Tuần 3)

| Ngày | Khoa (Leader) | Thịnh | Kiên |
|------|------|-------|------|
| **T2 21/07** | - Đo baseline Before (2.0)<br>- DB Migration `is_safe` (2.1)<br>- Đọc tài liệu LLM Judge (4.1)<br>- Họp sync rubrics & gán nhãn (4.2) | - Thiết kế cấu hình harness (1.1)<br>- Thêm surface field vào dataset (1.2)<br>- Đọc tài liệu LLM Judge (4.1)<br>- Họp sync rubrics & gán nhãn (4.2) | - Thống nhất Redis key schema với Khoa (3.1)<br>- Thiết kế & viết ADR 0007 (3.1)<br>- Đọc tài liệu LLM Judge (4.1)<br>- Họp sync rubrics & gán nhãn (4.2) |
| **T3 22/07** | - Viết module `cache.py` (2.2)<br>- Đồng bộ Redis key cho Closed-Loop | - Bổ sung PII-in-review cases (1.2)<br>- Viết script `eval_support/judge_agreement.py` (1.3) | - Triển khai Redis Actuator trong product_reviews_server.py (3.2)<br>- Thêm Failure Injection Mode (3.3) |
| **T4 23/07** | - Đo After + So sánh before/after (2.4)<br>- Viết ADR 0006 (2.5) | - Fix timeout & UNVERIFIED pass rate (1.4)<br>- Đóng gói Makefile (1.5) | - Tích hợp Custom Prometheus Metrics (3.4)<br>- Graceful Shutdown & Reconnect (3.6)<br>- Viết logic log kiểm toán (3.5) |
| **T5 24/07** | - Đóng gói ticket #14 (2.5)<br>- Nộp Jira ticket #14 | - Chạy thử nghiệm e2e harness (1.6)<br>- Chụp terminal, xuất results.json gửi Khoa | - Phối hợp test E2E với AIOps (3.5)<br>- Đóng gói ticket #22 & Nộp Jira |
| **T6 25/07** | Kiểm tra chéo các ticket của nhóm, chuẩn bị môi trường chạy thật trước hạn | Hỗ trợ review, kiểm định chéo | Hỗ trợ review, kiểm định chéo |
