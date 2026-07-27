# HƯỚNG DẪN TRIỂN KHAI AIOPS ENGINE & TRAINING CRONJOB (DÀNH CHO CDO TEAM)

Tài liệu này hướng dẫn đội ngũ CDO cấu hình các tham số bảo mật, tạo các tài nguyên Kubernetes và triển khai hệ thống **AIOps Engine** (FastAPI service) & **Training CronJob** chạy thành công trên cụm Kubernetes (EKS) ở Phase 3.

---

## 🚀 1. Docker Image Thông Tin

Ảnh Docker của AIOps Engine đã được đóng gói và đẩy lên ECR với tag chuyên biệt cho thuật toán Isolation Forest (`IF`):

* **Image URI:** `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:IF`
* **Lệnh pull chạy thử:**
  ```bash
  aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com
  docker pull 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:IF
  ```

---

## ⚙️ 2. Các Cấu Hình Cần Thiết (Environment Variables & Secrets)

Để dịch vụ hoạt động ổn định và bảo mật, CDO cần cung cấp các biến môi trường thông qua **Kubernetes Secret** có tên là **`aiops-engine-secrets`** đặt tại namespace **`techx-tf3`**.

### 🔑 A. Cấu hình Secrets (`aiops-engine-secrets`)
Secret này lưu trữ thông tin nhạy cảm và được chia sẻ dùng chung cho cả **Engine Pod** và **Training CronJob Pod**:
1. `aws-access-key-id`: Access Key ID của tài khoản AWS (cần có quyền ghi/đọc S3 Bucket `tf3-aiops-models-197826770971` và quyền invoke model Bedrock).
2. `aws-secret-access-key`: Secret Access Key tương ứng.
3. `slack-webhook-url`: Đường dẫn Slack Webhook dùng để thông báo sự cố và nhận tương tác phản hồi SRE.

### 📊 B. Cấu hình Tài nguyên & Kháng Tải (EKS Environment Variables)
* `AIOPS_SIMULATION_MODE`: Thiết lập `"false"` khi chạy trên cụm EKS thật (kết nối Prometheus/Jaeger trực tiếp).
* `PROMETHEUS_URL`: `"http://prometheus-server.techx-tf3.svc.cluster.local"` (Địa chỉ dịch vụ Prometheus nội bộ cụm).
* `JAEGER_URL`: `"http://jaeger-query.techx-tf3.svc.cluster.local"` (Địa chỉ dịch vụ Jaeger nội bộ cụm).
* `OPENSEARCH_URL`: `"http://opensearch.techx-tf3.svc.cluster.local:9200"`
* `AIOPS_S3_BUCKET`: `"tf3-aiops-models-197826770971"`
* `BEDROCK_MODEL_ID`: `"amazon.nova-lite-v1:0"` (Dòng mô hình Nova Lite thế hệ mới, tối ưu hóa suy luận RCA).
* `AWS_DEFAULT_REGION`: `"ap-southeast-1"`.
  > [!NOTE]
  > Hệ thống đã được tích hợp cơ chế tự động định tuyến (Safe Fallback Region): Nếu phát hiện vùng chạy EKS là Singapore (`ap-southeast-1`), LLM Client sẽ tự động chuyển hướng các lệnh gọi Bedrock qua vùng **`us-east-1`** (nơi model Nova Lite khả dụng), tránh lỗi kết nối LLM.

---

## 📦 3. Các Bước Triển Khai Trên Kubernetes

CDO tiến hành apply lần lượt các tệp manifest trong thư mục `k8s/` theo trình tự sau:

### Bước 1: Tạo Kubernetes Secret chứa thông tin bảo mật
Chạy lệnh sau hoặc viết file Secret YAML (thay thế các giá trị thật):
```bash
kubectl create secret opaque aiops-engine-secrets \
  --namespace=techx-tf3 \
  --from-literal=aws-access-key-id="YOUR_AWS_ACCESS_KEY_ID" \
  --from-literal=aws-secret-access-key="YOUR_AWS_SECRET_ACCESS_KEY" \
  --from-literal=slack-webhook-url="YOUR_SLACK_WEBHOOK_URL"
```

### Bước 2: Tạo PriorityClass cho Job huấn luyện
Tạo PriorityClass `low-priority` để đảm bảo Job huấn luyện định kỳ không cạnh tranh CPU/RAM với Pod Production khi tải cao:
```bash
kubectl apply -f k8s/priority-class.yaml
```

### Bước 3: Triển khai Engine và CronJob
Triển khai dịch vụ AIOps Engine và cài đặt lịch chạy tự động huấn luyện Isolation Forest (Job chạy lúc 2AM Thứ Hai hàng tuần):
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/training-cronjob.yaml
```

---

## 🔍 4. Quản Lý Phiên Bản & Hot Reload (Phase 3 Operators)

### A. Quản lý phiên bản tự động (MLOps S3 Manifest)
Hệ thống sử dụng cơ chế **Manifest-based Versioning** để đảm bảo tính nguyên tử (Atomicity):
* Mô hình huấn luyện được đẩy đồng thời vào `archive/<timestamp>/` và thư mục tương thích ngược `current/`.
* Tệp `active_manifest.json` được ghi đè ở bước cuối cùng khi toàn bộ 7 mô hình đã upload thành công và vượt qua kiểm định chất lượng (Precision $\ge$ 0.75, Recall $\ge$ 0.70).
* Engine khi khởi động sẽ tự động đọc `active_manifest.json` để tải đúng phiên bản mô hình sạch.

### B. Nạp nóng mô hình trực tuyến (Hot Reload)
Khi CronJob hoàn tất huấn luyện mô hình mới và đẩy lên S3, CDO hoặc SRE **không cần restart Pod** của Engine. Chỉ cần gửi một request POST tới endpoint bảo mật của Engine để kích hoạt nạp nóng tức thời (Zero-Downtime):
```bash
curl -X POST http://aiops-engine.techx-tf3.svc.cluster.local/reload-models
```
* **Phản hồi thành công mẫu:**
  ```json
  {
    "status": "success",
    "message": "Successfully hot-reloaded all Isolation Forest models from S3.",
    "loaded_models": ["checkout", "frontend", "payment", "product-catalog", "product-reviews", "recommendation", "shipping"]
  }
  ```
