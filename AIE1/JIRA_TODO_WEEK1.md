# Kế hoạch Phân chia Công việc Tuần 1 - Nhóm AIE1 (JIRA TODO)

Tài liệu này chứa nội dung chi tiết các công việc tuần 1 được thiết kế dưới dạng các ticket **JIRA TODO** cho 3 thành viên: **Khoa** (Leader), **Thịnh**, và **Kiên**.

---

## TICKET 1: Cấu hình Tích hợp LLM Thật (gpt-4o-mini) & Giám sát Telemetry
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Tối ưu & Vận hành Tầng AI (Tuần 1)
* **Ưu tiên:** High (P0)

### Mô tả công việc (Description)
Triển khai cắm model LLM thực tế (`gpt-4o-mini` - lựa chọn tối ưu chi phí để dễ dàng trình CFO duyệt) thay thế cho Mock server hiện tại. Thực hiện deploy lên Kubernetes cluster của Task Force và sử dụng Jaeger/Prometheus để theo dõi traces/metrics của các cuộc gọi AI nhằm thu thập số liệu latency baseline.

### Các tác vụ con cần thực hiện (Sub-tasks)
1. **Tạo Kubernetes Secret:** Tạo secret chứa API key thật trong namespace của TF:
   ```bash
   kubectl -n <namespace_cua_TF> create secret generic llm-api-key --from-literal=key=<REAL_KEY>
   ```
2. **Cấu hình file Helm values:** Chỉnh sửa file `deploy/values-aio-llm.yaml` để:
   * Trỏ `LLM_BASE_URL` về `https://api.openai.com/v1` (hoặc Gateway tương thích).
   * Cấu hình `LLM_MODEL` thành `gpt-4o-mini`.
   * Liên kết biến `OPENAI_API_KEY` lấy giá trị từ secret `llm-api-key`.
3. **Deploy upgrade hệ thống:** Chạy Helm upgrade có đính kèm file cấu hình LLM và đồng bộ flagd:
   ```bash
   helm upgrade --install techx-corp ./techx-corp-chart -n <namespace_cua_TF> \
     -f deploy/values-observability.yaml \
     -f deploy/values-flagd-sync.yaml \
     -f deploy/values-aio-llm.yaml
   ```
4. **Theo dõi traces trên Jaeger:** Port-forward proxy để truy cập Jaeger UI. Theo dõi các traces của lời gọi từ service `product-reviews` sang `llm` để xác nhận cuộc gọi thành công và không phát sinh lỗi.
5. **Thu thập số liệu Latency & Cost:** Đo đạc thời gian phản hồi thực tế (Latency p95, p99) và ước tính chi phí dựa trên số lượng token tiêu thụ thực tế để ghi nhận vào tài liệu baseline.

### Tiêu chí nghiệm thu (Acceptance Criteria)
* [x] Tính năng tóm tắt review trên storefront chạy bằng model thật `nova-lite` (không bị mock).
* [x] File `deploy/values-aio-llm.yaml` được cập nhật chính xác và commit lên repo.
* [x] Traces trên Jaeger ghi nhận đầy đủ luồng đi và thời gian xử lý của API LLM thật.
* [x] Bảng số liệu Latency & Cost được điền đầy đủ vào Mục 1 trong file `AI_BASELINE_EVAL.md`.

---

## TICKET 2: Xây dựng Bộ Đánh giá Độ trung thực (Fidelity Evaluation Framework) cho văn bản tóm tắt
* **Người thực hiện (Assignee):** Thịnh
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Tối ưu & Vận hành Tầng AI (Tuần 1)
* **Ưu tiên:** High (P1)

### Mô tả công việc (Description)
Xây dựng bộ eval (viết mã nguồn/script tự động hoặc bán tự động) để đánh giá độ trung thực (**Fidelity**) của các văn bản tóm tắt do AI tạo ra so với tập dữ liệu review gốc được lưu trong cơ sở dữ liệu Postgres (`reviews.productreviews`). Đảm bảo hệ thống phát hiện được khi LLM bịa đặt thông tin (hallucination) hoặc tóm tắt sai lệch.

