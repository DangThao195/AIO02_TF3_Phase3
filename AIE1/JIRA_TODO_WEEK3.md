# Kế hoạch Phân chia Công việc Tuần 3 - Nhóm AIE1 (JIRA TODO)

Tài liệu này chứa nội dung chi tiết các công việc tuần 3 (21/07 – 25/07/2026) đã được tinh chỉnh lại cho nhóm **AIE1** (chỉ tập trung vào **Phần A: Nâng cấp tính năng product-review** và loại bỏ phần Shopping Copilot).

> **Deadline cứng:** Thứ Bảy **25/07/2026** — Nộp `AI MANDATE #14` và `AI MANDATE #22`.

---

## 🔴 PHÂN TÍCH TIẾN ĐỘ & GAP HIỆN TẠI (Tính đến 21/07)

### Đã hoàn thành tốt ✅
- ADR 0001–0005 đã phê duyệt và commit.
- Guardrails 4 tầng đã triển khai cho dịch vụ `product-reviews`.
- Script `eval_fidelity.py` và `run_eval_guardrail.py` đã hoàn chỉnh cho việc đánh giá tóm tắt review.
- Dataset 200 cases (`dataset.jsonl`) đã commit.
- Kết quả benchmark tóm tắt: Attack Block Rate 95.9% (regex-only), Review Guard Rate 100%, Fidelity tổng 85.5%.
- Fallback 3 tầng (ADR 0002) đã triển khai hoạt động trên `product-reviews`.

### Giao điểm công việc cần làm tuần này (Gap)

#### MANDATE #14 (Chỉ áp dụng cho Product-Review) ❌
* **Eval Harness (`eval_harness.py`):** Cần đóng gói thành CLI nhận JSONL từ ngoài, chỉ chạy đánh giá cho surface `summary` (tóm tắt review) và `product-reviews Ask AI`.
* **Dataset:** Bổ sung ca multi-turn injection (nhét trong chat hỏi đáp về review) và review chứa thông tin PII.
* **Bảng judge↔human agreement:** Cần hoàn thiện ≥10 ca người-gán cho tính năng tóm tắt review.
* **Chỉ số:** Đo Abstention (câu hỏi Ask AI ngoài tầm review → trả lời "không có thông tin") và Excessive-agency (nếu có yêu cầu ghi/mua hàng nhét vào Ask AI → phải chặn).
* **repro một lệnh:** `make eval-mandate14` chạy toàn bộ suite test cho product-reviews.

#### MANDATE #22 (Closed-Loop cho Product-Review Service) ❌
* **Closed-loop auto-mitigation:** Tự động phát hiện lỗi kết nối LLM (429/5xx) của dịch vụ `product-reviews` $\rightarrow$ Tự động chuyển cấu hình sang dùng PostgreSQL Cache/Fallback $\rightarrow$ Verify bằng telemetry thật $\rightarrow$ Rollback khi Bedrock phục hồi.
* **Audit log + Replay:** Ghi log 5 tầng và xây dựng kịch bản trigger lỗi để chạy thử nghiệm.

#### Triển khai Caching (ADR 0005) ❌
* Tích hợp Redis cache + cột `is_safe` PostgreSQL để tối ưu hóa latency và chi phí cho dịch vụ `product-reviews`. Phục vụ việc đo latency before/after cho Mandate #14.

---

## 📋 PHÂN CHIA CÔNG VIỆC TỔNG QUAN

