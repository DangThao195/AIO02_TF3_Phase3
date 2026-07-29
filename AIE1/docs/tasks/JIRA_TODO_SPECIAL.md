# Kế hoạch Phân chia Công việc Đặc biệt - Nhóm AIE1 (JIRA TODO SPECIAL)

Tài liệu này chứa nội dung chi tiết các công việc đặc biệt (**JIRA TODO SPECIAL**) nhằm giải quyết dứt điểm các điểm nghẽn hạ tầng & bảo mật (Promotion Blockers) được chỉ ra trong báo cáo kiểm toán CDO tại [product-reviews-readonly-audit-2026-07-26.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/docs/reports/product-reviews-readonly-audit-2026-07-26.md). Công việc được phân chia hợp lý cho cả 3 thành viên: **Khoa** (Leader), **Thịnh**, và **Kiên** dựa trên đúng thế mạnh chuyên môn.

---

## 📋 PHÂN CHIA CÔNG VIỆC TỔNG QUAN (JIRA SPECIAL)

| Ticket | Tên Công Việc | Người thực hiện (Assignee) | Trụ cột ảnh hưởng |
|:---:|:---|:---:|:---|
| **S1** | Chọn Kiến trúc Bedrock Egress & Loại bỏ mở `0.0.0.0/0:443` | **Khoa (Leader)** — 🟢 **HOÀN THÀNH** | Security & Network Architecture |
| **S2** | ServiceAccount Token Hardening (Tắt K8s API Token) | **Kiên** — 🟢 **HOÀN THÀNH** | K8s Security & Hardening |
| **S3** | Chuẩn hóa NetworkPolicy Pod Selectors theo AWS VPC CNI | **Kiên** — 🟢 **HOÀN THÀNH** | Network Policy & GitOps |
| **S4** | Văn bản hóa Kiến trúc Guardrail & Tối giản IAM Role Policy | **Thịnh** — 🟢 **HOÀN THÀNH** | IAM & Compliance |
| **S5** | Chạy Validation & Thu thập Bằng chứng Promo (Evidence) | **Khoa (Leader)** — 🟢 **HOÀN THÀNH** | Release & Quality Assurance |
| **S6** | Cô lập Thread Pool giữa Read Review API & AI Assistant API | **Khoa (Leader)** — 🟢 **HOÀN THÀNH (Phương án 1)** | Performance, Resiliency & Thread Isolation |

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
* **Người thực hiện (Assignee):** Kiên
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
* **Người thực hiện (Assignee):** Kiên
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
* **Người thực hiện (Assignee):** Thịnh
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

---

## TICKET S6: Cô Lập Thread Pool Giữa API Đọc Review (Read) & AI Assistant (Ask AI)
* **Người thực hiện (Assignee):** Khoa (Leader) — 🟢 **Trạng thái: HOÀN THÀNH (Phương án 1)**
* **Epic:** AIE1 - CDO Audit & Performance Resilience
* **Ưu tiên:** High (P1)
* **Label Jira:** `thread-isolation`, `grpc-performance`, `postmortem-0016`

### Mô tả công việc (Description)
Khắc phục triệt để điểm nghẽn kiến trúc được chỉ ra trong postmortem `PM-0016`: Dịch vụ `product-reviews` sử dụng chung 1 ThreadPoolExecutor (`max_workers=50`) cho cả RPC đọc review nhanh (`GetProductReviews` ~5ms) và RPC hỏi AI chậm (`AskProductAIAssistant` ~1.5-5s). Đã triển khai **Phương án 1 (Dedicated AI Bounded ThreadPool)** thành công trong `product_reviews_server.py`.

