# ĐỒNG GÓP DANH MỤC BACKLOG - NHÓM AI (HƯỚNG AIE & AIOPS)

Dưới đây là danh mục backlog chi tiết kết hợp cả hai trụ **AI Engine (AIE)** và **AIOps CMDR Engine** trong Phase 3, được rà soát theo các khía cạnh ưu tiên kinh doanh, rủi ro vận hành và ảnh hưởng đến trụ Security/Reliability/Cost.

---

## 1. Phương pháp tính điểm ưu tiên

### 📊 Hướng AI Engine (AIE)
Mỗi nhiệm vụ AIE được đánh giá theo thang điểm từ 1 đến 5 cho 4 tiêu chí:
- Tác động Business (Business Impact)
- Rủi ro bảo mật / vận hành (Risk)
- Khả năng hoàn thành trong thời gian ngắn (Speed / Feasibility)
- Giá trị nền tảng / mở đường cho các task sau (Foundation Value)

$$\text{Priority Score}_{\text{AIE}} = \text{Business Impact} + \text{Risk} + \text{Foundation Value} + \text{Feasibility}$$
*(Điểm từ 4 đến 20. Điểm càng cao => ưu tiên càng cao)*

### 🛠️ Hướng AIOps CMDR Engine (AIOps)
Các nhiệm vụ AIOps được xếp hạng ưu tiên nghiêm ngặt theo công thức rủi ro nhân tác động:
$$\text{Priority Score}_{\text{AIOps}} = \text{Risk (Probability} \times \text{Severity)} \times \text{Business Impact}$$
Trong đó, mỗi tiêu chí được đánh giá theo thang điểm từ 1 đến 5:
- **Probability (Khả năng xảy ra)**: Xác suất sự cố xảy ra hoặc tần suất sử dụng (1 = Rất thấp, 5 = Rất cao).
- **Severity (Mức nghiêm trọng)**: Mức độ nguy hại đối với hệ thống nếu không thực hiện (1 = Rất thấp, 5 = Cực kỳ nghiêm trọng).
- **Business Impact (Tác động Business)**: Ảnh hưởng trực tiếp tới cam kết SLO, doanh thu và chi phí (1 = Rất thấp, 5 = Rất cao).

*(Điểm từ 1 đến 125. Điểm từ 75 trở lên là Tối ưu tiên)*

---

## 2. Danh mục Backlog chi tiết - Hướng AI Engine (AIE)

### 1) Task AIE-01: Xây dựng Module gRPC Client tích hợp cho Shopping Copilot
- **Mô tả:** Thiết kế và triển khai gRPC client kết nối trực tiếp tới các service nội bộ của TechX Corp, đặc biệt ProductCatalogService và CartService, để làm nền tảng cho các tool của agent.
- **Mức độ ưu tiên:** Cao
- **Priority Score:** 17/20
- **Tác động Business:** Cho phép agent tương tác thật với hệ thống sản phẩm và giỏ hàng, thay vì dùng mockup.
- **Rủi ro:** Thấp đến trung bình; chủ yếu là lỗi kết nối, schema mismatch hoặc timeout.
- **Phạm vi:**
  - Implement client stub cho ProductCatalogService
  - Implement client stub cho CartService
  - Xử lý retry / timeout / error mapping
  - Chuẩn hóa response để tool có thể dùng được
- **Điều kiện hoàn thành:**
  - Có thể gọi thành công các RPC core từ module Shopping Copilot
  - Có test integration cơ bản
  - Có log và error handling rõ ràng
- **Metrics:**
  - Connection success rate
  - RPC latency p95
  - Tool execution success rate
- **Trụ chấm điểm:** Security: trung bình, Reliability: cao, Customer Experience: cao

### 2) Task AIE-02: Lập trình Logic Định tuyến Intent và Cơ chế Tool-calling
- **Mô tả:** Xây dựng engine xử lý intent cho Shopping Copilot bằng LLM hoặc prompt-based routing, cho phép agent phân tích câu hỏi khách hàng, trích xuất tham số và chọn tool phù hợp như SearchProducts, GetProductReviews, GetCart.
- **Mức độ ưu tiên:** Cao
- **Priority Score:** 16/20
- **Tác động Business:** Tăng độ chính xác của trải nghiệm RAG và cải thiện tỷ lệ khách hàng tìm thấy sản phẩm phù hợp, từ đó tăng khả năng đưa vào giỏ hàng.
- **Rủi ro:** Trung bình; rủi ro chính là intent misclassification hoặc tool selection sai.
- **Phạm vi:**
  - Xây dựng prompt/logic routing
  - Chọn tool đúng theo intent
  - Trích xuất tham số đầu vào
  - Bọc output sao cho có thể dùng tiếp cho câu trả lời grounded
