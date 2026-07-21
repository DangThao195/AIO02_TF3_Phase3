# HƯỚNG DẪN CHẠY & VẬN HÀNH HỆ THỐNG AIOPS ENGINE

Thư mục `submit/` này chứa toàn bộ tài liệu đặc tả, hợp đồng thiết kế và mã nguồn hoàn chỉnh của hệ thống AIOps Engine do nhóm **TF3** phát triển. Dưới đây là hướng dẫn chi tiết cách chạy kiểm thử (test) và vận hành hệ thống.

---

## 1. Hướng dẫn chạy Unit & Integration Tests (Khuyên dùng trước)
Hệ thống đi kèm bộ test suite bao phủ toàn bộ các module chẩn đoán, cảnh báo và khắc phục sự cố.

### Bước 1: Khởi tạo môi trường ảo và cài đặt thư viện
Di chuyển vào thư mục code và cài đặt các dependencies cần thiết:
```bash
cd ai-engine
python -m venv .venv
# Trên Windows:
.venv\Scripts\activate
# Trên Linux/macOS:
source .venv/bin/activate

pip install -e .
pip install pytest pytest-asyncio
```

### Bước 2: Chạy toàn bộ các test cases
Chạy lệnh pytest để kiểm định chất lượng mã nguồn:
```bash
pytest
```
*Hệ thống sẽ chạy qua 112 test cases bao gồm kiểm tra logic chẩn đoán lỗi, gom nhóm cảnh báo (correlation), và bộ lọc an toàn (Safety Gate).*

---

## 2. Hướng dẫn chạy Local FastAPI Server
Engine chạy như một REST API server tiếp nhận dữ liệu và xử lý webhook tương tác từ Slack.

### Bước 1: Thiết lập cấu hình môi trường (.env)
Tạo file `.env` trong thư mục `ai-engine/` hoặc sử dụng file `.env` có sẵn:
```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-slack-signing-secret
SLACK_CHANNEL_ID=C0XXXXXXXX
OPENSEARCH_URL=http://localhost:9200
JAEGER_URL=http://localhost:16686
PROMETHEUS_URL=http://localhost:9090
```

### Bước 2: Khởi động Server
```bash
uvicorn src.ai_engine.server:create_app --factory --host 0.0.0.0 --port 8000
```
*Server sẽ chạy tại `http://localhost:8000`. Bạn có thể kiểm tra sức khỏe tại endpoint `/healthz`.*

---

## 3. Hướng dẫn Giả lập Sự cố & Chaos Testing (INCIDENT-2026-004)
Để test luồng phát hiện lỗi cạn kiệt Connection Pool của dịch vụ thanh toán (`payment-service`):

### Bước 3.1: Tiêm lỗi (Fault Injection) qua OpenFeature
Sửa đổi ConfigMap `flagd-config` trên cụm EKS để kích hoạt lỗi:
```bash
kubectl edit configmap flagd-config -n techx-tf3
```
Chuyển cờ `paymentFailure` sang trạng thái `"ON"`:
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

### Bước 3.2: Bắn Cảnh báo Slack thủ công (Bypass quét định kỳ)
Để giả lập luồng cảnh báo Slack Block Kit của sự cố 004 ngay lập tức:
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/TXXXX/BXXXX/XXXX"
python scripts/send-incident-slack-004.py
```
*Thẻ thông tin lỗi kèm nút "Approve Auto-scaling" sẽ hiển thị lập tức trên kênh Slack.*

---

## 4. Hướng dẫn CDO lấy Docker Image từ ECR và Deploy lên EKS

### Bước 4.1: Đăng nhập ECR (Quyền pull liên tài khoản đã được cấp)
```bash
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com
```

### Bước 4.2: Kéo Image
```bash
docker pull 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest
```

### Bước 4.3: Deploy lên cụm Kubernetes
Sử dụng các file manifest trong thư mục `deploy/` để áp dụng:
```bash
kubectl apply -f deploy/quota.yaml -n techx-tf3
kubectl apply -f deploy/aiops-engine-deployment.yaml -n techx-tf3
```
