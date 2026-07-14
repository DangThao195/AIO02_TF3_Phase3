# TF3 AIOps Engine - Priority Backlog

Tài liệu quản lý tiến độ và xếp hạng ưu tiên các hạng mục công việc của mảng **TF3 AIOps Engine**.

Các hạng mục được xếp hạng ưu tiên nghiêm ngặt theo công thức chuẩn:
$$\text{Priority Score} = \text{Risk (Probability} \times \text{Severity)} \times \text{Business Impact}$$

Trong đó, mỗi tiêu chí được đánh giá theo thang điểm từ 1 đến 5:
- **Probability (Khả năng xảy ra)**: Xác suất sự cố xảy ra hoặc nhu cầu sử dụng (1 = Rất thấp, 5 = Rất cao).
- **Severity (Mức nghiêm trọng)**: Mức độ nguy hại đối với hạ tầng nếu không thực hiện (1 = Rất thấp, 5 = Cực kỳ nghiêm trọng).
- **Business Impact (Tác động Business)**: Ảnh hưởng trực tiếp tới vận hành, doanh thu và chi phí (1 = Rất thấp, 5 = Rất cao).

*Thang điểm Priority Score (1 - 125):*
- **75 - 125**: Tối ưu tiên
- **40 - 74**: Cao
- **20 - 39**: Trung bình
- **1 - 19**: Thấp

---

## 📋 Danh sách Backlog Ưu Tiên AIOps

| Mã Task | Hạng mục công việc | Probability (1-5) | Severity (1-5) | Business Impact (1-5) | Priority Score | Mức ưu tiên | Sprint thực hiện |
|---|---|:---:|:---:|:---:|:---:|---|---|
| **TF3-01** | **Báo cáo sự cố INCIDENT-2026-004 & Cảnh báo Slack** (Done) | 5 | 5 | 5 | **125** / 125 | Tối ưu tiên | Sprint 1 |
| **TF3-02** | **Tự động hóa Khắc phục sự cố (Auto-remediation Webhook)** | 4 | 5 | 5 | **100** / 125 | Tối ưu tiên | Sprint 2 |
| **TF3-03** | **Dự báo Sự cố trước thời gian thực (Incident Prediction)** | 3 | 5 | 5 | **75** / 125 | Tối ưu tiên | Sprint 2 |
| **TF3-04** | **Mã hóa Kịch bản Xử lý lỗi (Runbooks as Code)** | 4 | 4 | 4 | **64** / 125 | Cao | Sprint 2 |
| **TF3-05** | **Dashboard Metric Tập trung cho Đội CDO** | 4 | 3 | 4 | **48** / 125 | Cao | Sprint 3 |
| **TF3-06** | **Mở rộng kịch bản Chaos Engineering (Latency, Pod Kill)** | 3 | 3 | 3 | **27** / 125 | Trung bình | Sprint 3 |

---

## 🛠️ Chi tiết từng hạng mục công việc AIOps

### 1) Task TF3-01: Báo cáo sự cố INCIDENT-2026-004 & Cảnh báo Slack (Đã hoàn thành)
- **Mô tả**: Điều tra lỗi cạn kiệt Connection Pool của Payment Service, viết RCA. Xây dựng tin nhắn Block Kit cảnh báo tới Slack, cấp quyền AWS ECR cho đội CDO.
- **Rủi ro**: Hệ thống sập diện rộng nhưng đội CDO không có quyền lấy image phục hồi, quản trị viên mù thông tin (Xác suất: 5, Nghiêm trọng: 5).
- **Tác động Business**: Khôi phục khả năng giao dịch, bảo vệ doanh thu. Cung cấp thông tin trong suốt.
- **Điều kiện hoàn thành**: Báo cáo lưu trên GitHub. Script Slack chạy thành công. CDO pull image thành công.
- **Metrics đo lường**: Thời gian báo cáo sự cố (Dưới 2 tiếng).

### 2) Task TF3-02: Tự động hóa Khắc phục sự cố (Auto-remediation Webhook)
- **Mô tả**: Xây dựng API Webhook Server nhận tín hiệu callback từ nút "Approve Auto-scaling" trên Slack. Tự động chuyển đổi tín hiệu thành lệnh `kubectl scale deployment/payment-service --replicas=5`.
- **Rủi ro**: Nhận cảnh báo nhưng vẫn phải thao tác scale thủ công bằng tay, gây chậm trễ trong việc cứu hệ thống (Xác suất: 4, Nghiêm trọng: 5).
- **Tác động Business**: Biến hệ thống từ bán tự động (cảnh báo) sang tự động hoàn toàn có giám sát (Human-in-the-loop). Đảm bảo giao dịch thông suốt.
- **Phạm vi thực hiện**:
  - Xây dựng HTTP POST callback API.
  - Tích hợp bảo mật RBAC cho API gọi lệnh Kubernetes.