- **Điều kiện hoàn thành:**
  - Đạt độ chính xác trên bộ test intent mẫu
  - Hỗ trợ ít nhất 3 intent core: tìm sản phẩm, hỏi review, xem giỏ hàng
  - Có fallback khi tool không rõ hoặc không tìm thấy kết quả
- **Metrics:**
  - Task-success Eval Rate
  - Intent accuracy
  - Tool-call success rate
- **Trụ chấm điểm:** Customer Experience: cao, Reliability: trung bình

### 3) Task AIE-03: Triển khai Cổng bảo vệ Excessive-Agency và Confirmation Gate cho Giỏ hàng
- **Mô tả:** Triển khai middleware/guardrail chặn hành vi AI tự ý thực hiện thao tác ghi dữ liệu như thêm vào giỏ, xóa giỏ, checkout, hoặc các thao tác có rủi ro tài chính. Khi cần thực hiện hành động ghi, frontend sẽ hiển thị nút xác nhận và chỉ thực thi sau khi nhận token confirm hợp lệ.
- **Mức độ ưu tiên:** Tối khẩn cấp
- **Priority Score:** 20/20
- **Tác động Business:** Bảo vệ luồng thanh toán và giỏ hàng — khu vực có ảnh hưởng trực tiếp tới doanh thu và trải nghiệm khách hàng.
- **Rủi ro:** Rất cao nếu không có guardrail; có thể gây hành vi không mong muốn hoặc thao tác sai trên hệ thống thật.
- **Phạm vi:**
  - Implement input filter / prompt injection guard
  - Implement confirmation gate bằng HMAC token
  - Chặn các action bị cấm tuyệt đối: EmptyCart, PlaceOrder, Charge
  - Kết nối với frontend để hiển thị UI confirmation
- **Điều kiện hoàn thành:**
  - AI không thể tự ý gọi action ghi không có xác nhận
  - Tất cả hành động ghi phải đi qua confirmation flow
  - Có test cho deny/pending/approve cases
- **Metrics:**
  - Blocked unsafe actions rate
  - Confirmation success rate
  - Security incident count (should be zero)
- **Trụ chấm điểm:** Security: cực cao, Reliability: cực cao, Customer Trust: cao

---

## 3. Danh mục Backlog chi tiết - Hướng AIOps CMDR Engine

### 1) Task AIOps-01: Phát hiện Anomaly & Cảnh báo Burn-rate SLO
- **Mô tả**: Thiết lập bộ lọc PromQL kép tính toán SLO Burn-rate (Short/Long windows) và Z-score của metrics (CPU, Memory, Kafka lag) chạy dự phòng song song với Alertmanager.
- **Mức độ ưu tiên**: Tối ưu tiên
- **Priority Score**: 100/125 (Probability: 4, Severity: 5, Business Impact: 5)
- **Tác động Business**: Tránh vi phạm cam kết SLO hạ tầng, bảo vệ doanh thu cửa hàng trực tuyến.
- **Rủi ro**: Lỗi mất dấu sự cố lớn nếu hệ thống giám sát thô sập.
- **Phạm vi**:
  - Viết truy vấn PromQL đo lường Latency & Saturation.
  - Cấu hình cơ chế cảnh báo dự phòng độc lập.
- **Điều kiện hoàn thành**:
  - Nhận diện chính xác 100% các đỉnh Latency từ Prometheus.
  - Tự động chuyển vùng cảnh báo thô khi Engine bị gián đoạn.
- **Metrics**: SLO violation detection rate (100%), False Negative rate (0%).

### 2) Task AIOps-02: Định vị Nguyên nhân gốc Graph-based RCA
- **Mô tả**: Xây dựng giải thuật duyệt đồ thị Jaeger Trace Spans từ đỉnh lỗi (Frontend-proxy) đi sâu dần theo các quan hệ cha-con để tìm nút lá sâu nhất bị lỗi (Culprit service).
- **Mức độ ưu tiên**: Cao
- **Priority Score**: 64/125 (Probability: 4, Severity: 4, Business Impact: 4)
- **Tác động Business**: Giảm thời gian mò lỗi thủ công của kỹ sư hệ thống từ 30 phút xuống còn 1 giây.
- **Rủi ro**: Chẩn đoán sai dịch vụ gây lỗi dây chuyền kéo theo toàn hệ thống sập.
- **Phạm vi**:
  - Tích hợp API kết nối Jaeger Query.
  - Viết giải thuật đệ quy duyệt DAG trace spans.
- **Điều kiện hoàn thành**:
  - Định vị chính xác microservice gây lỗi gốc trong INC-1, INC-2, INC-3.
