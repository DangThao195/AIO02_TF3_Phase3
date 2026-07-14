# Backlog Kế hoạch Công việc - TF3 AIOps Engine

Tài liệu này theo dõi các hạng mục công việc đã hoàn thành và danh sách các tính năng/nhiệm vụ cần thực hiện trong các giai đoạn tiếp theo (Sprints) của hệ thống TF3 AIOps.

## Sprint Hiện tại (Đã hoàn thành)
- [x] **Điều tra và Báo cáo Sự cố (Incident Analysis):** Đã phân tích thành công mã lỗi `INCIDENT-2026-004` (Cạn kiệt Connection Pool do đợt quét tấn công mạng / "đạo chích"). Đã lập file báo cáo RCA chi tiết.
- [x] **Tích hợp Cảnh báo Tương tác Slack (Interactive Slack Alerts):** Đã triển khai script Python sử dụng Slack Block Kit để gửi cảnh báo lỗi kèm nút "Approve Auto-scaling".
- [x] **Cấu hình Quyền chia sẻ Docker Image (ECR Access Policy):** Đã cập nhật `ecr-policy.json` để cấp quyền cho tài khoản của đội CDO pull image `tf-2-ai-engine:latest` từ AWS ECR.
- [x] **Hoàn thiện Hệ thống Tài liệu (Documentation):** Đã hoàn tất và dịch sang tiếng Việt chi tiết các tài liệu cốt lõi: SPEC, BACKLOG, CONTRACTS, POC, và RUN_GUIDE.

## Sprint Tiếp theo (To-Do)

### 1. Tự động hóa khắc phục sự cố (Automated Remediation Execution)
- [ ] **Mục tiêu:** Biến nút "Approve Auto-scaling" trên Slack thành một hành động thực tế.
- [ ] **Chi tiết:** Xây dựng một API Webhook Server nhỏ nhận tín hiệu từ Slack. Khi user click "Approve", API này sẽ dùng lệnh `kubectl scale deployment/payment-service --replicas=5` để tự động mở rộng hệ thống, thay vì phải chạy thủ công.

### 2. Dự báo sự cố (Incident Prediction System)
- [ ] **Mục tiêu:** Chuyển từ "Phản ứng (Reactive)" sang "Chủ động phòng ngừa (Proactive)".
- [ ] **Chi tiết:** Tích hợp mô hình Machine Learning (ví dụ: Time-series forecasting) vào `aiops-engine` để phân tích dữ liệu lịch sử. Engine phải có khả năng dự đoán trước 15-30 phút khi nào Connection Pool có nguy cơ bị cạn kiệt và cảnh báo trước.

### 3. Dashboard Dành cho đội CDO (CDO Metrics Dashboard)
- [ ] **Mục tiêu:** Cung cấp góc nhìn tổng quan (Visibility) cho đội Chief Data Officer.
- [ ] **Chi tiết:** Triển khai Grafana và kết nối với Prometheus trong cluster `techx-tf3`. Xây dựng các biểu đồ hiển thị thời gian thực các thông số: Transaction Volume, Error Rate (HTTP 5xx), Connection Pool Usage, và tần suất các cảnh báo AIOps tại region `us-east-1`.

### 4. Mở rộng kịch bản Chaos Engineering (Advanced Chaos Scenarios)
- [ ] **Mục tiêu:** Kiểm thử độ bền bỉ (Resilience) của AIOps Engine bằng các tình huống phức tạp hơn.
- [ ] **Chi tiết:** Cập nhật `flagd-config` để bổ sung các cấu hình: 
  - `latencyInjection`: Tạo độ trễ ngẫu nhiên từ 500ms - 5000ms cho các request thanh toán.
  - `databaseDisconnect`: Giả lập đứt kết nối ngắt quãng với cơ sở dữ liệu.
  - `randomPodTermination`: Tắt đột ngột một vài Pods để xem hệ thống tự phục hồi như thế nào.

### 5. Mã hóa Kịch bản Xử lý (Runbooks as Code)
- [ ] **Mục tiêu:** Số hóa và tự động hóa toàn bộ tài liệu hướng dẫn xử lý lỗi.
- [ ] **Chi tiết:** Chuyển đổi các file Markdown hướng dẫn (Runbook) còn lại thành các script Python tự động hoàn toàn. Khi sự cố X xảy ra, hệ thống tự động chạy Script X tương ứng.
