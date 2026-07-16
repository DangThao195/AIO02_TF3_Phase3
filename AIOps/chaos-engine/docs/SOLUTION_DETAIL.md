# Chi Tiết Giải Pháp Kỹ Thuật AIOps - TF3 Engine

Tài liệu này mô tả chi tiết phương pháp, thuật toán và giải pháp kỹ thuật mà nhóm **TF3** đang sử dụng để xử lý bài toán AIOps (Phát hiện, Chẩn đoán và Tự động khắc phục sự cố). 

Các giải pháp được đánh giá mức độ ưu tiên và rủi ro theo công thức chuẩn của Backlog:
$$\text{Priority Score} = \text{Risk (Probability} \times \text{Severity)} \times \text{Business Impact}$$

---

## 📋 Bảng Tổng Quan Các Giải Pháp AIOps

| Mã Giải Pháp | Tên Giải Pháp Kỹ Thuật | Probability (1-5) | Severity (1-5) | Business Impact (1-5) | Priority Score | Mức ưu tiên | Trạng thái triển khai |
|---|---|:---:|:---:|:---:|:---:|---|---|
| **SOL-01** | **Giám sát Burn-rate SLO & Ngưỡng Động Z-Score** | 4 | 5 | 5 | **100** / 125 | Tối ưu tiên | **Đang hoạt động** |
| **SOL-02** | **Gom nhóm Alert dựa trên Graph Topology** | 4 | 4 | 5 | **80** / 125 | Tối ưu tiên | **Đang hoạt động** |
| **SOL-03** | **Định vị lỗi gốc Jaeger Graph-based RCA** | 3 | 5 | 5 | **75** / 125 | Tối ưu tiên | **Đang hoạt động** |
| **SOL-04** | **Phân cụm Logs Drain3 & Evidence Pack** | 4 | 4 | 4 | **64** / 125 | Cao | **Đang hoạt động** |
| **SOL-05** | **AI Diagnostic Engine & Bedrock Gateway** | 3 | 4 | 4 | **48** / 125 | Cao | **Đang hoạt động** |
| **SOL-06** | **Auto-remediation & Safety Approval Gate** | 3 | 3 | 4 | **36** / 125 | Trung bình | **Đang hoạt động** |

---

## 🛠️ Chi Tiết Kỹ Thuật Từng Giải Pháp

### 1) SOL-01: Giám sát Burn-rate SLO & Ngưỡng Động Z-Score (Detection Layer)
- **Mô tả giải thuật**:
  - **Burn-rate SLO**: Sử dụng cơ chế Multi-window Multi-burn-rate (theo Google SRE). Thiết lập bộ lọc PromQL kép quét song song hai cửa sổ: 5 phút (ngắn - phản ứng nhanh) và 1 giờ (dài - tránh cảnh báo giả). Chỉ kích hoạt cảnh báo `critical` khi cả hai cửa sổ đều vi phạm với Burn-rate $\ge 14.4$.
  - **Z-Score động**: Tính toán ngưỡng động cho các metrics hạ tầng (CPU, RAM, DB Connections) dựa trên giá trị trung bình ($\mu$) và độ lệch chuẩn ($\sigma$) trượt trong 7 ngày: $Z_t = \frac{x_t - \mu_{7d}}{\sigma_{7d}}$. Cảnh báo `warning` khi $|Z| > 3.0$ liên tục trong 5 chu kỳ quét.
- **Rủi ro hạ tầng**: Lỗi mất dấu sự cố lớn nếu hệ thống Prometheus bị sập hoặc nghẽn mạng (Xác suất: 4, Nghiêm trọng: 5).
- **Tác động Business**: Phát hiện sớm sự cố giao dịch (SLO availability) trước khi khách hàng phàn nàn, bảo vệ trực tiếp doanh thu.
- **Phạm vi triển khai thực tế**: Viết các câu truy vấn PromQL tích hợp trực tiếp vào module giám sát của AI Engine và thiết lập Alertmanager làm dự phòng (Redundancy).
- **Điều kiện hoàn thành**: Phát hiện chính xác 100% các vụ rớt SLO giao dịch trong môi trường kiểm thử.
- **Metrics đo lường**: Tỷ lệ phát hiện lỗi thật (Target: $100\%$), Tỷ lệ báo động giả (Target: $<5\%$).

