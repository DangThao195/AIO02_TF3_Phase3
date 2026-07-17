# Deployment Contract — AIE2 Shopping Copilot
<!-- Owner: AIO02 | Version: 1.1.0 | Date: 2026-07-17 -->
<!-- Cập nhật: thêm Valkey session, ECR image thực tế, K8s manifests đầy đủ -->

## Tổng quan

Shopping Copilot là AI chatbot hỗ trợ mua sắm, chạy dưới dạng FastAPI service, tích hợp với:
- **AWS Bedrock** (Nova Lite LLM + Guardrails + Knowledge Base RAG)
- **EKS Microservices** của TechX Corp qua gRPC
- **PostgreSQL** của cluster qua K8s DNS
- **Valkey** (Redis-compatible) cho session và cache persistence

---

## AIE cung cấp cho CDO

| Artifact | Giá trị |
|---|---|
| **ECR Image URI** | `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/shopping-copilot:v1.0.0` |
| **ECR Region** | `ap-southeast-1` (Singapore) |
| **Port** | `8001` |
| **Health check** | `GET /health` → HTTP 200 |
| **API doc** | `GET /docs` (Swagger UI) |
| **K8s manifests** | `contracts/k8s-deployment.yaml`, `contracts/k8s-serviceaccount.yaml` |

---

## CDO cần thực hiện

### 1. Tạo IAM Role cho IRSA

Pod cần quyền gọi AWS Bedrock. CDO tạo IAM Role với trust policy cho EKS OIDC và policy sau:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ApplyGuardrail",
        "bedrock:Retrieve"
      ],
      "Resource": "*"
    }
  ]
}
```

Sau khi tạo Role, điền ARN vào annotation trong `k8s-serviceaccount.yaml`:
```yaml
eks.amazonaws.com/role-arn: "arn:aws:iam::197826770971:role/<tên-role-CDO-tạo>"
```

### 2. Apply các manifest theo thứ tự

```bash
# 1. ServiceAccount (IRSA)
kubectl apply -f contracts/k8s-serviceaccount.yaml

# 2. ConfigMap + Secret + Deployment + Service
kubectl apply -f contracts/k8s-deployment.yaml

# 3. Kiểm tra Pod đã Ready
kubectl get pods -n techx-tf3 -l app=shopping-copilot
kubectl logs -n techx-tf3 -l app=shopping-copilot --tail=30
```

### 3. Xác nhận Health Check

```bash
# Port-forward để test local (hoặc dùng Service ClusterIP)
kubectl port-forward svc/shopping-copilot 8001:8001 -n techx-tf3
curl http://localhost:8001/health
# → {"status": "ok", ...}
```

---

## Cấu hình môi trường đầy đủ

Tất cả biến đã có trong `k8s-deployment.yaml` (ConfigMap + Secret). Ghi chú quan trọng:

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `VALKEY_URL` | `redis://valkey-cart.techx-tf3.svc.cluster.local:6379/1` | DB=1 để tách Cart (DB=0) |
| `DB_HOST` | `postgresql.techx-tf3.svc.cluster.local` | K8s internal DNS |
| `DB_PORT` | `5432` | Cổng PostgreSQL tiêu chuẩn trên cluster |
| `BEDROCK_KB_ID` | `UCTITOWFHE` | Knowledge Base ID trên AWS |
| `REVIEWS_ADDR` | `product-reviews.techx-tf3.svc.cluster.local:3551` | gRPC port 3551 |
| `CATALOG_ADDR` | `product-catalog.techx-tf3.svc.cluster.local:8080` | gRPC port 8080 |

> ⚠️ **Lưu ý quan trọng về `REVIEWS_ADDR`**: port phải là `3551` (gRPC internal), không phải `9090` (port-forward dev).

---

## Phụ thuộc trên cluster

Shopping Copilot yêu cầu các service sau **đã chạy** trước khi deploy:

| Service | Namespace | Ghi chú |
|---|---|---|
| `postgresql` | `techx-tf3` | Schema `catalog` và `reviews` phải tồn tại |
| `valkey-cart` | `techx-tf3` | Dùng DB=1, không cần password |
| `product-catalog` | `techx-tf3` | gRPC port 8080 |
| `cart` | `techx-tf3` | gRPC port 8080 |
| `product-reviews` | `techx-tf3` | gRPC port 3551 |
| `recommendation` | `techx-tf3` | gRPC port 8080 |
| `currency` | `techx-tf3` | gRPC port 8080 |
| `shipping` | `techx-tf3` | HTTP port 8080 |

---

## Resource Requirements

| | Request | Limit |
|---|---|---|
| **CPU** | 250m | 1000m |
| **Memory** | 512Mi | 1Gi |
| **Replicas** | 2 | — |

---

## Phân công

| Việc | AIE | CDO |
|---|---|---|
| Build & push image lên ECR | ✅ | |
| Tạo IAM Role IRSA | | ✅ |
| Apply ServiceAccount + annotate IRSA | | ✅ |
| Apply ConfigMap, Secret, Deployment, Service | | ✅ |
| Cấp quyền pull ECR image cho node group | | ✅ |
| Xác nhận các microservices phụ thuộc đang chạy | | ✅ |
| Fix lỗi tầng AI / code | ✅ | |
| Xử lý Pod crash / tài nguyên cluster | | ✅ |
