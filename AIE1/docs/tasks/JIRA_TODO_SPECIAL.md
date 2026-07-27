# Kế hoạch Công việc Đặc biệt - Nhóm AIE1 (JIRA TODO SPECIAL)

Tài liệu này chứa nội dung chi tiết các công việc đặc biệt (**JIRA TODO SPECIAL**) nhằm giải quyết dứt điểm các điểm nghẽn hạ tầng & bảo mật (Promotion Blockers) được chỉ ra trong báo cáo kiểm toán CDO tại [product-reviews-readonly-audit-2026-07-26.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/reports/product-reviews-readonly-audit-2026-07-26.md). Toàn bộ các ticket này được giao cho **1 người thực hiện duy nhất (Khoa - Leader)** để đảm bảo tính nhất quán tuyệt đối và triển khai tuyến tính từ đầu đến cuối.

---

## 📋 PHÂN CHIA CÔNG VIỆC TỔNG QUAN (JIRA SPECIAL)

| Ticket | Tên Công Việc | Người thực hiện (Assignee) | Trụ cột ảnh hưởng |
|:---:|:---|:---:|:---|
| **S1** | Chọn Kiến trúc Bedrock Egress & Loại bỏ mở `0.0.0.0/0:443` | **Khoa (Leader)** | Security & Network Architecture |
| **S2** | ServiceAccount Token Hardening (Tắt K8s API Token) | **Khoa (Leader)** | K8s Security & Hardening |
| **S3** | Chuẩn hóa NetworkPolicy Pod Selectors theo AWS VPC CNI | **Khoa (Leader)** | Network Policy & GitOps |
| **S4** | Văn bản hóa Kiến trúc Guardrail & Tối giản IAM Role Policy | **Khoa (Leader)** | IAM & Compliance |
| **S5** | Chạy Validation & Thu thập Bằng chứng Promo (Evidence) | **Khoa (Leader)** | Release & Quality Assurance |

---

## TICKET S1: Tối Ưu Kiến Trúc Bedrock Egress & Loại Bỏ Quy Tắc Mở `0.0.0.0/0:443`
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Epic:** AIE1 - CDO Audit Promotion Unblocker
* **Ưu tiên:** High (P0)
* **Label Jira:** `cdo-audit`, `network-policy`, `egress-proxy`

### Mô tả công việc (Description)
Chính sách mạng hiện tại của dịch vụ `product-reviews` đang bị CDO chặn không cho promote (`promotion-blocked`) do mở quy tắc egress tự do `0.0.0.0/0:443` ra Internet để gọi AWS Bedrock Runtime (`us-east-1`) từ VPC Singapore (`ap-southeast-1`). Cần triển khai giải pháp kiến trúc Egress chuẩn để gỡ bỏ blocker này.

### Các tác vụ con (Sub-tasks)
* **Sub-task S1.1: Thống nhất phương án kiến trúc Egress với Infra/CDO team**
  - Đánh giá và lựa chọn 1 trong 3 phương án do CDO đề xuất.
  - *Phương án ưu tiên:* Định tuyến luồng Bedrock qua GitOps-managed Egress Proxy với FQDN allowlist (`*.bedrock-runtime.us-east-1.amazonaws.com`, `sts.ap-southeast-1.amazonaws.com`).
  - *Phương án tạm thời:* Đăng ký ngoại lệ HTTPS NAT có hạn chót (Expiry Date), chủ sở hữu và tiêu chí rollback rõ ràng.
* **Sub-task S1.2: Loại bỏ quy tắc Egress Wildcard trong NetworkPolicy**
  - Cập nhật tệp NetworkPolicy `gitops/infrastructure/network-policy-staged/32-product-reviews.yaml` gỡ bỏ hoàn toàn quy tắc wildcard `0.0.0.0/0:443`.
  - Cấu hình lại các cổng egress cụ thể hướng tới Egress Proxy hoặc Gateway chỉ định.
* **Sub-task S1.3: Kiểm tra tính khả thi của Private Endpoint cho STS**
  - Đánh giá việc tạo VPC Interface Endpoint cho STS tại Singapore (`ap-southeast-1`).
  - Kiểm tra Private DNS, Endpoint Policy và Security Group để loại bỏ hoàn toàn luồng STS egress ra public Internet.

---

## TICKET S2: Hardening ServiceAccount Token (Tắt Kubernetes API Token Mặc Định)
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Epic:** AIE1 - CDO Audit Promotion Unblocker
* **Ưu tiên:** High (P1)
* **Label Jira:** `k8s-security`, `helm`, `hardening`

### Mô tả công việc (Description)
CDO phát hiện Pod `product-reviews` vẫn tự động mount Kubernetes API Token mặc định (`kube-api-access-*`), gây rủi ro an ninh K8s. Cần cấu hình Helm Chart để tắt việc tự động mount token này.

### Các tác vụ con (Sub-tasks)
* **Sub-task S2.1: Cấu hình tắt automount Token trong Helm Chart**
  - Chỉnh sửa Helm Chart template / `values.yaml` của dịch vụ `product-reviews`.
  - Thêm cấu hình `automountServiceAccountToken: false` ở cả cấp độ ServiceAccount và Pod Spec.
