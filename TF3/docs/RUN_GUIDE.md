# Sổ tay Vận hành & Triển khai (RUN_GUIDE) - TF3 AIOps

Tài liệu này cung cấp hướng dẫn toàn diện từ cách cài đặt, chạy thử (deploy), cho đến cách giả lập lỗi và kiểm tra cảnh báo của hệ thống AIOps Engine. Tài liệu này đặc biệt hữu ích cho đội CDO và các tư lệnh quản lý hệ thống.

## 1. Yêu cầu Hệ thống (Prerequisites)
Trước khi bắt đầu, đảm bảo máy tính làm việc của bạn (hoặc CI/CD pipeline) đáp ứng các yêu cầu sau:
- Đã cài đặt **AWS CLI** và cấu hình tài khoản có đủ quyền truy cập (IAM Credentials).
- Đã cài đặt và cấu hình **kubectl** trỏ tới cụm EKS hiện tại.
- Đã cài đặt **Docker** (nếu muốn pull và chạy image ở môi trường local).
- Có sẵn một **Slack Incoming Webhook URL** (Dùng để nhận thông báo).

## 2. Dành cho Đội CDO: Triển khai AIOps Engine từ ECR
AIOps Engine đã được đóng gói thành Docker Image và cấp quyền truy cập xuyên tài khoản (Cross-Account). Đội CDO làm theo các bước sau để lấy image:

### Bước 2.1: Đăng nhập vào Amazon ECR
```bash
# Lấy mật khẩu xác thực và đăng nhập vào Docker với quyền AWS
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com
```

### Bước 2.2: Kéo (Pull) Image về máy
```bash
# Pull phiên bản mới nhất của ai-engine
docker pull 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest
```

### Bước 2.3: Chạy Engine (Local Testing)
Bạn có thể chạy thử trực tiếp container này để thẩm định mã nguồn:
```bash
docker run -e SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR_WEBHOOK_URL" 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest
```

## 3. Hướng dẫn Giả lập Sự cố (Chaos Testing / Fault Injection)
Để kiểm tra xem Engine có hoạt động đúng không, chúng ta sẽ cố ý tạo ra sự cố `INCIDENT-2026-004` thông qua cơ chế Feature Flag.

### Bước 3.1: Chỉnh sửa ConfigMap
Trong namespace `techx-tf3`, dịch vụ `payment-service` đang đọc cấu hình lỗi từ `flagd-config`. Chạy lệnh:
```bash
kubectl edit configmap flagd-config -n techx-tf3
```

### Bước 3.2: Kích hoạt Lỗi Thanh toán
Tìm đến đoạn cấu hình `paymentFailure` và đổi giá trị `"state"` từ `"OFF"` thành `"ON"` như dưới đây:
```json
"paymentFailure": {
  "state": "ON",
  "defaultVariant": "on",
  "variants": {
    "on": true,
    "off": false
  }
}
```
*Lưu ý: Ngay sau khi bạn lưu file, lỗi sẽ bắt đầu xuất hiện trong hệ thống thực (không cần khởi động lại Pod).*

## 4. Hướng dẫn Gửi cảnh báo Slack Thủ công (Manual Alert Testing)
Trong trường hợp bạn muốn kiểm tra trực tiếp giao diện cảnh báo trên Slack mà không cần chờ đợi hệ thống giám sát quét đủ chu kỳ:

### Bước 4.1: Đi tới thư mục script
```bash
cd ai-engine/scripts
```

### Bước 4.2: Chạy Script cảnh báo
Đảm bảo bạn đã export biến môi trường Webhook URL:
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXX"
python send-incident-slack-004.py
```
*Bạn sẽ ngay lập tức nhận được thẻ cảnh báo có nút bấm màu đỏ/xanh trên Slack.*

## 5. Giám sát & Đọc Logs (Monitoring)
Để xác nhận rằng việc giả lập lỗi đã thành công, bạn có thể kiểm tra logs của Dịch vụ Thanh toán:
```bash
kubectl logs deployment/payment-service -n techx-tf3 -f
```
Nếu bạn thấy các thông báo kiểu `503 Service Unavailable` hoặc `Connection Pool Exhausted`, có nghĩa là quy trình tiêm lỗi đã hoàn hảo. Lúc này, chỉ cần chờ đợi hệ thống Radar/Dashboard tự động kích hoạt tiến trình xử lý sự cố.