- **Metrics**: RCA Accuracy (>95%).

### 3) Task AIOps-03: Đóng gói Bằng chứng & Phân cụm Logs (Drain3)
- **Mô tả**: Thu thập logs và traces có liên quan từ OpenSearch, chạy qua thuật toán Drain3 để lọc bỏ các tham số động (IDs, IPs, timestamps) và gom log thành các cụm template cô đọng gửi cho AI.
- **Mức độ ưu tiên**: Cao
- **Priority Score**: 60/125 (Probability: 5, Severity: 3, Business Impact: 4)
- **Tác động Business**: Giảm 80% chi phí sử dụng API LLM Bedrock, tăng tốc độ suy luận lỗi.
- **Rủi ro**: Spam log làm tràn bộ nhớ LLM context và tăng chi phí token vô ích.
- **Phạm vi**:
  - Kết nối API OpenSearch thu thập logs.
  - Cấu hình và huấn luyện trực tiếp bộ khai thác Drain3.
- **Điều kiện hoàn thành**:
  - Gom hàng ngàn dòng log thô thành tối đa 5-10 dòng template đại diện.
- **Metrics**: Log compression ratio (>90%), Token usage reduction (>80%).

### 4) Task AIOps-04: Khung an toàn CMDR Safety Gate & Dry-run
- **Mô tả**: Thiết lập cơ chế kiểm duyệt hành động dựa trên whitelist (scale, restart, cache-flush) và chặn đứng hoàn toàn các lệnh phá hủy như xóa dữ liệu hoặc restart pod single-replica (như INC-2). Chạy lệnh bằng `--dry-run=server` trước khi thực thi thật.
- **Mức độ ưu tiên**: Tối ưu tiên
- **Priority Score**: 75/125 (Probability: 3, Severity: 5, Business Impact: 5)
- **Tác động Business**: Tránh mất mát dữ liệu giỏ hàng của người dùng, giữ uy tín thương hiệu.
- **Rủi ro**: Tự động hóa phá hoại cụm EKS do LLM chẩn đoán sai.
- **Phạm vi**:
  - Viết bộ lọc Safety Gate so khớp whitelist hành động.
  - Thực thi dry-run K8s API kiểm tra RBAC.
- **Điều kiện hoàn thành**:
  - Chặn đứng 100% lệnh nguy hiểm ngoài whitelist.
  - Chặn đứng lệnh restart đối với INC-2.
- **Metrics**: Hệ số an toàn (Safety rate = 100%), Không xảy ra sự cố sập cụm do tự sửa lỗi.

### 5) Task AIOps-05: Container hóa & Deploy Engine EKS
- **Mô tả**: Đóng gói AIOps Engine vào Docker container, đẩy lên AWS ECR và deploy lên cụm EKS của dự án với ServiceAccount giới hạn quyền truy cập thông qua RoleBinding.
- **Mức độ ưu tiên**: Cao
- **Priority Score**: 48/125 (Probability: 3, Severity: 4, Business Impact: 4)
- **Tác động Business**: Tự động hóa vận hành 24/7, không phụ thuộc vào máy local.
- **Rủi ro**: Lộ thông tin quản trị hoặc Pod bị chiếm quyền điều khiển cụm.
- **Phạm vi**:
  - Viết Dockerfile tối ưu hóa dung lượng image.
  - Viết manifests Kubernetes Deployment, ServiceAccount.
- **Điều kiện hoàn thành**:
  - Engine chạy ổn định trên EKS và kết nối được với các IP nội bộ của Jaeger/Prometheus/OpenSearch.
- **Metrics**: Pod uptime (99.9%).

### 6) Task AIOps-06: Tương tác Slack & Approval Gate (ALB Ingress)
- **Mô tả**: Xây dựng card tin nhắn Block Kit chứa nút duyệt/từ chối (Approve/Reject) và thiết lập AWS ALB Ingress/ngrok tunnel để chuyển tiếp callback từ Slack API về Pod trong EKS.
- **Mức độ ưu tiên**: Tối ưu tiên
- **Priority Score**: 80/125 (Probability: 4, Severity: 4, Business Impact: 5)
- **Tác động Business**: Đáp ứng cam kết an toàn vận hành ở hợp đồng C6 (Human-in-the-loop).
- **Rủi ro**: Thực thi hành động sai lầm mà không có sự kiểm soát của SRE.
- **Phạm vi**:
  - Thiết kế UI Slack Card tương tác.
  - Xây dựng HTTP POST callback endpoint trong FastAPI.
  - Cấu hình AWS Load Balancer tiếp nhận request công khai từ Slack.
