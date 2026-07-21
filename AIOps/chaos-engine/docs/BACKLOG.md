# AIOps CMDR Engine - Priority Backlog (TF3 / Nhóm AIO02)

Tài liệu quản lý tiến độ và xếp hạng ưu tiên các hạng mục công việc của mảng **AIOps CMDR Engine (Trụ Ops/Reliability - Nhóm AIO02)**.

Các hạng mục được xếp hạng ưu tiên nghiêm ngặt theo công thức chuẩn:
$$\text{Priority Score} = \text{Risk (Probability} \times \text{Severity)} \times \text{Business Impact}$$

Trong đó, mỗi tiêu chí được đánh giá theo thang điểm từ 1 đến 5:
- **Probability (Khả năng xảy ra)**: Xác suất sự cố xảy ra hoặc nhu cầu sử dụng (1 = Rất thấp, 5 = Rất cao).
- **Severity (Mức nghiêm trọng)**: Mức độ nguy hại đối với hạ tầng nếu không thực hiện (1 = Rất thấp, 5 = Cực kỳ nghiêm trọng).
- **Business Impact (Tác động Business)**: Ảnh hưởng trực tiếp tới SLO, doanh thu và chi phí (1 = Rất thấp, 5 = Rất cao).

*Thang điểm Priority Score (1 - 125):*
- **75 - 125**: Tối ưu tiên
- **40 - 74**: Cao
- **20 - 39**: Trung bình
- **1 - 19**: Thấp

---

## 📋 Danh sách Backlog Ưu Tiên AIOps

| Mã Task | Hạng mục công việc | Probability (1-5) | Severity (1-5) | Business Impact (1-5) | Priority Score | Mức ưu tiên | Tuần thực hiện |
|---|---|:---:|:---:|:---:|:---:|---|---|
| **AIOps-01** | **Phát hiện Anomaly & Burn-rate SLO** | 4 | 5 | 5 | **100** / 125 | Tối ưu tiên | Tuần 1 |
| **AIOps-06** | **Tương tác Slack & Approval Gate (ALB Ingress)** | 4 | 4 | 5 | **80** / 125 | Tối ưu tiên | Tuần 1 - Tuần 2 |
| **AIOps-04** | **Khung an toàn CMDR Safety Gate & Dry-run** | 3 | 5 | 5 | **75** / 125 | Tối ưu tiên | Tuần 1 |
| **AIOps-02** | **Định vị Nguyên nhân gốc Graph-based RCA** | 4 | 4 | 4 | **64** / 125 | Cao | Tuần 1 |
| **AIOps-03** | **Đóng gói Bằng chứng & Phân cụm Logs (Drain3)** | 5 | 3 | 4 | **60** / 125 | Cao | Tuần 1 |
| **AIOps-05** | **Container hóa & Deploy Engine EKS** | 3 | 4 | 4 | **48** / 125 | Cao | Tuần 2 |
| **AIOps-07** | **Lọc bất thường liên tiếp 5 chu kỳ quét** | 5 | 3 | 3 | **45** / 125 | Cao | Tuần 2 |
| **AIOps-08** | **Thuật toán tính toán Blast Radius (Jaeger DAG)** | 2 | 4 | 4 | **32** / 125 | Trung bình | Tuần 2 |

---

## 🛠️ Chi tiết từng hạng mục công việc AIOps

### 1) Task AIOps-01: Phát hiện Anomaly & Cảnh báo Burn-rate SLO
- **Mô tả**: Thiết lập bộ lọc PromQL kép tính toán SLO Burn-rate (Short/Long windows) và Z-score của metrics (CPU, Memory, Kafka lag) chạy dự phòng song song với Alertmanager.
- **Rủi ro**: Lỗi mất dấu sự cố lớn nếu hệ thống giám sát thô sập (Xác suất: 4, Nghiêm trọng: 5).
- **Tác động Business**: Tránh vi phạm cam kết SLO hạ tầng, bảo vệ doanh thu cửa hàng trực tuyến.
- **Phạm vi thực hiện**:
  - Viết truy vấn PromQL đo lường Latency & Saturation.
  - Cấu hình cơ chế cảnh báo dự phòng độc lập.