* **Sub-task S2.2: Render và kiểm tra Pod Spec sau khi triển khai**
  - Thực hiện `helm template` và `kubectl get pod` để xác nhận Pod chỉ giữ duy nhất volume IRSA `aws-iam-token` cho việc xác thực IAM Role AWS Bedrock.
  - Đảm bảo trong Pod không còn chứa volume hay mount path dạng `kube-api-access-*`.

---

## TICKET S3: Chuẩn Hóa NetworkPolicy Pod Selectors Theo AWS VPC CNI Standard
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Epic:** AIE1 - CDO Audit Promotion Unblocker
* **Ưu tiên:** High (P1)
* **Label Jira:** `aws-vpc-cni`, `network-policy`, `k8s`

### Mô tả công việc (Description)
AWS VPC CNI hoạt động ở chế độ `standard`, đánh giá traffic sau bước Service DNAT. Việc quy định peer theo ClusterIP `/32` sẽ khiến traffic bị block nhầm. Cần chuyển sang dùng Pod Selectors chuẩn.

### Các tác vụ con (Sub-tasks)
* **Sub-task S3.1: Chuyển đổi Peer Rules sang Pod Selectors**
  - Rà soát tệp `gitops/infrastructure/network-policy-staged/32-product-reviews.yaml`.
  - Thay thế các quy tắc peer ClusterIP `/32` bằng `podSelector` cho các dịch vụ nội bộ: `product-catalog:8080`, `flagd:8013`, và `otel-gateway:4317`.
* **Sub-task S3.2: Xác nhận quy tắc truy cập CSDL RDS PostgreSQL**
  - Giữ nguyên và xác nhận 3 dải CIDR `/20` private subnet của RDS trên cổng `5432` được cấu hình chính xác.

---

## TICKET S4: Văn Bản Hóa Kiến Trúc Guardrail & Tối Giản IAM Role Policy
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Epic:** AIE1 - CDO Audit Promotion Unblocker
* **Ưu tiên:** Medium (P2)
* **Label Jira:** `iam-policy`, `compliance`, `guardrails`

### Mô tả công việc (Description)
Làm rõ với CDO về quyết định sử dụng Guardrail ở Tầng Ứng dụng (Application-level Evaluator) và đảm bảo IAM Role tuân thủ nguyên tắc quyền tối thiểu (Least Privilege).

### Các tác vụ con (Sub-tasks)
* **Sub-task S4.1: Văn bản hóa quyết định sử dụng App-level Evaluator**
  - Soạn thảo tài liệu xác nhận kiến trúc: Khẳng định ứng dụng `product-reviews` sử dụng bộ lọc an toàn và fidelity evaluator tự phát triển ở tầng ứng dụng (App-level Evaluator), không cần tích hợp AWS Bedrock Guardrail (`shopping-copilot-guardrail`).
* **Sub-task S4.2: Tối giản và chốt IAM Inline Policy**
  - Kiểm tra IAM Inline Policy `techx-tf3/product-reviews-bedrock`: Giữ nguyên policy tối giản, chỉ cho phép `bedrock:InvokeModel` đối với 2 mô hình Nova Lite và Nova Micro tại `us-east-1`.
  - Đảm bảo không cấp thừa quyền `bedrock:ApplyGuardrail` hay `bedrock:Converse` không cần thiết.

---

## TICKET S5: Chạy Validation & Thu Thập Bằng Chứng Promotion (Promo Evidence)
* **Người thực hiện (Assignee):** Khoa (Leader)
* **Epic:** AIE1 - CDO Audit Promotion Unblocker
* **Ưu tiên:** High (P0)
* **Label Jira:** `qa`, `validation`, `argo-cd`, `promo-evidence`

### Mô tả công việc (Description)
Thực hiện chạy toàn bộ quy trình kiểm thử và thu thập đầy đủ 6 hạng mục bằng chứng (Evidence) theo yêu cầu của CDO để xin duyệt promote `NetworkPolicy` từ `network-policy-staged/` lên Production.

### Các tác vụ con (Sub-tasks)
* **Sub-task S5.1: Kiểm tra Helm Lint & CI**
  - Chạy `helm lint` và `helm template` thành công với tệp `values-aio-llm.yaml`.
* **Sub-task S5.2: Kiểm tra trạng thái Argo CD & Pod Readiness**
  - Xác nhận Argo CD báo trạng thái `Synced` & `Healthy`. Dịch vụ `product-reviews` duy trì trạng thái Ready, không bị lỗi restart regression.
* **Sub-task S5.3: Thử nghiệm luồng Traffic Được Phép (Allowed Flows)**
  - Chạy test kiểm chứng kết nối thành công tới: DNS, `product-catalog`, `flagd`, `otel-gateway`, RDS PostgreSQL, STS và Bedrock Runtime.
* **Sub-task S5.4: Thử nghiệm luồng Traffic Bị Cấm (Denied Flows)**
  - Kiểm tra chặn thành công traffic tới dịch vụ `payment`, các service không liên quan, và traffic ra Internet ngoài whitelist.
* **Sub-task S5.5: Đổi tên & Promote NetworkPolicy**
  - Xác nhận K8s `PolicyEndpoint` khớp 100% với policy được promote.
  - Theo dõi luồng trải nghiệm khách hàng (browse & product-review) hoạt động ổn định trong suốt cửa sổ theo dõi (Soak Window).
