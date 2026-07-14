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

**AIE cần CDO cung cấp:**

| Thông tin | Mô tả |
|---|---|
| **DB Host** | Địa chỉ nội bộ của PostgreSQL trong cluster (hoặc DNS RDS) |
| **DB Port** | Thường là `5432` |
| **DB Name** | Database chứa bảng reviews của `product-reviews` |
| **Credentials** | Tên Secret/ConfigMap trong K8s chứa username + password (AIE sẽ mount vào Pod) |
| **Quyền truy cập** | `SELECT` trên bảng `productreviews` — chỉ đọc, không ghi |

> ⚠️ AIE **chỉ cần quyền đọc (SELECT)**. Không cần quyền ghi/xoá. CDO có thể tạo một DB user riêng (`copilot_readonly`) với quyền tối thiểu.

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