- **Điều kiện hoàn thành**:
  - Nhận diện chính xác 100% các đỉnh Latency từ Prometheus.
  - Tự động chuyển vùng cảnh báo thô khi Engine bị gián đoạn.
- **Metrics đo lường**: SLO violation detection rate ($100\%$), False Negative rate ($0\%$).

### 2) Task AIOps-06: Tương tác Slack & Approval Gate (ALB Ingress)
- **Mô tả**: Xây dựng card tin nhắn Block Kit chứa nút duyệt/từ chối (Approve/Reject) và thiết lập AWS ALB Ingress/ngrok tunnel để chuyển tiếp callback từ Slack API về Pod trong EKS.
- **Rủi ro**: Thực thi hành động sai lầm mà không có sự kiểm soát của SRE (Xác suất: 4, Nghiêm trọng: 4).
- **Tác động Business**: Đáp ứng cam kết an toàn vận hành ở hợp đồng C6 (Human-in-the-loop).
- **Phạm vi thực hiện**:
  - Thiết kế UI Slack Card tương tác.
  - Xây dựng HTTP POST callback endpoint trong FastAPI.
  - Cấu hình AWS Load Balancer tiếp nhận request công khai từ Slack.
- **Điều kiện hoàn thành**:
  - Card hiển thị đầy đủ RCA, Log template và lệnh đề xuất.
  - Click nút trên Slack kích hoạt lệnh sửa lỗi thật trên cụm K8s.
- **Metrics đo lường**: MTTR (Giảm từ hàng giờ xuống <30 giây), User approval latency.

### 3) Task AIOps-04: Khung an toàn CMDR Safety Gate & Dry-run
- **Mô tả**: Thiết lập cơ chế kiểm duyệt hành động dựa trên whitelist (scale, restart, cache-flush) và chặn đứng hoàn toàn các lệnh phá hủy như xóa dữ liệu hoặc restart pod single-replica (như INC-2). Chạy lệnh bằng `--dry-run=server` trước khi thực thi thật.
- **Rủi ro**: Tự động hóa phá hoại cụm EKS do LLM chẩn đoán sai (Xác suất: 3, Nghiêm trọng: 5).
- **Tác động Business**: Tránh mất mát dữ liệu giỏ hàng của người dùng, giữ uy tín thương hiệu.
- **Phạm vi thực hiện**:
  - Viết bộ lọc Safety Gate so khớp whitelist hành động.
  - Thực thi dry-run K8s API kiểm tra RBAC.
- **Điều kiện hoàn thành**:
  - Chặn đứng 100% lệnh nguy hiểm ngoài whitelist.
  - Chặn đứng lệnh restart đối với INC-2.
- **Metrics đo lường**: Hệ số an toàn (Safety rate = $100\%$), Không xảy ra sự cố sập cụm do tự sửa lỗi.

### 4) Task AIOps-02: Định vị Nguyên nhân gốc Graph-based RCA
- **Mô tả**: Xây dựng giải thuật duyệt đồ thị Jaeger Trace Spans từ đỉnh lỗi (Frontend-proxy) đi sâu dần theo các quan hệ cha-con để tìm nút lá sâu nhất bị lỗi (Culprit service).
- **Rủi ro**: Chẩn đoán sai dịch vụ gây lỗi dây chuyền kéo theo toàn hệ thống sập (Xác suất: 4, Nghiêm trọng: 4).
- **Tác động Business**: Giảm thời gian mò lỗi thủ công của kỹ sư hệ thống từ 30 phút xuống còn 1 giây.
- **Phạm vi thực hiện**:
  - Tích hợp API kết nối Jaeger Query.
  - Viết giải thuật đệ quy duyệt DAG trace spans.
- **Điều kiện hoàn thành**:
  - Định vị chính xác microservice gây lỗi gốc trong INC-1, INC-2, INC-3.
- **Metrics đo lường**: RCA Accuracy ($>95\%$).