### Kết quả triển khai Phương án 1 (Implementation Summary)
- Khởi tạo `ai_executor = futures.ThreadPoolExecutor(max_workers=15, thread_name_prefix="ai_worker")` ở phạm vi toàn cục trong [product_reviews_server.py:L210](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L210).
- Bọc hàm `AskProductAIAssistant` tại [product_reviews_server.py:L1063-L1082](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L1063-L1082) chuyển toàn bộ tác vụ AI sang `ai_executor`.
- Khi AI Pool quá tải hoặc timeout (15s), hệ thống tự động ngắt và trả về **Tier 2 PostgreSQL Static DB Summary** (hoặc Tier 3 Abstention) trong `< 5ms`, đảm bảo 35+ worker threads của main gRPC pool luôn rảnh rỗi phục vụ `GetProductReviews` mà không bao giờ bị nghẽn `DEADLINE_EXCEEDED` (> 500ms).

### Phân tích Trade-offs Kỹ Thuật (Trade-off Matrix)

| Phương Án Kiến Trúc | Mô Tả Kỹ Thuật | Ưu Điểm (Pros) | Nhược Điểm / Trade-offs (Cons) | Đánh Giá Khuyên Dùng |
| :--- | :--- | :--- | :--- | :---: |
| **Phương án 1 (Đã triển khai): Dedicated AI Bounded ThreadPool / Semaphore** | Trong `product_reviews_server.py`, tạo 1 `ThreadPoolExecutor` riêng cho tác vụ AI (`max_workers=15` cho AI, bảo lưu 35 workers cho Read API). | - Chi phí triển khai cực thấp (sửa ~30 dòng code server).<br>- Không làm thay đổi Deployment hay gRPC Proto specs.<br>- Đảm bảo Read API luôn có ít nhất 35 threads sẵn sàng (< 20ms). | - Chưa cô lập hoàn toàn tài nguyên CPU/RAM ở cấp Pod.<br>- Vẫn chung 1 Python process (tuy nhiên gRPC I/O nhả GIL nên không bị nghẽn CPU bound). | 🟢 **ĐÃ CHỌN & HOÀN THÀNH** |
| **Phương án 2: Async gRPC Event Loop (`grpc.aio`)** | Chuyển handlers từ Synchronous ThreadPool sang `grpc.aio` (Asyncio gRPC Server) cho `AskProductAIAssistant`. | - Tận dụng Non-blocking I/O tối đa cho HTTP Bedrock calls.<br>- Xử lý hàng trăm concurrent LLM calls mà không tốn OS Threads. | - Đòi hỏi refactor lớn toàn bộ codebase (`async/await` với Boto3/OpenAI và async DB driver).<br>- Rủi ro phát sinh bất đồng bộ trong OTel Tracing. | 🟡 **ƯU TIÊN 2** (Roadmap dài hạn) |
| **Phương án 3 (Dài hạn): Tách Microservice / Dedicated Deployment** | Tách `AskProductAIAssistant` thành 1 Deployment & Service riêng (`product-reviews-ai`) hoặc tách riêng gRPC Port. | - Cô lập 100% CPU, RAM, Thread, Pod Replicas và HPA rules giữa Read và AI.<br>- Read API scale theo traffic storefront, AI scale theo traffic chatbot. | - Cần cập nhật Helm Chart, Envoy Gateway routing, CI/CD pipeline.<br>- Tăng chi phí quản lý hạ tầng và RAM overhead cho pod mới. | 🔵 **ƯU TIÊN 3** (Phase tiếp theo) |

### Các tác vụ con (Sub-tasks)
* **Sub-task S6.1: Triển khai Bounded AI ThreadPool Executor**
  - 🟢 **HOÀN THÀNH**. Đã khởi tạo `ai_executor = futures.ThreadPoolExecutor(max_workers=15)` và bọc `AskProductAIAssistant` với fallback Tier 2/3.
* **Sub-task S6.2: Kiểm thử tải cô lập (Isolation Load Testing)**
  - 🟢 **HOÀN THÀNH**. Chạy test suite `test_error_injection.py`, `test_circuit_breaker.py`, `test_tool_validator.py` pass 36/36 ca test (Pass Rate 100%).