### Các tác vụ con cần thực hiện (Sub-tasks)
1. **Viết script truy vấn dữ liệu:** Viết mã nguồn Python kết nối Postgres để lấy dữ liệu review gốc tương ứng với một `product_id`.
2. **Tích hợp API LLM Eval:** Viết script gọi API tóm tắt từ `AskProductAIAssistant` hoặc tự động hóa việc so khớp ngữ nghĩa (Semantic Alignment) / Sentiment phân tích chéo để chấm điểm Fidelity.
3. **Mô phỏng kịch bản lỗi:** Sử dụng feature flag `llmInaccurateResponse` trên product ID `L9ECAV7KIM` (giả lập trả về tóm tắt sai sự thật từ file `inaccurate-product-review-summaries.json`) để chạy thử nghiệm.
4. **Kiểm chứng bộ Eval:** Chứng minh script đánh giá có khả năng phát hiện ra tóm tắt sai lệch của sản phẩm `L9ECAV7KIM` và gán điểm Fidelity thấp (vd: 1/5).
5. **Tài liệu hóa kịch bản:** Viết mẫu các kịch bản test độ trung thực vào Mục 2 của file `AI_BASELINE_EVAL.md`.

### Tiêu chí nghiệm thu (Acceptance Criteria)
* [x] Mã nguồn script/code eval được commit vào thư mục dự án (vd: `repro/` hoặc `scripts/`).
* [ ] Bộ eval chạy thành công và xuất ra điểm số Fidelity rõ ràng cho từng test case.
* [ ] Test case mô phỏng lỗi `L9ECAV7KIM` được bộ eval phát hiện chính xác là "Sai lệch dữ liệu".
* [ ] Đã cập nhật đầy đủ thông tin kịch bản test vào file `AI_BASELINE_EVAL.md`.

---

## TICKET 3: Thiết kế AI Guardrails, Cơ chế Fallback và Đóng góp Backlog AI
* **Người thực hiện (Assignee):** Kiên
* **Loại công việc:** Task / Story
* **Epic:** AIE1 - Tối ưu & Vận hành Tầng AI (Tuần 1)
* **Ưu tiên:** High (P1)

### Mô tả công việc (Description)
Nghiên cứu các giải pháp bảo mật cho tầng AI (chống Prompt Injection nhét trong nội dung review mẫu, chống rò rỉ system prompt của Chat Assistant), lọc thông tin cá nhân nhạy cảm (PII). Thiết kế cơ chế xử lý dự phòng (Fallback/Circuit Breaker) để storefront hoạt động bình thường khi LLM gặp sự cố (Timeout/429/500). Đồng thời, tổng hợp và đề xuất các đầu việc cải tiến AI vào backlog chung kèm điểm đánh giá rủi ro & tác động business.

### Các tác vụ con cần thực hiện (Sub-tasks)
1. **Tìm kiếm & Thử nghiệm lỗ hổng:** Thiết lập các payload Prompt Injection mẫu nhét vào nội dung review và kiểm tra khả năng LLM bị thao túng hoặc làm rò rỉ System Prompt.
2. **Tài liệu hóa lỗ hổng bảo mật:** Liệt kê chi tiết các lỗ hổng phát hiện được vào Mục 3 của file `AI_BASELINE_EVAL.md`.
3. **Thiết kế Guardrail & PII Filter:** Đưa ra giải pháp/kiến trúc lọc PII (Email, số điện thoại) trước khi gửi payload lên LLM API và chặn các từ khóa injection độc hại.
4. **Thiết kế Logic Fallback:** Xây dựng giải pháp dự phòng (ví dụ: khi kích hoạt flag `llmRateLimitError` làm giả lập lỗi 429, hệ thống phải tự động trả về tóm tắt tĩnh/cache hoặc thông báo thân thiện thay vì làm treo storefront).
5. **Xây dựng Backlog cải tiến:** Đề xuất ít nhất 3-4 đầu việc cải tiến kỹ thuật cho tầng AI (ví dụ: cài đặt cache giảm 30% chi phí token, middleware chặn PII, timeout/retry logic) kèm điểm rủi ro (Risk Score: 1-5) và tác động business (Business Impact: High/Medium/Low), ghi nhận vào Mục 4 của file `AI_BASELINE_EVAL.md`.

### Tiêu chí nghiệm thu (Acceptance Criteria)
* [ ] Danh sách lỗ hổng bảo mật kèm payload mẫu được ghi nhận đầy đủ trong tài liệu eval.
* [ ] Bản thiết kế kỹ thuật (luồng xử lý/code mẫu) cho cơ chế Fallback và lọc PII được hoàn thành.
* [ ] Danh sách các công việc cải tiến tầng AI có điểm rủi ro và tác động business được cập nhật đầy đủ vào phần Backlog trong file `AI_BASELINE_EVAL.md`.