### 5) Task AIOps-03: Đóng gói Bằng chứng & Phân cụm Logs (Drain3)
- **Mô tả**: Thu thập logs và traces có liên quan từ OpenSearch, chạy qua thuật toán Drain3 để lọc bỏ các tham số động (IDs, IPs, timestamps) và gom log thành các cụm template cô đọng gửi cho AI.
- **Rủi ro**: Spam log làm tràn bộ nhớ LLM context và tăng chi phí token vô ích (Xác suất: 5, Nghiêm trọng: 3).
- **Tác động Business**: Giảm 80% chi phí sử dụng API LLM Bedrock, tăng tốc độ suy luận lỗi.
- **Phạm vi thực hiện**:
  - Kết nối API OpenSearch thu thập logs.
  - Cấu hình và huấn luyện trực tiếp bộ khai thác Drain3.
- **Điều kiện hoàn thành**:
  - Gom hàng ngàn dòng log thô thành tối đa 5-10 dòng template đại diện.
- **Metrics đo lường**: Log compression ratio ($>90\%$), Token usage reduction ($>80\%$).

### 6) Task AIOps-05: Container hóa & Deploy Engine EKS
- **Mô tả**: Đóng gói AIOps Engine vào Docker container, đẩy lên AWS ECR và deploy lên cụm EKS của dự án với ServiceAccount giới hạn quyền truy cập thông qua RoleBinding.
- **Rủi ro**: Lộ thông tin quản trị hoặc Pod bị chiếm quyền điều khiển cụm (Xác suất: 3, Nghiêm trọng: 4).
- **Tác động Business**: Tự động hóa vận hành 24/7, không phụ thuộc vào máy local.
- **Phạm vi thực hiện**:
  - Viết Dockerfile tối ưu hóa dung lượng image.
  - Viết manifests Kubernetes Deployment, ServiceAccount.
- **Điều kiện hoàn thành**:
  - Engine chạy ổn định trên EKS và kết nối được với các IP nội bộ của Jaeger/Prometheus/OpenSearch.
- **Metrics đo lường**: Pod uptime ($99.9\%$).

### 7) Task AIOps-07: Lọc bất thường liên tiếp 5 chu kỳ quét
- **Mô tả**: Nâng cấp module dò quét để chỉ kích hoạt luồng CMDR khi chỉ số Z-score hoặc Burn-rate vượt ngưỡng liên tục trong 5 chu kỳ quét (5 cycles) thay vì báo ngay lập tức.
- **Rủi ro**: Xảy ra hiện tượng báo động giả do nhiễu tức thời (Xác suất: 5, Nghiêm trọng: 3).
- **Tác động Business**: Loại bỏ Alert Fatigue (SRE bị quá tải bởi hàng loạt tin nhắn rác).
- **Phạm vi thực hiện**:
  - Thiết lập sliding window lưu trữ lịch sử 5 lần quét gần nhất.
- **Điều kiện hoàn thành**:
  - Bỏ qua toàn bộ các đỉnh đột biến đơn lẻ (Transient Spikes) dưới 5 phút.
- **Metrics đo lường**: Tỷ lệ báo động giả (False Positive Rate < $5\%$).

### 8) Task AIOps-08: Thuật toán tính toán Blast Radius (Jaeger DAG)
- **Mô tả**: Triển khai giải thuật duyệt ngược từ dịch vụ bị tác động lên các nhánh phụ thuộc để ước lượng "Bán kính ảnh hưởng" (Blast Radius) của hành động khắc phục trước khi chạy.
- **Rủi ro**: Lệnh sửa lỗi kéo sập các service lành mạnh kế cận (Xác suất: 2, Nghiêm trọng: 4).
- **Tác động Business**: Bảo vệ độ sẵn sàng của các luồng kinh doanh xung quanh khu vực sự cố.
- **Phạm vi thực hiện**:
  - Viết logic so khớp độ sâu ảnh hưởng dựa trên đồ thị quan hệ microservices.
- **Điều kiện hoàn thành**:
  - Tính toán chính xác số lượng dịch vụ bị ảnh hưởng gián tiếp nếu một service bị tác động.
- **Metrics đo lường**: Remediation safety score.
