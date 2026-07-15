# Deployment Contract - AIE2 Shopping Copilot

<!-- Owner: AIO02 | Signed by: AI Lead + CDO Leads | Date: 2026-07-14 -->

## Mục đích

Đặc tả những gì CDO cần làm để tích hợp Shopping Copilot vào cluster TF và những gì AIE cần CDO cung cấp.

---

## AIE cung cấp cho CDO

| Artifact | Nội dung |
|---|---|
| **ECR Image** | `<ACCOUNT>.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:1.0-shopping-copilot` |
| **Port** | `8001` |
| **Health check path** | `GET /chatbot` → HTTP 200 |
| **Prometheus metrics** | `GET /metrics` — scrape vào Prometheus của TF |

---

## CDO cần thiết lập

### 1. Environment Variables (ConfigMap)

```env
# AWS Bedrock
AWS_REGION=ap-southeast-1
BEDROCK_MODEL_ID=apac.amazon.nova-lite-v1:0

# Địa chỉ gRPC microservices trong cluster (CDO điền theo DNS thật của TF)
CATALOG_ADDR=product-catalog.<namespace>.svc.cluster.local:3550
CART_ADDR=cart.<namespace>.svc.cluster.local:7070
REVIEWS_ADDR=product-reviews.<namespace>.svc.cluster.local:9090
RECO_ADDR=recommendation.<namespace>.svc.cluster.local:8081
CURRENCY_ADDR=currency.<namespace>.svc.cluster.local:7001
SHIPPING_ADDR=http://shipping.<namespace>.svc.cluster.local:50051

# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.<namespace>.svc.cluster.local:4317
```

### 2. IAM Permission cho Pod (IRSA)

Pod cần IAM Role với 2 quyền sau để gọi Bedrock:

```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel", "bedrock:ApplyGuardrail"],
  "Resource": "*"
}
```

### 3. Prometheus Scrape Config

Thêm scrape target vào Prometheus của TF:
```yaml
- job_name: shopping-copilot
  static_configs:
    - targets: ['shopping-copilot.<namespace>.svc.cluster.local:8001']
```

---

## AIE cần CDO cung cấp

### Kết nối Database (cho tính năng RAG)

Shopping Copilot cần đọc dữ liệu **product reviews** từ database của `product-reviews` service để phục vụ tính năng hỏi-đáp dựa trên review thật (RAG — không hallucinate).

Sau khi kiểm tra cấu hình chạy hiện tại của microservice `product-reviews` trên cluster EKS, thông tin kết nối Database của hệ thống như sau:

| Thông tin | Giá trị mặc định trên EKS | Ghi chú |
|---|---|---|
| **DB Host** | `postgresql` (hoặc `postgresql.<namespace>.svc.cluster.local`) | CDO cấu hình qua DNS nội bộ K8s |
| **DB Port** | `5432` | Cổng PostgreSQL tiêu chuẩn |
| **DB Name** | `otel` | Tên database của hệ thống |
| **DB User** | `otelu` | AIE chỉ cần quyền `SELECT` |
| **DB Password** | `otelp` | Mật khẩu truy cập |
| **Bảng dữ liệu** | `productreviews` | Chứa review của khách hàng |

> ⚠️ CDO cần cấu hình các tham số kết nối Database trên dưới dạng các biến môi trường (hoặc Secrets) tương ứng cho Pod `shopping-copilot` khi triển khai. AIE **chỉ cần quyền đọc (SELECT)**, đảm bảo an toàn dữ liệu.

---

## Tóm tắt phân công

| Việc | AIE | CDO |
|---|---|---|
| Build & push image lên ECR | ✅ | |
| Tích hợp image vào Helm chart / deployment | | ✅ |
| Cấu hình env vars theo bảng trên | | ✅ |
| Cấp IAM Role (IRSA) | | ✅ |
| Thêm Prometheus scrape target | | ✅ |
| Cung cấp DB connection cho RAG | | ✅ |
| Sửa code khi lỗi tầng AI | ✅ | |
| Xử lý Pod sập / tài nguyên | | ✅ |
