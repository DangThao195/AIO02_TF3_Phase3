# Postmortem: Sự cố nghẽn kết nối và sập luồng Checkout do cấu hình sai NetworkPolicy

**Mã sự cố:** INC-20260716-CHECKOUT-OUTAGE  
**Độ nghiêm trọng:** SEV-1 (Critical)  
**Thời gian bắt đầu:** 16/07/2026 11:44 (GMT+7)  
**Thời gian khắc phục:** 16/07/2026 14:20 (GMT+7)  
**Tổng thời gian gián đoạn (Downtime):** 2 giờ 36 phút  
**Tác giả:** Trương Công Tú (CDO02 Platform Team)  

---

## 1. Tóm tắt Sự cố (Summary)
Vào lúc **11:44 GMT+7 ngày 16/07/2026**, hệ thống storefront TechX Corp gặp sự cố nghiêm trọng khiến khách hàng không thể thực hiện thanh toán (Checkout), giao diện trả về lỗi `HTTP 500`. Song song đó, hệ thống giám sát tự động bằng AI (`aiops-engine`) liên tục bị khởi động lại (`CrashLoopBackOff`) và hệ thống logs tập trung trên OpenSearch ngừng nhận dữ liệu log mới.

Nguyên nhân được xác định là do đợt áp dụng thủ công các NetworkPolicy bảo mật mới lúc **11:43** bị cấu hình thiếu: chặn kết nối từ `opentelemetry-collector` đến OpenSearch. Điều này làm nghẽn hàng đợi xuất dữ liệu của OTel Collector, gián tiếp làm treo luồng log đồng bộ của service `currency` (C++), dẫn tới luồng `checkout` bị timeout khi gọi `currency` và tự đánh dấu mình là không sẵn sàng (`NOT_SERVING`).

Sự cố được khắc phục triệt để vào lúc **14:20** sau khi các NetworkPolicy được cập nhật chính xác và đồng bộ hóa thông qua GitOps/ArgoCD tại PR #155.

---

## 2. Gây ảnh hưởng (Impact)
* **Khách hàng**: 
  * Giao dịch mua hàng bị gián đoạn hoàn toàn. Tỷ lệ checkout thành công giảm về **0%**.
  * Khách hàng nhận lỗi `HTTP 500 / gRPC Code 13 Internal` kèm thông báo `failed to convert price` hoặc `shipping quote failure`.
* **Hệ thống**:
  * **Dịch vụ Checkout**: 2 pod của `checkout-rollout` lần lượt thất bại Readiness Probe, bị gỡ khỏi Endpoint Service, dẫn tới mất tính sẵn sàng dịch vụ.
  * **Hệ thống AI Ops (`aiops-engine`)**: Bị liveness probe kill liên tục vì không thể gọi API Prometheus để quét metrics.
  * **Hệ thống Observability (`otel-collector`)**: Bị nghẽn hàng đợi xuất dữ liệu (Export queue), dẫn đến mất hoàn toàn khả năng thu thập log/trace thời gian thực của toàn bộ cluster.

---

## 3. Dòng thời gian Sự cố (Timeline)
* **11:43 GMT+7**: Nhóm Security (CDO01) áp dụng thủ công 4 NetworkPolicy mới (`prometheus-access`, `jaeger-access`, `opensearch-access`, `loadgen-deny-ingress`) trực tiếp dưới cluster để thắt chặt bảo mật.
* **11:44 GMT+7**: **[BẮT ĐẦU SỰ CỐ]**
  * Pod `aiops-engine` chuyển sang `Ready: False` do bị chặn kết nối tới Prometheus.
  * OTel Collector bắt đầu bị timeout khi đẩy logs tới OpenSearch.
  * Cổng `4317` gRPC của collector bị nghẽn, làm đóng băng service `currency` (C++).
  * Luồng `checkout` gọi `currency` bị timeout (`DeadlineExceeded`) và tự chuyển sang `NOT_SERVING`.
* **13:48 GMT+7**: Hệ thống frontend liên tục in lỗi ghi nhận HTTP 500 khi gọi dịch vụ shipping/currency.
* **14:03 GMT+7**: Team CDO02 bắt đầu điều tra kết nối, khởi tạo pod `grpc-probe` để chẩn đoán gRPC dưới cluster.
* **14:08 GMT+7**: Nhóm vận hành AI phát hiện `aiops-engine` bị sập và chạy lệnh vá tay (patch) `prometheus-access` dưới cluster để cứu pod AI. Pod AI chạy lại nhưng luồng checkout vẫn bị sập.
* **14:12 GMT+7**: **[PHÁT HIỆN NGUYÊN NHÂN GỐC]** 
  * Phát hiện OTel Collector bị timeout khi gọi OpenSearch (do NetworkPolicy chặn).
  * Xác định cơ chế treo dây chuyền: OTel Collector bị nghẽn $\rightarrow$ Block cổng 4317 $\rightarrow$ Treo luồng log của service `currency` (C++) $\rightarrow$ `checkout` gọi `currency` bị timeout.
* **14:15 GMT+7**: Thực hiện tạo nhánh Git `fix/observability-network-policies`, viết lại 4 file NetworkPolicy chuẩn và mở PR #155 để sửa lỗi.
* **14:18 GMT+7**: PR #155 được phê duyệt và merge vào nhánh `main`.
* **14:19 GMT+7**: Kích hoạt đồng bộ hóa thủ công trên ArgoCD (`techx-infrastructure-app`) để đẩy cấu hình chuẩn xuống cluster.
* **14:20 GMT+7**: **[KHẮC PHỤC]** Cấu hình mới được áp dụng. OTel Collector thông suốt kết nối, giải phóng nghẽn. Service `currency` và `checkout` tự phục hồi về trạng thái `1/1 Ready`. Storefront hoạt động bình thường trở lại.