### 2) SOL-02: Gom nhóm Alert dựa trên Graph Topology (Correlation Layer)
- **Mô tả giải thuật**: 
  - Khử trùng lặp (Dedup) bằng cách băm (hashing) thông tin cảnh báo thành một vân tay độc nhất `{service, sli, rule}`. Bỏ qua các cảnh báo trùng lặp trong 15 phút.
  - Sử dụng bản đồ kiến trúc dịch vụ (Dependency Graph) để tính toán mối quan hệ giữa các dịch vụ. Nếu nhiều alert xảy ra đồng thời trong vòng 2-5 phút và các dịch vụ tương ứng cách nhau $\le 2$ bước nhảy (hops) trên đồ thị, Engine tự động gộp chúng thành một Incident duy nhất.
- **Rủi ro hạ tầng**: Gom nhóm sai khiến nhiều lỗi độc lập bị gộp lại làm một, gây nhiễu cho người trực (Xác suất: 4, Nghiêm trọng: 4).
- **Tác động Business**: Giải quyết triệt để tình trạng "bão cảnh báo" (Alert Fatigue), giúp SRE tập trung vào 1 vấn đề cốt lõi thay vì bị ngập trong hàng chục thông báo Slack.
- **Phạm vi triển khai thực tế**: Triển khai module `alert_correlator.py` kết nối trực tiếp với bản đồ topology tĩnh của hệ thống.
- **Điều kiện hoàn thành**: Gộp thành công 10 cảnh báo đơn lẻ phát sinh trong đợt quét tấn công mạng thành đúng 1 Incident.
- **Metrics đo lường**: Tỷ lệ giảm nhiễu cảnh báo (Alert Volume Reduction $>80\%$).

### 3) SOL-03: Định vị lỗi gốc Jaeger Graph-based RCA (RCA Layer)
- **Mô tả giải thuật**:
  - Khi Incident được kích hoạt, Engine tự động gọi API Jaeger để lấy thông tin các vết gọi (Trace Spans) bị lỗi.
  - Xây dựng đồ thị cây cuộc gọi (Call Tree) từ điểm đầu vào (Frontend-proxy).
  - Áp dụng giải thuật duyệt đồ thị đệ quy để đi tìm nút lá bị lỗi sâu nhất (leaf-most error node) - nơi phát sinh mã lỗi HTTP 5xx đầu tiên. Nút này được xác định là nguyên nhân gốc (Culprit Service).
- **Rủi ro hạ tầng**: Jaeger bị mất mát spans (due to sampling rate) làm giải thuật duyệt đồ thị bị đứt quãng không tìm thấy gốc (Xác suất: 3, Nghiêm trọng: 5).
- **Tác động Business**: Giảm thời gian tìm kiếm thủ công nguồn phát sinh lỗi của kỹ sư từ hàng giờ xuống còn 1 giây.
- **Phạm vi triển khai thực tế**: Module `rca_engine.py` gọi trực tiếp API Jaeger Query và xử lý JSON Spans.
- **Điều kiện hoàn thành**: Xác định đúng 100% culprit service cho các sự cố kinh điển (như `payment-service` trong sự cố pool DB).
- **Metrics đo lường**: Độ chính xác định vị lỗi gốc (Target $>95\%$).

### 4) SOL-04: Phân cụm Logs Drain3 & Evidence Pack (Log & Evidence)
- **Mô tả giải thuật**:
  - Quét logs của Culprit Service từ OpenSearch trong cửa sổ thời gian sự cố ($\pm 30s$).
  - Sử dụng thuật toán phân cụm log **Drain3** để bóc tách các tham số động (IP, ID, timestamp) biến log thô thành các template mẫu.
  - Gom các log có cùng template và tính toán tần suất xuất hiện, chỉ gửi 5-10 template đại diện nhất kèm theo link Grafana panel và Trace IDs lỗi vào một tệp `evidence-pack.md` đóng gói.
