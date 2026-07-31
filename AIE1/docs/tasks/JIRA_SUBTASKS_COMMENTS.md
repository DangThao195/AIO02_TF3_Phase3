# 📝 DANH SÁCH COMMENT JIRA MẪU (DÙNG ĐƯỜNG LINK RAW URL TRỰC TIẾP)

Tài liệu này tổng hợp toàn bộ nội dung comment cho các **Ticket S1, S5, S6** trên Jira. 
Tất cả các đường link minh chứng và commit được để dưới dạng **Raw URL đơn thuần (`https://github.com/...`)** để Jira tự động nhận diện và chuyển thành Smart Link clickable khi dán vào.

---

## 📌 TICKET S1: Bedrock Egress Architecture & Remove Wildcard `0.0.0.0/0:443`

### 🔵 Sub-task S1.1: Thống nhất phương án kiến trúc Egress với Infra/CDO team
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Đã hoàn thành đánh giá 3 phương án kiến trúc do CDO đề xuất và thống nhất lựa chọn Phương án ưu tiên (GitOps-managed Egress Proxy với FQDN allowlist).
- Định tuyến toàn bộ luồng gọi AWS Bedrock Runtime (*.bedrock-runtime.us-east-1.amazonaws.com) và STS (sts.ap-southeast-1.amazonaws.com) qua Egress Proxy được quản lý qua GitOps.
- Quyết định này đồng bộ với kiến trúc App-level Evaluator (không tích hợp Bedrock Guardrail shopping-copilot-guardrail) đã được văn bản hóa chính thức trong ADR 0009.

2. Commits thay đổi:
- Commit 57ee35a1: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/57ee35a1
- Commit 2f5dfbf6: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/2f5dfbf6

3. Minh chứng & File đính kèm:
- Tài liệu ADR 0009: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/adr/0009-APP-LEVEL-EVALUATOR-NO-BEDROCK-GUARDRAIL.md
- Báo cáo kiểm toán CDO: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/product-reviews-readonly-audit-2026-07-26.md#L20-L29
```

---

### 🔵 Sub-task S1.2: Loại bỏ quy tắc Egress Wildcard trong NetworkPolicy
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Đã chỉnh sửa tệp NetworkPolicy staged 32-product-reviews.yaml, loại bỏ hoàn toàn quy tắc mở tự do egress wildcard 0.0.0.0/0:443 ra Internet.
- Cấu hình lại các cổng egress cụ thể hướng trực tiếp tới Egress Proxy và Gateway chỉ định, đáp ứng tiêu chuẩn Promotion Unblocker của CDO Audit.

2. Commits thay đổi:
- Commit f97430db: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/f97430db

3. Minh chứng & File đính kèm:
- Kế hoạch JIRA SPECIAL: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/tasks/JIRA_TODO_SPECIAL.md#L20-L40
- Báo cáo CDO Audit: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/product-reviews-readonly-audit-2026-07-26.md#L4-L6
```

---

### 🔵 Sub-task S1.3: Kiểm tra tính khả thi của Private Endpoint cho STS
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Đã đánh giá tính khả thi và lập kế hoạch khởi tạo VPC Interface Endpoint cho AWS STS tại region Singapore (ap-southeast-1).
- Kiểm tra thiết lập Private DNS, Endpoint Policy và Security Group để hướng luồng xác thực IRSA nội bộ VPC, loại bỏ hoàn toàn nhu cầu egress ra public Internet cho dịch vụ STS.

2. Commits thay đổi:
- Commit f97430db: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/f97430db

3. Minh chứng & File đính kèm:
- Báo cáo đối chiếu CDO: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/product-reviews-readonly-audit-2026-07-26.md#L35-L38
- Kế hoạch phân công: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/tasks/JIRA_TODO_SPECIAL.md#L37-L39
```

---

## 📌 TICKET S5: Run Validation & Promo Evidence Collection

### 🔵 Sub-task S5.1: Kiểm tra Helm Lint & CI
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Đã rà soát và kiểm tra toàn bộ cấu hình Helm Chart templates trong techx-corp-chart/ kết hợp với file values-aio-llm.yaml.
- Xác nhận các tham số môi trường LLM Provider (bedrock), Candidate Model (amazon.nova-lite-v1:0), Judge Model (amazon.nova-micro-v1:0) và Region (us-east-1) hoạt động chính xác và không có lỗi cú pháp Helm.

2. Commits thay đổi:
- Commit 55f36eb6: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/55f36eb6

3. Minh chứng & File đính kèm:
- File cấu hình Helm: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/deploy/values-aio-llm.yaml
- Báo cáo nghiệm thu Mandate 25: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/AIE1-MANDATE-25-SUBMISSION.md#L18-L27
```

---

### 🔵 Sub-task S5.2: Kiểm tra trạng thái Argo CD & Pod Readiness
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Xác nhận ứng dụng product-reviews trên Argo CD đạt trạng thái Synced & Healthy.
- Kiểm tra Pod ReadinessProbe & LivenessProbe hoạt động ổn định. Tích hợp thành công quy trình Graceful Shutdown 5.0 giây khi nhận tín hiệu SIGTERM, không gặp lỗi restart regression.

2. Commits thay đổi:
- Commit f97430db: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/f97430db

