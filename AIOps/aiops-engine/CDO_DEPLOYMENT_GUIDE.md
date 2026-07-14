# HƯỚNG DẪN TRIỂN KHAI AIOPS ENGINE (DÀNH CHO CDO TEAM)

Tài liệu này hướng dẫn đội ngũ CDO cách kéo Docker Image, cấu hình các tham số bảo mật và triển khai hệ thống **AIOps Engine** (FastAPI service) chạy thành công trên cụm Kubernetes (EKS).

---

## 🚀 1. Docker Image Thông Tin

Ảnh Docker của AIOps Engine đã được đóng gói và đẩy lên ECR cá nhân dưới quyền truy cập mở (**Public Pull Policy - Không cần mật khẩu/đăng nhập**):

* **Image URI:** `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest`
* **Lệnh pull chạy thử:**
  ```bash
  docker pull 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest
  ```

---

## ⚙️ 2. Các Cấu Khiên Cần Thiết (Environment Variables & Secrets)

Để toàn bộ pipeline (Alert Correlation + RCA + AWS Bedrock LLM + Slack) hoạt động, CDO cần cung cấp các biến môi trường dưới đây khi chạy container. 

Chúng tôi khuyến nghị cấu hình chúng qua **Kubernetes Secret** và ánh xạ vào biến môi trường của Pod (đã định nghĩa mẫu sẵn trong file `deployment.yaml`):

### 🔑 A. Cấu hình xác thực AWS Bedrock (LLM & RAG)
Dùng để gọi mô hình Claude 3 Sonnet và kết nối cơ sở tri thức Bedrock Knowledge Base.
* `AWS_ACCESS_KEY_ID`: Access Key của tài khoản AWS có quyền gọi Bedrock.
* `AWS_SECRET_ACCESS_KEY`: Secret Access Key tương ứng.
* `AWS_DEFAULT_REGION`: `us-east-1` (Vùng chạy Bedrock KB).
* `BEDROCK_KB_ID`: `GH3FUCYVOJ` (ID của Knowledge Base chứa tri thức sự cố).

### 💬 B. Cấu hình tương tác Slack (Interactive Alerting)
Dùng để gửi báo cáo sự cố kèm nút bấm "Approve/Reject" hành động sửa lỗi về Slack.
* `SLACK_BOT_TOKEN`: Token của Slack App (dạng `xoxb-...`).
* `SLACK_CHANNEL`: ID của kênh Slack nhận thông báo sự cố (ví dụ: `C07D...`).

### 📊 C. Địa chỉ kết nối các hệ thống giám sát (Monitoring Endpoints)
Dùng để tự động kéo metrics và trace lỗi khi sự cố xảy ra.
* `PROMETHEUS_HOST`: `prometheus-server.techx-tf3.svc.cluster.local` (Port: `80`)
* `JAEGER_QUERY_HOST`: `jaeger-query-manager.techx-tf3.svc.cluster.local` (Port: `16686`)

---

## 📦 3. Các Bước Triển Khai Trên Kubernetes

### Bước 1: Tạo Kubernetes Secret chứa các thông tin nhạy cảm
Hãy chạy lệnh sau trên cụm K8s (thay thế các giá trị thật của dự án):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aiops-secrets
  namespace: techx-tf3
type: Opaque
stringData:
  aws-access-key-id: "YOUR_AWS_ACCESS_KEY_ID"
  aws-secret-access-key: "YOUR_AWS_SECRET_ACCESS_KEY"
  slack-bot-token: "YOUR_SLACK_BOT_TOKEN"
  slack-channel: "YOUR_SLACK_CHANNEL"
```

### Bước 2: Deploy ứng dụng sử dụng manifest file
Sử dụng file cấu hình [deployment.yaml](file:///d:/Xbrain/Read_Capstone03/aiops-engine/deployment.yaml) đi kèm để deploy:
```bash
kubectl apply -f deployment.yaml -n techx-tf3
```

---

## 🔍 4. Kiểm Tra Trạng Thái & Telemetry Probes

Sau khi deploy, CDO có thể kiểm tra sức khỏe của dịch vụ thông qua các HTTP endpoints (Cổng mặc định: `8000`):

1. **Readiness Probe (`/readyz`):** 
   * Trả về HTTP `200 OK` khi ứng dụng đã sẵn sàng nhận webhook cảnh báo từ Alertmanager.
2. **Version & Topology Probe (`/version`):**
   * Trả về thông tin phiên bản code và trạng thái nạp đồ thị dịch vụ (Service Topology Graph) thời gian thực.
   * Định dạng output mẫu:
     ```json
     {
       "status": "healthy",
       "version": "1.2.0",
       "graph_metadata": {
         "nodes_count": 12,
         "edges_count": 15,
         "graph_version": "a4d3e7...",
         "graph_loaded_at": "2026-07-13T10:00:00Z"
       }
     }
     ```