- **Rủi ro hạ tầng**: Quá tải log thô khiến thuật toán Drain3 bị nghẽn RAM (Xác suất: 4, Nghiêm trọng: 4).
- **Tác động Business**: Giảm 90% lượng text thô gửi cho LLM, tiết kiệm chi phí token và tăng tốc độ phản hồi của AI.
- **Phạm vi triển khai thực tế**: Tích hợp thư viện Drain3 Python vào module `evidence_collector.py` và kết nối OpenSearch.
- **Điều kiện hoàn thành**: Xuất ra tệp `evidence-pack.md` đầy đủ thông tin trong vòng 30 phút từ lúc sự cố mở.
- **Metrics đo lường**: Tỷ lệ nén log (Log compression ratio $>90\%$).

### 5) SOL-05: AI Diagnostic Engine & Bedrock Gateway (AI Layer)
- **Mô tả giải thuật**:
  - Tích hợp cổng kết nối bảo mật đến AWS Bedrock (sử dụng model Claude 3.5 Sonnet hoặc tương tự).
  - Sử dụng kỹ thuật In-Context Learning: Nạp cấu trúc hệ thống và tệp lịch sử sự cố `INCIDENT_HISTORY.md` vào prompt.
  - Kết hợp giải thuật so khớp từ khóa (`INCIDENT_PATTERNS`) để so sánh sự cố hiện tại với thư viện lịch sử lỗi, đưa ra dự đoán nguyên nhân và khuyến nghị Runbook xử lý tối ưu.
- **Rủi ro hạ tầng**: API của LLM Provider bị timeout hoặc trả về kết quả mơ hồ (hallucination) (Xác suất: 3, Nghiêm trọng: 4).
- **Tác động Business**: Tận dụng trí tuệ nhân tạo để chẩn đoán lỗi tức thời như một chuyên gia SRE lão luyện.
- **Phạm vi triển khai thực tế**: Viết module `llm_diagnostician.py` tích hợp AWS SDK (boto3) kết nối Bedrock.
- **Điều kiện hoàn thành**: Đưa ra gợi ý sửa lỗi chính xác trùng khớp với Runbook chuẩn.
- **Metrics đo lường**: Độ trễ gọi AI (Target $<2s$), Độ chính xác chẩn đoán của AI (Target $>90\%$).

### 6) SOL-06: Auto-remediation & Safety Approval Gate (Remediation Layer)
- **Mô tả giải thuật**:
  - Đề xuất kịch bản vá lỗi (ví dụ: `scale` deployment lên thêm replica) gửi lên Slack thông qua Block Kit.
  - Khi SRE click nút "Approve", API FastAPI tiếp nhận callback định danh chính xác ID của người nhấn nút (Human-in-the-loop).
  - Kiểm tra lệnh qua Whitelist (Safety Gate), chặn đứng hoàn toàn các lệnh phá hoại (như xóa namespace, restart pod đơn lẻ...).
  - Thực thi lệnh an toàn bằng `shlex` và chạy bất đồng bộ. Sau khi chạy, kiểm tra lại Prometheus trong 5 phút; nếu không hồi phục, tự động thực hiện **Rollback** về trạng thái ban đầu.
- **Rủi ro hạ tầng**: Lệnh thực thi bị lỗi hoặc rollback không thành công gây sập hệ thống (Xác suất: 3, Nghiêm trọng: 3).
- **Tác động Business**: Đảm bảo an toàn vận hành, loại bỏ hoàn toàn khả năng AI tự ý chạy lệnh phá hủy cụm EKS.
- **Phạm vi triển khai thực tế**: Module `remediation_handler.py` sử dụng Kubernetes Python Client để thao tác trên cụm.
- **Điều kiện hoàn thành**: Thực thi scale deploy thành công và rollback hoạt động tốt khi giả lập kiểm thử thất bại.
- **Metrics đo lường**: Hệ số an toàn (Safety Rate = $100\%$, không có lệnh nguy hiểm lọt qua).