- **Điều kiện hoàn thành**: Click nút trên Slack kích hoạt lệnh scale thành công trên cụm `techx-tf3`.
- **Metrics đo lường**: MTTR (Giảm thời gian thao tác khắc phục xuống dưới 10 giây).

### 3) Task TF3-03: Dự báo Sự cố trước thời gian thực (Incident Prediction)
- **Mô tả**: Tích hợp mô hình dự báo Time-series (ví dụ Prophet/ARIMA) vào `aiops-engine` để phân tích xu hướng metrics. Báo động trước khi Connection Pool thực sự bị cạn kiệt.
- **Rủi ro**: Đợi tới khi lỗi rớt giao dịch (HTTP 503) mới cảnh báo là quá trễ, khách hàng đã bị ảnh hưởng (Xác suất: 3, Nghiêm trọng: 5).
- **Tác động Business**: Tránh hoàn toàn việc mất giao dịch, bảo vệ điểm hài lòng của khách hàng (CSAT).
- **Phạm vi thực hiện**:
  - Gắn AI model phân tích log lịch sử và metric hiện tại.
  - Cấu hình cảnh báo "Tiền sự cố".
- **Điều kiện hoàn thành**: Cảnh báo sớm 15-30 phút trước khi Limit bị chạm ngưỡng.
- **Metrics đo lường**: Tỷ lệ dự đoán chính xác (Prediction Accuracy $>85\%$).

### 4) Task TF3-04: Mã hóa Kịch bản Xử lý lỗi (Runbooks as Code)
- **Mô tả**: Chuyển đổi các quy trình khắc phục thủ công (tài liệu text) thành các script Python thực thi tự động. Tích hợp trực tiếp vào module Remediation.
- **Rủi ro**: Phụ thuộc quá nhiều vào kinh nghiệm của SRE, rủi ro lỗi do con người (Human Error) khi gõ lệnh (Xác suất: 4, Nghiêm trọng: 4).
- **Tác động Business**: Tiêu chuẩn hóa quy trình khắc phục, SRE mới có thể vận hành hệ thống như một chuyên gia.
- **Phạm vi thực hiện**:
  - Viết 5 script cơ bản: Restart Pod, Flush Cache, Scale UP/DOWN, DB Failover, Block IP.
- **Điều kiện hoàn thành**: 100% kịch bản P1 (Critical) đều có script tự động đi kèm.
- **Metrics đo lường**: Tỷ lệ số hóa tài liệu Runbook ($100\%$).

### 5) Task TF3-05: Dashboard Metric Tập trung cho Đội CDO
- **Mô tả**: Triển khai Grafana Dashboard tổng hợp riêng cho đội CDO để quan sát thời gian thực các chỉ số: Transaction Volume, Error Rate, Connection Pool Usage, và tần suất Cảnh báo tại region `us-east-1`.
- **Rủi ro**: Đội quản trị dữ liệu (CDO) thiếu góc nhìn tổng quan (Visibility) để đánh giá sức khỏe nền tảng (Xác suất: 4, Nghiêm trọng: 3).
- **Tác động Business**: Đưa ra quyết định kinh doanh và tối ưu hạ tầng dựa trên dữ liệu (Data-driven).
- **Phạm vi thực hiện**:
  - Cấu hình nguồn dữ liệu Prometheus cho Grafana.
  - Thiết kế các Panel hiển thị và xuất báo cáo.
- **Điều kiện hoàn thành**: Dashboard hoạt động ổn định trên giao diện Web, biểu đồ Real-time (độ trễ < 1 phút).
- **Metrics đo lường**: User Adoption Rate từ đội CDO.

### 6) Task TF3-06: Mở rộng kịch bản Chaos Engineering (Latency, Pod Kill)
- **Mô tả**: Cập nhật `flagd-config` để bơm thêm các lỗi phức tạp: `latencyInjection` (tạo độ trễ 5s) và `randomPodTermination` (giết Pod ngẫu nhiên). Kiểm thử khả năng chịu lỗi của hệ thống.
- **Rủi ro**: Hệ thống không được kiểm chứng khả năng tự phục hồi với các sự cố bất ngờ khác ngoài tràn DB (Xác suất: 3, Nghiêm trọng: 3).
- **Tác động Business**: Tăng cường sự tự tin của tổ chức vào kiến trúc microservices.
- **Phạm vi thực hiện**:
  - Code thêm cờ (flag) vào dịch vụ và `flagd-config`.
  - Lên lịch chạy Chaos Monkey vào giờ thấp điểm (Off-peak).
- **Điều kiện hoàn thành**: Hệ thống tiếp tục xử lý được tối thiểu 90% giao dịch khi bị tiêm độ trễ.
- **Metrics đo lường**: Tỷ lệ sống sót của dịch vụ (Resilience Score).
