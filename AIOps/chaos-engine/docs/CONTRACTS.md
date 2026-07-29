# Hợp đồng Giao tiếp & Tích hợp (API & Event Contracts)

Tài liệu này định nghĩa các chuẩn giao tiếp, cấu trúc dữ liệu, và chính sách tích hợp giữa AIOps Engine và các hệ thống ngoại vi (Slack, AWS ECR, Kubernetes). Bất kỳ sự thay đổi nào từ các hệ thống liên quan đều phải tuân thủ nghiêm ngặt các hợp đồng này để đảm bảo hệ thống không bị đứt gãy.

## 1. Hợp đồng Tích hợp Cảnh báo Slack (Slack Alert Integration Contract)

### 1.1 Điểm cuối (Endpoint)
Hệ thống sử dụng **Slack Incoming Webhook** được cấp phát cho kênh nội bộ của dự án.
*   **Bảo mật:** URL Webhook tuyệt đối không được hardcode. Phải được nạp từ biến môi trường thông qua Kubernetes Secrets (`aiops-engine-secrets`).

### 1.2 Cấu trúc Payload (Payload Schema)
Tin nhắn được gửi dưới định dạng **Slack Block Kit (JSON)** để hỗ trợ hiển thị đẹp mắt và tích hợp các nút tương tác.
*Ví dụ Payload cho mã lỗi INCIDENT-2026-004:*
```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🚨 [AIOps Alert] Phát hiện Cạn kiệt Connection Pool (INCIDENT-2026-004)",
        "emoji": true
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Dịch vụ ảnh hưởng:*\nPayment Service (techx-tf3)"
        },
        {
          "type": "mrkdwn",
          "text": "*Mức độ nghiêm trọng:*\nCRITICAL 🔴"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Mô tả nguyên nhân (RCA):* Hệ thống thanh toán đang từ chối giao dịch (503 Service Unavailable). Radar AIOps ghi nhận lượng lớn request không hợp lệ tấn công vào API tạo độ trễ, dẫn đến cạn kiệt Connection Pool."
      }
    },
    {
      "type": "divider"
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "Phê duyệt Tự động Mở rộng (Auto-scale)",
            "emoji": true
          },
          "style": "primary",
          "value": "action_scale_payment_service"
        },
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "Bỏ qua (False Alarm)",
            "emoji": true
          },
          "style": "danger",
          "value": "action_ignore"
        }
      ]
    }
  ]
}
```

## 2. Hợp đồng Tải Docker Image từ AWS ECR (ECR Pull Contract)
Để đội CDO (Chief Data Officer) có thể pull image AI Engine và triển khai tự động, một hợp đồng IAM Policy đã được thiết lập giữa các tài khoản AWS.

*   **Tài khoản lưu trữ (Source Account ID):** `197826770971`
*   **Khu vực lưu trữ (Region):** `ap-southeast-1`
*   **Đường dẫn Image (Image URI):** `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest`
*   **Hợp đồng (Contract Policy):** AWS ECR bucket policy cấp các quyền sau cho `arn:aws:iam::[CDO_ACCOUNT_ID]:root`:
    *   `ecr:GetDownloadUrlForLayer`
    *   `ecr:BatchGetImage`
    *   `ecr:BatchCheckLayerAvailability`

## 3. Hợp đồng Giả lập Lỗi OpenFeature (flagd Fault Injection Contract)
Hệ thống sử dụng **OpenFeature** thông qua provider `flagd` để giả lập sự cố.

*   **Tài nguyên Kubernetes:** ConfigMap mang tên `flagd-config` nằm trong namespace `techx-tf3`.
*   **Hợp đồng (Contract):** Để tiêm lỗi thanh toán, quản trị viên (hoặc automation script) phải thay đổi trường `state` của flag `paymentFailure` sang trạng thái `"ON"`. Dịch vụ thanh toán (Payment Service) đã đăng ký theo dõi (watch) ConfigMap này và sẽ lập tức phản hồi giả lập lỗi mà không cần khởi động lại.

## 4. Hợp đồng Webhook Khắc phục Tự động (Remediation Webhook Contract - Dự kiến)
Dành cho tính năng sẽ phát triển ở Sprint tiếp theo: Khi user bấm nút trên Slack, Slack sẽ gửi một HTTP POST request về API của AIOps Engine.

*   **Giao thức:** HTTP POST
*   **Payload Schema:**
```json
{
  "incident_id": "INCIDENT-2026-004",
  "action_value": "action_scale_payment_service",
  "approved_by": {
    "user_id": "U12345678",
    "username": "commander_john"
  },
  "timestamp": "2026-07-14T08:00:00Z"
}
```