---

## 4. Phân tích Nguyên nhân gốc rễ (Root Cause Analysis)

### 4.1. Phân tích Kỹ thuật
Sự cố xảy ra do sự kết hợp của ba yếu tố cấu hình sai trong NetworkPolicy và cơ chế logging đồng bộ của service:

1. **Thiếu sót trong thiết lập NetworkPolicy**:
   * Cấu hình `opensearch-access` được áp dụng chỉ cho phép kết nối từ `fluent-bit`, `grafana`, và `jaeger` tới OpenSearch, nhưng **bỏ quên** `opentelemetry-collector` (DaemonSet `otel-collector-agent`).
   * Cấu hình `prometheus-access` ban đầu chỉ cho phép `grafana`, chặn kết nối từ `aiops-engine`.
   * Cấu hình `jaeger-access` chỉ mở cổng ingest dữ liệu, quên mở cổng truy vấn `16686` / `16685`.
2. **Cơ chế treo dây chuyền (Cascading Failure)**:
   * Do OTel Collector không thể đẩy logs về OpenSearch $\rightarrow$ Hàng đợi (buffer) của collector đầy $\rightarrow$ Cổng nhận log `4317` gRPC của collector phản hồi cực chậm/block.
   * Service `currency` (viết bằng C++) sử dụng thư viện logging OpenTelemetry với cơ chế đồng bộ (synchronous write). Khi gọi hàm `logger->Info()` để ghi log, luồng xử lý bị khóa cứng để đợi OTel Collector phản hồi $\rightarrow$ Treo toàn bộ luồng xử lý gRPC của dịch vụ `currency`.
   * Dịch vụ `checkout` gọi `currency` để quy đổi tiền tệ sản phẩm $\rightarrow$ Chờ quá hạn 5s $\rightarrow$ Báo lỗi `DEADLINE_EXCEEDED` $\rightarrow$ Thất bại Readiness Probe.

```
[NetworkPolicy chặn OpenSearch]
            │
            ▼
[OTel Collector nghẽn queue]
            │
            ▼
[Cổng gRPC 4317 của Collector bị block]
            │
            ▼
[Logger của Currency (C++) bị treo đồng bộ]
            │
            ▼
[gRPC Currency/Convert bị timeout]
            │
            ▼
[Checkout dependency check thất bại (NOT_SERVING)]
            │
            ▼
[Sập luồng Checkout (HTTP 500)]
```

### 4.2. Lỗi Quy trình
* **Thao tác thủ công trực tiếp (Manual Intervention)**: Các NetworkPolicy mới được apply trực tiếp dưới cluster bằng lệnh `kubectl apply` mà không qua GitOps (ArgoCD), dẫn đến thiếu quy trình review code và test tự động trước khi triển khai.

---

## 5. Giải pháp Khắc phục đã Thực hiện (Resolution Actions)
Chúng ta đã chuyển đổi hoàn toàn việc quản lý 4 NetworkPolicy này về quy trình GitOps/ArgoCD chuẩn tại PR #155:
1. **Đưa các file vào Git**: Đưa 4 cấu hình NetworkPolicy bị thiếu vào thư mục `gitops/infrastructure/`.
2. **Sửa đổi cấu hình chính xác**:
   * **`opensearch-access`**: Thêm `opentelemetry-collector` (DaemonSet `otel-collector-agent`, label `app.kubernetes.io/name: opentelemetry-collector`) và `aiops-engine` vào danh sách Ingress Allowlist ở port 9200.
   * **`prometheus-access`**: Thêm `aiops-engine` (label `app: aiops-engine`) vào Ingress Allowlist ở port 9090.
   * **`jaeger-access`**: Thêm port `16686` (HTTP Query) và `16685` (gRPC Query) cho phép `grafana` và `aiops-engine` truy xuất traces.
3. **Đồng bộ hóa tự động**: ArgoCD đồng bộ hóa các tài nguyên này xuống cluster, tự động gắn tracking-id để quản lý cấu hình tập trung.

---

## 6. Giải pháp Phòng ngừa (Action Items & Preventative Measures)

| STT | Hành động cụ thể | Trách nhiệm | Trạng thái |
| :--- | :--- | :--- | :--- |
| 1 | **Khóa quyền can thiệp thủ công (No Manual Apply)**: Thu hồi quyền `write/patch` NetworkPolicy trực tiếp của các tài khoản IAM cá nhân dưới cluster. Bắt buộc mọi thay đổi hạ tầng đi qua PR GitOps. | CDO01 (Security) | Chưa thực hiện |
| 2 | **Cấu hình Asynchronous Logging cho Workloads**: Cập nhật OTel SDK của các service stateless (đặc biệt là C++ `currency`) sang chế độ bất tuần tự / không chặn (Asynchronous / Non-blocking) và thiết lập drop logs khi buffer đầy để tránh treo luồng xử lý chính khi collector nghẽn. | CDO02 (Reliability) | Chưa thực hiện |
| 3 | **Tự động hóa kiểm tra NetworkPolicy trong CI**: Viết script test kết nối tự động (Smoke test connection matrix) chạy trong CI/CD. Khi có thay đổi NetworkPolicy, CI sẽ chạy verify luồng kết nối chính trước khi cho phép merge. | CDO02 / CDO01 | Chưa thực hiện |
