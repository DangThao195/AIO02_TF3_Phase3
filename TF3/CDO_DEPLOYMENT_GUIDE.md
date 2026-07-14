# HƯỚNG DẪN TRIỂN KHAI AIOPS ENGINE (DÀNH CHO CDO TEAM - ZONE us-east-1)

Tài liệu này hướng dẫn đội ngũ CDO cách kéo Docker Image, cấu hình các tham số bảo mật và triển khai hệ thống **AIOps Engine** (FastAPI service) chạy thành công trên cụm Kubernetes (EKS) tại zone **N. Virginia (us-east-1)**.

---

## 🚀 1. Docker Image Thông Tin (ECR us-east-1)

Ảnh Docker của AIOps Engine đã được đóng gói và đẩy lên ECR dưới quyền truy cập mở (**Public Pull Policy - Không cần mật khẩu/đăng nhập**):

*   **Image URI:** `197826770971.dkr.ecr.us-east-1.amazonaws.com/tf-2-ai-engine:latest`
*   **Lệnh pull chạy thử trực tiếp:**
    ```bash
    docker pull 197826770971.dkr.ecr.us-east-1.amazonaws.com/tf-2-ai-engine:latest
    ```

---

## ⚙️ 2. Các Cấu Hình Cần Thiết (Environment Variables & Secrets)

Để toàn bộ pipeline (Alert Correlation + RCA + AWS Bedrock LLM + Slack) hoạt động, CDO cần cung cấp các biến môi trường dưới đây khi chạy container. 

Chúng tôi khuyến nghị cấu hình chúng qua **Kubernetes Secret** và ánh xạ vào biến môi trường của Pod (đã định nghĩa mẫu sẵn trong file `aiops-engine-deployment.yaml`):

### 🔑 A. Cấu hình xác thực AWS Bedrock (LLM & RAG)
Dùng để gọi mô hình Claude 3 Sonnet / Nova và kết nối cơ sở tri thức Bedrock Knowledge Base.
*   `AWS_ACCESS_KEY_ID`: Access Key của tài khoản AWS có quyền gọi Bedrock.
*   `AWS_SECRET_ACCESS_KEY`: Secret Access Key tương ứng.
*   `AWS_DEFAULT_REGION`: `us-east-1` (Vùng chạy Bedrock KB và các dịch vụ AI).
*   `BEDROCK_KB_ID`: `GH3FUCYVOJ` (ID của Knowledge Base chứa tri thức sự cố).
*   `BEDROCK_MODEL_ID`: `amazon.nova-lite-v1:0` (Hoặc model ID do BTC chỉ định).

### 💬 B. Cấu hình tương tác Slack (Interactive Alerting)
Dùng để gửi báo cáo sự cố kèm nút bấm "Approve/Reject" hành động sửa lỗi về Slack.
*   `SLACK_BOT_TOKEN`: Token của Slack App (dạng `xoxb-...` hoặc `xoxp-...`).
*   `SLACK_SIGNING_SECRET`: Secret dùng để xác thực chữ ký bảo mật từ Slack gửi về callback.
*   `SLACK_CHANNEL_ID`: ID của kênh Slack nhận thông báo sự cố (ví dụ: `C0BG2EVQS13`).

### 📊 C. Địa chỉ kết nối các hệ thống giám sát (Monitoring Endpoints)
Dùng để tự động kéo metrics và trace lỗi khi sự cố xảy ra.
*   `PROMETHEUS_URL`: `http://prometheus.techx-tf3.svc.cluster.local:9090`
*   `JAEGER_URL`: `http://jaeger.techx-tf3.svc.cluster.local:16686`
*   `OPENSEARCH_URL`: `http://opensearch.techx-tf3.svc.cluster.local:9200`

---

## 📦 3. Các Bước Triển Khai Trên Kubernetes

### Bước 1: Tạo Kubernetes Secret chứa các thông tin nhạy cảm
Hãy chạy lệnh sau trên cụm K8s (thay thế các giá trị thật của dự án):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aiops-engine-secrets
  namespace: techx-tf3
type: Opaque
stringData:
  aws-access-key-id: "YOUR_AWS_ACCESS_KEY_ID"
  aws-secret-access-key: "YOUR_AWS_SECRET_ACCESS_KEY"
  slack-bot-token: "YOUR_SLACK_BOT_TOKEN"
  slack-signing-secret: "YOUR_SLACK_SIGNING_SECRET"
  slack-channel-id: "YOUR_SLACK_CHANNEL_ID"
```

### Bước 2: Deploy ứng dụng sử dụng manifest file
Sử dụng file cấu hình [aiops-engine-deployment.yaml](file:///D:/AWS/AIO23/phase3/TF3/deploy/aiops-engine-deployment.yaml) đi kèm để deploy:
```bash
kubectl apply -f deploy/aiops-engine-deployment.yaml -n techx-tf3
```

---

## 🔍 4. Kiểm Thử & Kiểm Tra Trạng Thái

Sau khi deploy, CDO có thể kiểm tra sức khỏe của dịch vụ thông qua các HTTP endpoints (Cổng mặc định: `8000`):

1.  **Liveness & Readiness Probe (`/healthz`):** 
    *   Trả về HTTP `200 OK` khi ứng dụng đã sẵn sàng nhận webhook.
2.  **Metrics Export (`/metrics`):**
    *   Expose các metric custom như `ai_gateway_requests_total`, `ai_breaker_state` phục vụ Prometheus scrape.
3.  **Slack Callback Endpoint:** `/webhooks/slack/interactive` (Cổng `8000`).
