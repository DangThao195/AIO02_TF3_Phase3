# Deployment Contract - Task force 02 (Phase 3)
**Dự án:** Shopping Copilot (AIE2)

<!-- Owner: Nhóm AI 02
     Signed by: AI Lead + CDO Leads
     Date signed: 2026-07-14
     🔒 FREEZE - no change without formal change request -->

## 1. Mục đích

Định nghĩa **Cách thức deploy Shopping Copilot (AIE) lên hệ thống EKS của CDO** - bao gồm tài nguyên CPU/RAM, cơ chế Scaling, phân quyền IAM, mạng lưới bảo mật, và chiến lược cuộn (rollout/rollback). CDO sẽ sử dụng đặc tả này để lập trình tệp cấu hình Helm Chart / Kubernetes Manifests.

---

## 2. Compute (Tài nguyên tính toán)

Chatbot được triển khai dưới dạng một dịch vụ microservice chạy trên các Pod của AWS EKS (môi trường sản xuất thực tế):

| Thuộc tính | Cấu hình tham chiếu |
|---|---|
| **Target Host** | AWS EKS Node Group (Linux x86_64) |
| **Namespace** | `aie-prod` |
| **Service Name** | `shopping-copilot` |
| **Docker Image Source**| AWS ECR (Elastic Container Registry) của Task force |
| **CPU per Pod (Request)**| `200m` (0.2 vCPU) |
| **CPU per Pod (Limit)**  | `500m` (0.5 vCPU) |
| **RAM per Pod (Request)**| `512 Mi` |
| **RAM per Pod (Limit)**  | `1024 Mi` (1 Gi) |

---

## 3. Scaling (Tự động mở rộng)

Cấu hình **Horizontal Pod Autoscaler (HPA)** để đảm bảo hệ thống chịu được tải đột biến:

| Thuộc tính | Giá trị tham chiếu |
|---|---|
| **Replicas (Tối thiểu)**| 2 (Đảm bảo tính sẵn sàng cao - High Availability) |
| **Replicas (Tối đa)**  | 10 |
| **Autoscale Trigger 1**| CPU Utilization > 70% |
| **Autoscale Trigger 2**| Request Count > 100 requests/giây mỗi Pod |
| **Scale-up Cooldown**  | 60 giây |
| **Scale-down Cooldown**| 300 giây |

---

## 4. Secrets & Credentials (Bảo mật)

**Bắt buộc:** Không sử dụng các khoá truy cập tĩnh (AWS Access Keys) trong container.
* **IAM Role cho Service Account (IRSA):** CDO liên kết một AWS IAM Role với Kubernetes Service Account của Pod AIE. Role này phải cấp quyền giao tiếp với AWS Bedrock và AWS Guardrails.
* **Biến môi trường (Environment Variables):**
  * `AWS_REGION=ap-southeast-1`
  * `BEDROCK_MODEL_ID=apac.amazon.nova-lite-v1:0`

---

## 5. Networking (Mạng lưới & Bảo mật)

AIE2 cần được thiết lập mạng cô lập an toàn:
* **Subnet Type:** Hoạt động hoàn toàn trong **Private Subnets** (Mạng nội bộ).
* **Ingress Rules:** Chỉ cho phép nhận traffic từ API Gateway / ALB (Application Load Balancer) nội bộ phục vụ Frontend qua cổng HTTP `8001`.
* **Egress Rules:**
  * Chỉ cho phép gọi ra ngoài mạng (Internet/VPC Endpoint) tới AWS Bedrock API (`bedrock-runtime`).
  * Chỉ cho phép kết nối nội bộ cụm EKS tới các gRPC microservices: Catalog (`3550`), Cart (`7070`), Reviews (`9090`), Reco (`8081`), Currency (`7001`), Shipping (`50052`).

---

## 6. Rollout & Rollback (Chiến lược triển khai và quay lui)

### 6.1 Chiến dịch cuộn (Canary Rollout)
Sử dụng công cụ **Argo Rollouts** (hoặc AWS App Mesh) để kiểm tra độ ổn định trước khi release 100%:

| Bước | Lưu lượng Traffic | Thời gian duy trì |
|---|---|---|
| 1 | 10% | 5 phút |
| 2 | 50% | 5 phút |
| 3 | 100% | Hoàn thành |

### 6.2 Điều kiện huỷ bỏ Canary (Abort Criteria)
Nếu trong quá trình Canary Rollout phát hiện bất kỳ lỗi nào sau đây, ArgoCD sẽ tự động thực hiện **Rollback lập tức** về phiên bản cũ:
* Tỷ lệ lỗi HTTP 5xx của Chatbot > 2%.
* Độ trễ đáp ứng P99 > 3.5 giây (SLA trễ của LLM).
* Pod bị lỗi khởi động (`CrashLoopBackOff` hoặc `OOMKilled`).

### 6.3 Rollback
* **Cách thực hiện chính:** ArgoCD tự động quay lui cấu hình (Revert Git Commit SHA).
* **Target RTO (Thời gian khôi phục dịch vụ):** < 30 giây.

---

## 7. Health Check (Kiểm tra sức khỏe Pod)

CDO cấu hình Liveness/Readiness Probes trên Kubernetes:
* **HTTP Path:** `/chatbot` (trả về mã 200 OK khi server sẵn sàng)
* **Port:** `8001`
* **Check Interval:** 15 giây.
* **Failure Threshold:** 3 lần thất bại liên tục $\rightarrow$ K8s kill Pod và khởi động lại Pod mới.
