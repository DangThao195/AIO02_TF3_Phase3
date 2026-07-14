# Báo cáo Chứng minh Khái niệm (Proof of Concept - POC)

## 1. Mục tiêu (Objective)
Tài liệu POC này nhằm chứng minh tính khả thi của hệ thống TF3 AIOps Engine trong việc thiết lập một quy trình khép kín: **Giả lập sự cố $\rightarrow$ Phát hiện lỗi $\rightarrow$ Gửi cảnh báo tương tác $\rightarrow$ Đề xuất khắc phục**. 

Kịch bản được chọn để làm POC là mã sự cố `INCIDENT-2026-004` (Cạn kiệt Connection Pool của Dịch vụ Thanh toán do bị quét/tấn công mạng).

## 2. Các bước triển khai POC (Implementation Steps)

### Bước 1: Giả lập Sự cố (Fault Simulation)
*   **Công cụ:** OpenFeature kết hợp với provider `flagd`.
*   **Thực thi:** Quản trị viên tiến hành sửa đổi ConfigMap `flagd-config` trong namespace `techx-tf3` của EKS cluster. Cờ `paymentFailure` được chuyển trạng thái từ `OFF` sang `ON`.
*   **Kết quả:** Dịch vụ `payment-service` ngay lập tức nhận diện sự thay đổi của cờ và bắt đầu từ chối các giao dịch hợp lệ, tạo ra các ngoại lệ (exceptions) và lỗi HTTP 503.

### Bước 2: Phát hiện Sự cố (Detection)
*   **Cơ chế:** Logs và Metrics (như số lượng kết nối DB đang bị treo, tỷ lệ lỗi tăng vọt) được AIOps Engine quét liên tục.
*   **Kết quả:** Hệ thống phát hiện sự gia tăng bất thường (anomaly) của lỗi 503 trùng khớp với pattern cạn kiệt Connection Pool. Sự kiện được gán nhãn là `INCIDENT-2026-004`.

### Bước 3: Cảnh báo Tương tác (Notification & Interaction)
*   **Công cụ:** Python Webhook kết hợp Slack Block Kit (`send-incident-slack-004.py`).
*   **Thực thi:** Ngay khi phát hiện sự cố, Engine gọi module cảnh báo, gửi một tin nhắn được định dạng đồ họa đẹp mắt vào kênh Slack chỉ huy.
*   **Kết quả:** Tin nhắn hiển thị rõ "Dịch vụ bị ảnh hưởng", "Mức độ nghiêm trọng", "Nguyên nhân gốc rễ (RCA)" và cung cấp các nút bấm tương tác (Approve Auto-scaling). Người vận hành không cần phải đọc text thô (raw logs) để hiểu sự cố.

### Bước 4: Chia sẻ Artifact xuyên tài khoản (Cross-Account Sharing for CDO)
*   **Công cụ:** AWS ECR Resource-based Policy.
*   **Thực thi:** Định nghĩa tệp `ecr-policy.json` cấp quyền pull image `tf-2-ai-engine:latest` cho tài khoản AWS của đội CDO.
*   **Kết quả:** Đội CDO đã có thể tự động triển khai phiên bản engine mới nhất về cluster riêng của họ ở bất kỳ region nào để thẩm định.

## 3. Kết luận (Conclusion)
*   POC đã **THÀNH CÔNG** chứng minh năng lực tự động hóa giám sát và phản hồi sự cố của hệ thống AIOps.
*   Giảm thiểu thao tác can thiệp thủ công (Zero-touch) trong việc bắn cảnh báo. Đẩy nhanh tốc độ xử lý sự cố từ vài giờ (cách truyền thống) xuống còn vài phút thông qua các nút bấm hành động (Actionable Buttons).
*   Hệ thống đã hoàn thiện tính đóng gói và sẵn sàng bàn giao cho các bộ phận khác (như CDO) sử dụng.