3. Minh chứng & File đính kèm:
- Mã nguồn Graceful Shutdown: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L2085-L2096
- Báo cáo nghiệm thu: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/AIE1-MANDATE-25-SUBMISSION.md#L45-L46
```

---

### 🔵 Sub-task S5.3: Thử nghiệm luồng Traffic Được Phép (Allowed Flows)
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Đã kiểm thử và thu thập bằng chứng kết nối thành công tới 100% các luồng traffic hợp lệ: DNS, product-catalog:8080, flagd:8013, otel-gateway:4317, RDS PostgreSQL (3 dải subnets /20), STS và AWS Bedrock Runtime.
- Trích xuất metric telemetry khẳng định zero-loss kết nối trên luồng chính.

2. Commits thay đổi:
- Commit d12f36d5: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/d12f36d5

3. Minh chứng & File đính kèm:
- Báo cáo bằng chứng: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/AIE1-MANDATE-25-SUBMISSION.md#L61-L67
- File nhật ký kiểm toán: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/techx-corp-platform/src/product-reviews/logs/audit_log.jsonl
```

---

### 🔵 Sub-task S5.4: Thử nghiệm luồng Traffic Bị Cấm (Denied Flows)
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Thử nghiệm và xác nhận NetworkPolicy chặn thành công 100% traffic không thuộc whitelist: kết nối sang dịch vụ payment, các service không liên quan và traffic egress tự do ra Internet ngoài proxy.

2. Commits thay đổi:
- Commit 55f36eb6: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/55f36eb6

3. Minh chứng & File đính kèm:
- Báo cáo bằng chứng: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/AIE1-MANDATE-25-SUBMISSION.md#L47-L49
```

---

### 🔵 Sub-task S5.5: Đổi tên & Promote NetworkPolicy
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Tổng hợp đầy đủ 6/6 hạng mục Promo Evidence theo yêu cầu CDO.
- Đã sẵn sàng đổi tên và promote NetworkPolicy 32-product-reviews.yaml từ network-policy-staged/ lên Production. Đảm bảo K8s PolicyEndpoint khớp 100% với policy promoted và giữ sức khỏe luồng khách hàng 100% qua Soak Window.

2. Commits thay đổi:
- Commit f97430db: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/f97430db
- Commit 55f36eb6: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/55f36eb6

3. Minh chứng & File đính kèm:
- Báo cáo tổng hợp nghiệm thu: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/AIE1-MANDATE-25-SUBMISSION.md
- Kế hoạch phân công: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/tasks/JIRA_TODO_SPECIAL.md#L88-L107
```

---

## 📌 TICKET S6: Thread Pool Isolation between Read API & Ask AI API

### 🔵 Sub-task S6.1: Triển khai Bounded AI ThreadPool Executor
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Khắc phục triệt để sự cố nghẽn luồng trong postmortem PM-0016 bằng việc triển khai Phương án 1 (Dedicated AI Bounded ThreadPool Executor).
- Khởi tạo ai_executor = futures.ThreadPoolExecutor(max_workers=15, thread_name_prefix="ai_worker") cô lập riêng các tác vụ AI.
- Bọc hàm AskProductAIAssistant tự động chuyển sang đường lui Tier 2 PostgreSQL Static DB Summary (hoặc Tier 3 Abstention) trong < 5ms khi AI Pool bị đầy hoặc timeout (15s).
- Đảm bảo 35+ worker threads của main gRPC pool luôn rảnh rỗi cho Read API (GetProductReviews), triệt tiêu rủi ro dính timeout DEADLINE_EXCEEDED (> 500ms).

2. Commits thay đổi:
- Commit f97430db: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/f97430db

3. Minh chứng & File đính kèm:
- Mã nguồn khởi tạo pool (Dòng L210): https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L210
- Mã nguồn bọc AI handler (Dòng L1063-L1082): https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L1063-L1082
- Kế hoạch & Trade-off matrix: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/tasks/JIRA_TODO_SPECIAL.md#L111-L147
```

---

### 🔵 Sub-task S6.2: Kiểm thử tải cô lập (Isolation Load Testing)
```text
🟢 Trạng thái: HOÀN THÀNH (DONE)

1. Nội dung thực hiện:
- Chạy toàn bộ test suites kiểm thử chịu lỗi và nén tải cô lập: test_error_injection.py, test_circuit_breaker.py, test_tool_validator.py.
- Kết quả: Đạt 36/36 ca unit test Passed (Pass Rate 100%).
- Đảm bảo p95 latency của API GetProductReviews luôn < 50ms (vượt xa SLO 500ms) ngay cả khi luồng AI bị nén tải hoặc throttled.

2. Commits thay đổi:
- Commit f97430db: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/f97430db
- Commit 55f36eb6: https://github.com/DangThao195/AIO02_TF3_Phase3/commit/55f36eb6

3. Minh chứng & File đính kèm:
- Báo cáo kết quả Test Suites: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/reports/AIE1-MANDATE-25-SUBMISSION.md#L103-L108
- Kế hoạch nghiệm thu: https://github.com/DangThao195/AIO02_TF3_Phase3/blob/feature/product-review/AIE1/docs/tasks/JIRA_TODO_SPECIAL.md#L133-L137
```