- **Điều kiện hoàn thành**:
  - Card hiển thị đầy đủ RCA, Log template và lệnh đề xuất.
  - Click nút trên Slack kích hoạt lệnh sửa lỗi thật trên cụm K8s.
- **Metrics**: MTTR (Giảm từ hàng giờ xuống <30 giây), User approval latency.

### 7) Task AIOps-07: Lọc bất thường liên tiếp 5 chu kỳ quét
- **Mô tả**: Nâng cấp module dò quét để chỉ kích hoạt luồng CMDR khi chỉ số Z-score hoặc Burn-rate vượt ngưỡng liên tục trong 5 chu kỳ quét (5 cycles) thay vì báo ngay lập tức.
- **Mức độ ưu tiên**: Cao
- **Priority Score**: 45/125 (Probability: 5, Severity: 3, Business Impact: 3)
- **Tác động Business**: Loại bỏ Alert Fatigue (SRE bị quá tải bởi hàng loạt tin nhắn rác).
- **Rủi ro**: Xảy ra hiện tượng báo động giả do nhiễu tức thời.
- **Phạm vi**:
  - Thiết lập sliding window lưu trữ lịch sử 5 lần quét gần nhất.
- **Điều kiện hoàn thành**:
  - Bỏ qua toàn bộ các đỉnh đột biến đơn lẻ (Transient Spikes) dưới 5 phút.
- **Metrics**: Tỷ lệ báo động giả (False Positive Rate < 5%).

### 8) Task AIOps-08: Thuật toán tính toán Blast Radius (Jaeger DAG)
- **Mô tả**: Triển khai giải thuật duyệt ngược từ dịch vụ bị tác động lên các nhánh phụ thuộc để ước lượng "Bán kính ảnh hưởng" (Blast Radius) của hành động khắc phục trước khi chạy.
- **Mức độ ưu tiên**: Trung bình
- **Priority Score**: 32/125 (Probability: 2, Severity: 4, Business Impact: 4)
- **Tác động Business**: Bảo vệ độ sẵn sàng của các luồng kinh doanh xung quanh khu vực sự cố.
- **Rủi ro**: Lệnh sửa lỗi kéo sập các service lành mạnh kế cận.
- **Phạm vi**:
  - Viết logic so khớp độ sâu ảnh hưởng dựa trên đồ thị quan hệ microservices.
- **Điều kiện hoàn thành**:
  - Tính toán chính xác số lượng dịch vụ bị ảnh hưởng gián tiếp nếu một service bị tác động.
- **Metrics**: Remediation safety score.

---

## 4. Đề xuất phân bổ thực hiện theo tuần

### 📅 Tuần 1: Thiết lập nền tảng & Các chốt chặn khẩn cấp
- **Hướng AIE**: Task AIE-01 (gRPC Client) + Task AIE-03 (Confirmation Gate giỏ hàng).
- **Hướng AIOps**: Task AIOps-01 (Phát hiện Burn-rate) + Task AIOps-04 (Safety Gate & dry-run) + Task AIOps-02 (RCA Engine) + Task AIOps-03 (Logs clustering Drain3).

### 📅 Tuần 2: Hoàn thiện logic & Triển khai tự động hóa EKS
- **Hướng AIE**: Task AIE-02 (Logic routing & Tool-calling).
- **Hướng AIOps**: Task AIOps-05 (Deploy Engine EKS) + Task AIOps-06 (Webhook Slack ALB Ingress) + Task AIOps-07 (Lọc 5-cycles) + Task AIOps-08 (Tính toán Blast Radius).

### 📅 Tuần 3: Tối ưu hóa, Đánh giá chất lượng & Củng cố hệ thống
- Tuning tham số, đo đạc độ trễ p95, đánh giá độ chính xác (Accuracy) của cả Shopping Copilot và AIOps Engine trước khi nghiệm thu.

---

## 5. Ghi chú đóng góp chiến lược cho Hội đồng duyệt

Sự kết hợp đồng bộ giữa **AIE** và **AIOps** giúp dự án đạt được các cam kết mục tiêu:
1. **Trải nghiệm khách hàng tối ưu (AIE)**: Copilot tương tác thời gian thực, có xác nhận an toàn trước khi thay đổi trạng thái giỏ hàng.
2. **Độ tin cậy hạ tầng tuyệt đối (AIOps)**: Nhận dạng, cô lập lỗi dây chuyền bằng đồ thị trace Jaeger và khắc phục sự cố trong vòng dưới 30 giây với chốt duyệt an toàn của con người (Human-in-the-loop).
3. **Hiệu quả kinh tế (FinOps)**: Lọc log rác bằng Drain3 giảm thiểu 80% kích thước context và chi phí gọi LLM API.