| Người | Việc chính tuần 3 | Phạm vi |
|-------|-------------------|---------|
| **Thịnh** | Hoàn thiện Eval Harness + dataset bổ sung + fix pass rate + human labels | Product-Reviews |
| **Khoa** | Triển khai Caching (ADR 0005) + Đo Cost/Latency + Đóng gói Mandate #14 | Product-Reviews |
| **Kiên** | Thiết lập Closed-loop auto-mitigation (Mandate #22) | Product-Reviews |

---

## TICKET 1: Hoàn thiện Eval Harness & Đóng gói MANDATE #14 (Tính năng Product-Review)

* **Người thực hiện (Assignee):** Thịnh
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #14 AI Eval Standard (Tuần 3)
* **Ưu tiên:** P0 — Deadline 25/07
* **Label Jira:** `ai-mandate`, `m14`

### Mô tả công việc (Description)
Hoàn thiện bộ harness đánh giá an toàn và độ trung thực của tính năng product-review (tóm tắt & Ask AI trên reviews). Bổ sung dataset kiểm thử và nâng chất lượng pass rate của hệ thống hiện tại.

### Các tác vụ con (Sub-tasks)

#### Sub-task 1.1: Xây dựng Eval Harness cho Product-Review [Thứ 2–3] — Priority: Highest
> Blocker cho toàn bộ Ticket 1. Không có harness thì không đo được bất kỳ chỉ số nào.
Tạo file `repro/eval_harness.py` nhận file JSONL từ ngoài, chỉ chạy cho service `product-reviews`:
```bash
python repro/eval_harness.py \
  --case-file <path-to-cases.jsonl> \
  --surface summary \
  --output-file results.json
```
Output xuất ra báo cáo per-case và tổng hợp (Fidelity, Block rate, PII leak rate, Abstention rate).

#### Sub-task 1.2: Bổ sung dataset Product-Review [Thứ 2–3] — Priority: Highest
> Blocker cho 1.1 và 1.5. Case PII-in-review (type B) là ca ẩn BTC sẽ đưa vào ngày chấm.
Bổ sung vào `repro/datasets/dataset.jsonl` các ca kiểm thử đặc thù:
- **Multi-turn injection** liên quan đến hội thoại Ask AI về sản phẩm (hỏi reviews $\rightarrow$ trả lời $\rightarrow$ cố tình inject lệnh override). Lưu ý: multi_turn injection đã có sẵn (ids 121–126), chỉ cần kiểm tra harness routing đúng sang `--surface ask-ai`.
- **Review chứa PII (loại B — PII nhúng trong nội dung review):** Tạo thêm ca kiểm thử mà *text của review khách hàng* chứa số điện thoại, email, hoặc CCCD (ví dụ: *"Tôi là Nguyễn Văn A, SĐT 0901xxxxxx, sản phẩm rất tốt"*). Mục tiêu: kiểm tra LLM tóm tắt KHÔNG được lặp lại PII đó ra ngoài. Đây khác với loại injection_query/pii_extraction (ids 75–82) đã có.
  - Thêm field `"type": "pii_in_review"`, `"expected_behavior": "no_pii_leak"` vào JSONL.
  - BTC sẽ đưa loại case này vào bộ ca ẩn ngày chấm.

Thêm field `"surface"` vào mỗi case trong `dataset.jsonl` để harness routing chính xác:
- Cases `type: normal / unanswerable / toxic_review / pii_in_review` $\rightarrow$ `"surface": "summary"`
- Cases `type: injection_query / off_topic` với câu hỏi dạng hội thoại $\rightarrow$ `"surface": "ask-ai"`

Tạo file `repro/datasets/human_labeled_cases.jsonl` (≥10 cases tóm tắt review) và tính toán bảng đối chiếu giữa nhãn người-gán và LLM judge. Bảng phải có cột: `Case_ID | Judge_Verdict | Human_Verdict | Agreement`. Tỷ lệ khớp mục tiêu ≥ 80%.

#### Sub-task 1.3: Đo Abstention & Excessive-agency [Thứ 3] — Priority: High
> Bắt buộc theo yêu cầu Mandate #14. Thiếu chỉ số này ticket không đạt AC.
Tích hợp luật kiểm tra:
- **Abstention:** Câu hỏi Ask AI ngoài phạm vi review của sản phẩm phải được mô hình từ chối bằng từ khóa `NO_INFO` hoặc `OUT_OF_SCOPE`.
- **Excessive-agency:** Chặn các từ khóa giao dịch (checkout, thanh toán) gửi đến API của product-review.

#### Sub-task 1.4: Fix Normal & Toxic Pass Rate [Thứ 3–4] — Priority: High
> Toxic pass rate = 100% là bar cứng của Mandate #14. Normal pass rate ≥ 80% là mục tiêu chất lượng.
- Tăng gRPC timeout lên 90s để loại bỏ hoàn toàn 4 lỗi `DEADLINE_EXCEEDED` của tuần trước.
- Xử lý lỗi judge trả `UNVERIFIED` trên toxic review (nếu context sau lọc quá ngắn, cấu hình để hệ thống trả thẳng `NO_INFO` thay vì crash hoặc bị judge từ chối).

#### Sub-task 1.5: Bổ sung luồng `--surface ask-ai` vào Harness [Thứ 3–4] — Priority: Highest
> Mandate #14 yêu cầu harness chạy được cho cả hai surface. Thiếu surface này ticket bị loại.
Mandate #14 yêu cầu harness chạy được cho **cả tóm tắt lẫn Ask AI**. Bổ sung vào `eval_harness.py`:
- Nhánh `--surface ask-ai`: gọi endpoint hỏi đáp RAG thay vì endpoint tóm tắt tự động.
- Lọc cases từ JSONL theo field `surface` để route đúng endpoint.
- Đo thêm chỉ số: Abstention rate (câu hỏi unanswerable → NO_INFO), Excessive-agency block rate (unauthorized_action → BLOCKED).

#### Sub-task 1.6: Makefile repro [Thứ 4] — Priority: Medium
> Yêu cầu repro một lệnh của Mandate #14, nhưng mentor có thể chạy thủ công nếu thiếu Makefile.
Cấu hình `Makefile` chạy hai lệnh tương ứng hai surface:
```makefile
eval-mandate14:
	python repro/eval_harness.py --case-file repro/datasets/dataset.jsonl --surface summary

eval-mandate14-askai:
	python repro/eval_harness.py --case-file repro/datasets/dataset.jsonl --surface ask-ai
```

#### Sub-task 1.7: Thu thập bằng chứng chạy thật cho Jira (Evidence #3) [Thứ 5 — Thịnh] — Priority: Highest
> Theo AI_MANDATE_EVIDENCE.md: thiếu Evidence #3 (bằng chứng chạy thật) → mentor để ticket mở, chưa tính dù code đã xong.
Chạy toàn bộ harness lần cuối và thu thập:
- Ảnh chụp màn hình output per-case + số tổng từ terminal.
- File `results.json` từ cả hai surface.
- Dán vào comment của ticket `AI MANDATE #14 [TF3]` trên Jira. Thiếu bước này ticket sẽ bị mentor để ngỏ dù code đã xong.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Harness chạy thành công với cả `--surface summary` và `--surface ask-ai`.
- [ ] Dataset có đủ ca multi-turn injection, PII-in-review (type B), unauthorized_action.
- [ ] Field `surface` đã được thêm vào tất cả cases trong `dataset.jsonl`.
- [ ] Đạt tỷ lệ: Normal pass rate ≥ 80%, Toxic pass rate = 100%, runtime errors = 0.
- [ ] Có bảng so sánh đối chiếu judge↔human với Agreement rate ≥ 80%.
- [ ] Chạy thành công bằng lệnh `make eval-mandate14` và `make eval-mandate14-askai`.
- [ ] Ảnh/log bằng chứng chạy thật đã dán vào Jira ticket (Evidence #3).

---

## TICKET 2: Triển khai Caching (ADR 0005) & Đo lường Cost/Latency

* **Người thực hiện (Assignee):** Khoa (Leader)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Tối ưu hóa Hiệu năng AI (Tuần 3)
* **Ưu tiên:** P0

### Mô tả công việc (Description)
Hiện thực hóa thiết kế Caching của ADR 0005 lên dịch vụ `product-reviews` nhằm tối ưu hóa p95 latency và chi phí token, đồng thời thu thập số liệu before/after phục vụ nộp Mandate #14.

### Các tác vụ con (Sub-tasks)

#### Sub-task 2.0: Đo baseline "Before" trước khi tích hợp cache [Thứ 2 sáng — Khoa, TRƯỚC KHI làm 2.1] — Priority: Highest
> Blocker về thứ tự: phải chạy trước 2.1. Nếu bỏ qua, mất toàn bộ số liệu before/after, không có bằng chứng cho Mandate #14.
> Đây là bước BẮT BUỘC phải chạy trước khi bất kỳ thay đổi cache nào được áp dụng, nếu bỏ qua sẽ mất số liệu "Before" và không có bằng chứng so sánh cho Mandate #14.
- Chạy `repro/benchmark.py` (đã có sẵn) trên môi trường hiện tại khi chưa có Redis cache.
- Ghi nhận: p95 latency (ms), average token/request, estimated cost/10k requests.
- Lưu vào `repro/artifacts/cost_latency_BEFORE_cache.json`.

#### Sub-task 2.1: PostgreSQL Migration cột `is_safe` [Thứ 2 sáng] — Priority: Medium
> Cải thiện chất lượng dữ liệu đầu vào cho LLM. Quan trọng nhưng hệ thống vẫn chạy được nếu chưa có cột này.
- Tạo migration script thêm cột `is_safe` (mặc định `TRUE`) vào bảng `reviews.productreviews`.
- Viết script background worker để quét các review cũ, lọc regex guardrail và cập nhật cột `is_safe`.
- Sửa SQL query trong `database.py` để chỉ lấy reviews có `is_safe = TRUE`.

#### Sub-task 2.2: Thiết lập Redis & Caching logic [Thứ 2 chiều - Thứ 3] — Priority: Highest
> Blocker cho 2.3, 2.4 và toàn bộ Ticket 3 (Redis key fallback_override). Hai ticket phụ thuộc vào hạ tầng này.
- Thêm `redis` vào `requirements.txt` và thêm service Redis vào local dev docker-compose.
- Viết file `cache.py` sử dụng Redis Key-Value để lưu LLM response. Cache Key sử dụng hàm băm động `SHA256(product_id + review_version + model_id + question)`.
- Áp dụng cơ chế **Fail-Open**: Nếu Redis sập, luồng RAG vẫn tiếp tục gọi LLM bình thường mà không gây lỗi hệ thống.
- **Phối hợp với Kiên (Ticket 3):** Định nghĩa và dành riêng Redis key `product_reviews:fallback_override` (kiểu String, TTL 5 phút) cho cơ chế Closed-Loop của Ticket 3. Key này KHÔNG dùng làm cache LLM. Khi key = `"true"`, `product_reviews_server.py` bỏ qua Bedrock và đọc thẳng từ PostgreSQL cache.

#### Sub-task 2.3: Tích hợp Cache vào product_reviews_server.py [Thứ 3] — Priority: High
> Bắt buộc để có số liệu After và để Ticket 3 hoạt động. Thiếu thì Mandate #14 không có minh chứng latency improvement.
- Kiểm tra cache ở đầu hàm `AskProductAIAssistant` (Cache Hit $\rightarrow$ trả kết quả ngay < 10ms).
- Lưu cache ở cuối hàm sau khi Fidelity Judge duyệt thành công (`approved == True`).

#### Sub-task 2.4: Đo đạc Cost/Latency After & So sánh Before/After [Thứ 4] — Priority: High
> Mandate #14 yêu cầu bắt buộc có số liệu cost/latency before/after. Thiếu bảng so sánh → ticket không đạt AC.
- Chạy benchmark đo latency p95 trước và sau khi có cache.
- Ghi nhận lượng token tiêu thụ và tính toán chi phí (cost) trung bình trên mỗi request.
- Lưu trữ kết quả vào tệp tin `repro/artifacts/cost_latency_baseline.json`.

#### Sub-task 2.5: Đóng gói, Viết ADR 0006 và Tạo Jira Ticket `AI MANDATE #14 [TF3]` [Thứ 5] — Priority: Highest
> Là bước nộp bài cuối cùng. Thiếu ticket trên Jira = Mandate coi như chưa làm dù code hoàn chỉnh.
- Viết ADR 0006 theo đúng format của các ADR 0001–0005 đã có trong `docs/adr/` (gồm: Context, Decision, Consequences, Metrics). Nội dung: phương pháp đo Cost/Latency, lý do chọn Redis, kết quả before/after thực tế.
- Tạo ticket Jira `AI MANDATE #14 [TF3]` với đủ 4 evidence theo format trong `AI_MANDATE_EVIDENCE.md`:
  1. Link PR/commit
  2. Lệnh repro: `make eval-mandate14`
  3. Bằng chứng chạy thật: ảnh/log từ Sub-task 1.7 (do Thịnh cung cấp) + file `cost_latency_BEFORE_cache.json` vs After
  4. Link ADR 0006 ký tên

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Số liệu baseline "Before" đã được đo và lưu vào `cost_latency_BEFORE_cache.json` trước khi tích hợp cache.
- [ ] Cột `is_safe` hoạt động và query DB chỉ lấy review sạch.
- [ ] Redis cache hoạt động ổn định, cache hit phản hồi dưới 10ms.
- [ ] Redis key `product_reviews:fallback_override` đã được định nghĩa và Kiên đã xác nhận tương thích.
- [ ] Tích hợp Fail-Open cho Redis thành công.
- [ ] Tệp `repro/artifacts/cost_latency_BEFORE_cache.json` và `cost_latency_AFTER_cache.json` ghi nhận đầy đủ số liệu so sánh.
- [ ] ADR 0006 commit đúng format, có ký tên.
- [ ] Jira ticket `AI MANDATE #14 [TF3]` được tạo với đủ 4 evidence yêu cầu.

---

## TICKET 3: Thiết lập Closed-Loop Auto-Mitigation (MANDATE #22) cho Product-Review Service

* **Người thực hiện (Assignee):** Kiên
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #22 Closed-Loop Mitigation (Tuần 3)
* **Ưu tiên:** P0 — Deadline 25/07
* **Label Jira:** `ai-mandate`, `m22`

### Mô tả công việc (Description)
Triển khai hệ thống tự dập sự cố end-to-end cho dịch vụ `product-reviews` dựa trên metrics lỗi. Khi phát hiện Bedrock gặp lỗi hoặc quá tải (429), hệ thống tự kích hoạt cấu hình chuyển hướng dùng cache/static summaries, verify trạng thái và tự rollback khi lỗi chấm dứt.

### Các tác vụ con (Sub-tasks)

#### Sub-task 3.1: Viết tài liệu ADR 0007 & Phối hợp interface với Khoa [Thứ 2] — Priority: Highest
> Blocker cho 3.2, 3.3: thiếu thiết kế và thống nhất Redis key schema thì Kiên và Khoa code song song sẽ conflict.
- Thiết kế luồng xử lý: Detector $\rightarrow$ Safety Check $\rightarrow$ Action $\rightarrow$ Verify $\rightarrow$ Rollback.
- Định nghĩa sự cố: Bedrock rate limit 429 (theo dõi metric `app_ai_fallback_total{source="rate_limit"}`).
- **Phối hợp với Khoa (Ticket 2):** Xác nhận cơ chế truyền tín hiệu mitigator vào `product_reviews_server.py` sử dụng Redis key `product_reviews:fallback_override`. Khi Detector kích hoạt mitigator, mitigator SET key này = `"true"` với TTL 5 phút. Khi rollback, mitigator DELETE key. Server.py kiểm tra key này ở đầu mỗi request — phải thống nhất trước khi bắt đầu code tránh conflict.
- Hành động: Ghi Redis key override thay vì ghi file cấu hình local (để tránh lỗi read-only filesystem trong K8s pod).
- Viết ADR 0007 theo đúng format của các ADR 0001–0005 đã có trong `docs/adr/`.

#### Sub-task 3.2: Phát triển Detector & Safety Check [Thứ 3] — Priority: Highest
> Blocker cho 3.3. Không có Detector thì không có Mitigator, toàn bộ vòng lặp closed-loop không hoạt động.
- Viết `aiops/detector.py` định kỳ quét Prometheus metric lỗi 429.
- Viết `aiops/safety_check.py` thực hiện: dry-run, kiểm tra phạm vi ảnh hưởng (blast-radius) và cooldown (không chạy liên tục 2 lần trong 5 phút).

#### Sub-task 3.3: Implement Mitigator, Verifier & Rollback [Thứ 3–4] — Priority: Highest
> Là trái tim của Mandate #22. Thiếu Mitigator hoặc Rollback → hệ thống không đủ điều kiện closed-loop.
- Viết logic ghi cấu hình override khi kích hoạt dập sự cố.
- Viết `aiops/verifier.py` kiểm tra telemetry sau 30 giây: Lỗi 429 đã về 0 chưa? Storefront có phản hồi 200 OK không?
- Nếu verify thất bại, tự động gọi hàm `rollback()` để khôi phục cấu hình cũ.

#### Sub-task 3.4: Xây dựng Audit Log & Replay script [Thứ 4] — Priority: High
> Audit log JSON 5 tầng là bằng chứng chạy thật (Evidence #3) cho Jira. Replay script giúp demo được kịch bản lỗi mà không cần inject lỗi thật.
- Cấu hình ghi audit log dưới dạng JSON chứa đủ thông tin trigger, check, action, verify và rollback.
- Viết script `aiops/replay.py` chạy thử nghiệm kịch bản lỗi giả lập.

#### Sub-task 3.5: Sanity test, Thu thập bằng chứng & Tạo Jira Ticket [Thứ 5 — Kiên] — Priority: Highest
> Là bước nộp bài cuối cùng của Mandate #22. Thiếu Evidence #3 (ảnh/log thật) → mentor để ticket mở.
> Chạy thử nghiệm toàn trình bằng `aiops/replay.py` (giả lập lỗi 429), ghi nhận kết quả và thu thập bằng chứng chạy thật:
- Chụp màn hình/log terminal hiển thị chuỗi: Trigger $\rightarrow$ Safety Check pass $\rightarrow$ Mitigation kích hoạt $\rightarrow$ Verify thành công $\rightarrow$ Rollback.
- Xuất file `audit_log.json` từ một lần chạy đầy đủ.
- Tạo ticket `AI MANDATE #22 [TF3]` với đủ 4 evidence theo format `AI_MANDATE_EVIDENCE.md`:
  1. Link PR/commit
  2. Lệnh repro: `python aiops/replay.py --scenario bedrock-429`
  3. Bằng chứng chạy thật: ảnh/log chuỗi closed-loop + file `audit_log.json`
  4. Link ADR 0007 ký tên

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Redis key `product_reviews:fallback_override` đã được xác nhận tương thích với Khoa.
- [ ] Detector bắt được lỗi và Safety Check phê duyệt hành động chính xác.
- [ ] Mitigator ghi Redis key thành công, server.py chuyển sang nhánh fallback ngay lập tức.
- [ ] Hệ thống tự dập lỗi và tự rollback thành công khi ép kịch bản sai.
- [ ] Ghi nhận audit log đầy đủ cấu trúc JSON 5 tầng: trigger, check, action, verify, rollback.
- [ ] ADR 0007 được commit đúng format và ký tên.
- [ ] Ảnh/log bằng chứng chạy thật (Evidence #3) đã dán vào Jira ticket.
- [ ] Jira ticket `AI MANDATE #22 [TF3]` được tạo với đủ 4 evidence.

---

## TICKET 4: Nghiên cứu tài liệu LLM-as-a-Judge & Thống nhất bộ rubric đánh giá

* **Người thực hiện (Assignee):** Cả nhóm (Thịnh, Khoa, Kiên)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Mandate #14 AI Eval Standard (Tuần 3)
* **Ưu tiên:** High
* **Label Jira:** `ai-mandate`, `m14`, `research`

### Mô tả công việc (Description)
Cả nhóm nghiên cứu tài liệu `D:\AI\Book\LLM-as-a-Judge.pdf` để thống nhất phương pháp thiết kế prompt cho LLM Judge, rubric chấm điểm và cơ chế gán nhãn của con người (human labels) để kiểm chứng độ chính xác của judge (Agreement Rate).

### Các tác vụ con (Sub-tasks)

#### Sub-task 4.1: Đọc và ghi chép tài liệu LLM-as-a-Judge [Thứ 2 sáng — Thịnh, Khoa, Kiên] — Priority: High
- Đọc tài liệu tại `D:\AI\Book\LLM-as-a-Judge.pdf`.
- Tìm hiểu cách thiết kế rubrics chấm điểm tự động.
- Nắm rõ cách xử lý các bias của LLM Judge (verbosity bias, position bias, self-enhancement bias).

#### Sub-task 4.2: Họp sync thống nhất Rubrics & chọn 10 cases gán nhãn thủ công [Thứ 2 chiều — Cả nhóm] — Priority: High
- Tổ chức buổi sync ngắn thống nhất bộ tiêu chí (rubric) chấm Fidelity (faithfulness, grounding) và Guardrails.
- Chọn ra ít nhất 10 cases thực tế từ reviews để cả nhóm cùng đánh giá bằng tay (human grading) và lưu vào `repro/datasets/human_labeled_cases.jsonl` làm tập đối so.

### Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Cả 3 thành viên đã đọc tài liệu.
- [ ] Bộ rubrics đánh giá được thống nhất và ghi nhận trong ADR 0006.
- [ ] Tệp `repro/datasets/human_labeled_cases.jsonl` được tạo với tối thiểu 10 cases được cả nhóm thống nhất nhãn.

---

---

## 📅 LỊCH SPRINT CHI TIẾT THEO NGÀY (Tuần 3)

> **Ghi chú phối hợp:** Khoa và Kiên cần đồng thuận về Redis key schema (`product_reviews:fallback_override`) trước cuối ngày T2. Thịnh cần gửi `results.json` và ảnh chụp harness cho Khoa trước Thứ 5 chiều để đính kèm vào ticket #14.

| Ngày | Khoa | Thịnh | Kiên |
|------|------|-------|------|
| **T2 21/07** | **Đo baseline Before** (Sub-task 2.0) + Migration DB `is_safe` + Xác nhận Redis key schema + **Đọc tài liệu LLM Judge (4.1) & Họp sync rubrics (4.2)** | Viết `eval_harness.py` skeleton + CLI args + thêm field `surface` vào dataset + **Đọc tài liệu LLM Judge (4.1) & Họp sync rubrics (4.2)** | Viết ADR 0007 + Xác nhận Redis key schema + **Đọc tài liệu LLM Judge (4.1) & Họp sync rubrics (4.2)** |
| **T3 22/07** | Viết `cache.py` (bao gồm key `fallback_override`) + Tích hợp cache vào server.py | Thêm PII-in-review cases (type B) + multi-turn cases + human labels | Viết `detector.py` + `safety_check.py` |
| **T4 23/07** | Đo After + So sánh before/after + Viết ADR 0006 | Bổ sung luồng `--surface ask-ai` + Fix timeout/UNVERIFIED + Viết Makefile | Viết `mitigator.py` + `verifier.py` + `replay.py` |
| **T5 24/07** | Tạo ticket #14 với đủ 4 evidence (nhận ảnh/log từ Thịnh) | Chạy e2e harness (cả 2 surface) + Chụp ảnh/log → gửi Khoa (Evidence #3) | Chạy closed-loop e2e + Chụp ảnh/log + Tạo ticket #22 với đủ 4 evidence |
| **T6 25/07** | Kiểm tra chéo 2 ticket + Đóng ticket trước hạn | Hỗ trợ review | Hỗ trợ review |
