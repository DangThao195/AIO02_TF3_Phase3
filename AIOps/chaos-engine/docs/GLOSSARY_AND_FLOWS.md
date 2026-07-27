# CẨM NANG THUẬT NGỮ, KIẾN THỨC VÀ LUỒNG VẬN HÀNH AIOPS - TF3

Tài liệu này giải thích chi tiết toàn bộ các khái niệm chuyên môn, thuật ngữ kỹ thuật, nền tảng kiến thức và luồng xử lý dữ liệu đầu-cuối (End-to-End Flow) trong hệ thống **AIOps Engine (TF3)**.

---

## I. Giải Thích Các Thuật Ngữ & Kiến Thức Cốt Lõi

### 1. Tầng Giám Sát & Chỉ Số (Observability & SLO)
*   **Telemetry (Viễn đo):** Tập hợp 3 trụ cột dữ liệu giám sát gồm:
    *   **Metrics:** Các chỉ số đo lường dạng số theo thời gian (ví dụ: RAM sử dụng, số lượng request/giây). thu thập qua Prometheus.
    *   **Logs:** Nhật ký hoạt động chi tiết dạng văn bản do ứng dụng in ra, thu thập qua OpenSearch.
    *   **Traces:** Vết cuộc gọi hành trình của một request đi qua các microservice, thu thập qua Jaeger.
*   **SLI (Service Level Indicator):** Chỉ số mức độ dịch vụ thực tế (ví dụ: tỷ lệ request thành công thực tế của checkout).
*   **SLO (Service Level Objective):** Mục tiêu mức độ dịch vụ cam kết (ví dụ: tỷ lệ checkout thành công phải $\ge 99\%$).
*   **Error Budget (Quỹ lỗi):** Lượng lỗi tối đa mà hệ thống được phép gặp phải trong một khoảng thời gian mà không bị coi là vi phạm cam kết với khách hàng. 
    *   *Ví dụ:* Nếu SLO là $99\%$, Quỹ lỗi được phép là $1\%$ lượng requests.
*   **Burn-rate (Tốc độ đốt quỹ lỗi):** Tốc độ tiêu thụ Quỹ lỗi. Burn-rate = 1 tức là hệ thống sẽ tiêu thụ hết quỹ lỗi vừa vặn trong thời gian cam kết (ví dụ: 30 ngày). Burn-rate = 14.4 tức là quỹ lỗi sẽ bị đốt sạch chỉ trong vòng 1 giờ rưỡi nếu lỗi tiếp diễn.
*   **Multi-window Multi-burn-rate:** Cơ chế phát hiện lỗi sử dụng hai cửa sổ thời gian trượt song song (cửa sổ ngắn 5m để phản ứng nhanh, cửa sổ dài 1h để kiểm chứng tính bền bỉ). Điều này giúp loại bỏ hoàn toàn các báo động giả (false alarm) gây ra bởi các đỉnh lỗi tức thời.

### 2. Tầng Phát Hiện & Gom Nhóm Bất Thường (Detection & Correlation)
*   **Z-Score (Điểm chuẩn hóa):** Số độ lệch chuẩn mà một điểm dữ liệu lệch so với giá trị trung bình. Công thức: $Z = \frac{x - \mu}{\sigma}$. 
*   **Robust Z-Score (Dùng Median và MAD):** Thay vì dùng trung bình ($\mu$) và độ lệch chuẩn ($\sigma$) dễ bị ảnh hưởng bởi các giá trị ngoại lai cực đoan, Robust Z-Score sử dụng Trung vị (Median) và Độ lệch tuyệt đối trung vị (MAD - Median Absolute Deviation) để tính toán ngưỡng động ổn định hơn.
*   **Isolation Forest (Rừng cô lập):** Thuật toán học máy không giám sát chuyên dùng để phát hiện bất thường. Thuật toán này phân tách các điểm dữ liệu bằng cách dựng các cây quyết định ngẫu nhiên. Những điểm bất thường sẽ bị cô lập rất nhanh (nằm ở các nhánh nông gần gốc của cây).
*   **Feature Engineering (Kỹ nghệ đặc trưng):** Việc tạo ra các cột dữ liệu mới từ dữ liệu thô để tăng độ nhạy cho AI. Trong dự án, chúng ta biến 1 dòng metric thô thành **6 đặc trưng**:
    1.  *Value:* Giá trị hiện tại.
    2.  *Rolling Mean:* Giá trị trung bình trượt (xu hướng dài hạn).
    3.  *Rolling Std:* Độ biến động trượt (độ nhiễu).
    4.  *Rate-of-Change:* Tốc độ tăng/giảm so với điểm trước đó (gia tốc).
    5.  *Lag-1:* Giá trị tại thời điểm $t-1$.
    6.  *Lag-k:* Giá trị tại thời điểm $t-k$ (so sánh chu kỳ dài).
*   **Drain3 (Log Clustening):** Thuật toán phân cụm log trực tuyến sử dụng cấu trúc cây phân cấp để nhóm các log thô có chung định dạng lại thành các "Template" (ví dụ: `Connect to DB failed: {error}` thay vì lưu hàng nghìn dòng log có IP khác nhau).
*   **Dedup & Fingerprint:** Đóng dấu vân tay duy nhất cho mỗi cảnh báo dựa trên `{service, sli, rule}` để loại bỏ các cảnh báo lặp lại, chống tràn kênh chat.
*   **Topology Correlation (Gom nhóm theo đồ thị):** Kết nối các cảnh báo dựa trên sơ đồ vật lý/kiến trúc các dịch vụ để gộp các cảnh báo liên đới thành một sự cố duy nhất (Incident).

### 3. Tầng Chẩn Đoán Nguyên Nhân Gốc (Root Cause Analysis - RCA)
*   **Jaeger Spans & Trace ID:** Mỗi request của người dùng có một `Trace ID` duy nhất. Hành trình đi qua mỗi dịch vụ được ghi nhận là một `Span`.
*   **Call Tree (Cây cuộc gọi):** Đồ thị dạng cây biểu diễn thứ tự gọi nhau giữa các microservices (ví dụ: `Frontend` gọi `Checkout`, `Checkout` gọi `Payment`).
*   **Leaf-most Error Node (Nút lỗi lá sâu nhất):** Trong cây cuộc gọi, đây là dịch vụ nằm sâu nhất ở cuối nhánh bị trả lỗi đỏ (5xx). Nó chính là nơi bắt đầu phát sinh lỗi (nguyên nhân gốc - Culprit).
*   **Retry Storm (Bão thử lại):** Khi dịch vụ phía sau bị chậm hoặc lỗi, dịch vụ phía trước liên tục thực hiện cơ chế thử lại (retry) tự động. Bão retry này làm quá tải tài nguyên của dịch vụ trung gian, tạo ra nhiều lỗi giả (noise) che lấp đi lỗi thật ở dịch vụ cuối cùng.
*   **RAG (Retrieval-Augmented Generation):** Kỹ thuật truy xuất thông tin từ tài liệu có sẵn (ví dụ: lịch sử sự cố `INCIDENT_HISTORY.md`) để nạp vào prompt làm tri thức cho mô hình AI, giúp AI trả lời chính xác, tránh bịa đặt.

### 4. Tầng Khắc Phục & Lưới An Toàn (Remediation & Safety)
*   **Safety Gate (Cổng an toàn):** Bộ lọc kiểm tra tính hợp lệ của lệnh vá lỗi trước khi chạy, chặn đứng các lệnh hủy diệt hệ thống hoặc can thiệp vào cờ lỗi của BTC.
*   **Dry-run:** Chạy thử lệnh ở chế độ giả lập (server-side dry-run) để kiểm tra cú pháp và quyền hạn RBAC của Kubernetes trước khi thực thi thật.
*   **Blast Radius (Bán kính ảnh hưởng):** Số lượng dịch vụ bị ảnh hưởng hoặc liên quan trực tiếp đến sự cố.
*   **Auto-Rollback (Tự động hoàn tác):** Lệnh tự động chạy để khôi phục lại trạng thái cũ của hạ tầng nếu sau khi vá lỗi mà SLO vẫn vỡ hoặc không thể verify được hệ thống (telemetry bị mất).

---

## II. Luồng Vận Hành Đi Của Dữ Liệu (End-to-End Flow)

Dưới đây là chi tiết luồng xử lý tự động của hệ thống khi có sự cố phát sinh:

```
[Thời gian]   [Hành động hệ thống]                              [Nhật ký hoạt động (Audit Trail)]
   T = 0s     BTC bật cờ lỗi paymentFailure ở flagd             System healthy -> Unhealthy
   T = 30s    Prometheus ghi nhận rớt SLO Checkout              Burn-rate SLO breach detected
   T = 35s    Engine gom alert Checkout & Payment thành 1       Incident created (Topology correlation)
   T = 40s    Engine phân tích trace Jaeger                     Culprit identified: product-catalog
   T = 50s    Engine quét OpenSearch và gom cụm log lỗi         Drain3 generated error templates
   T = 60s    AI Bedrock chẩn đoán lỗi dựa trên lịch sử         RAG diagnosis: Postgres pool exhaustion
   T = 65s    Engine đánh giá rủi ro của lệnh vá lỗi            assess_risk -> Low/Medium/High
              
   [Nếu Risk = Low]
   T = 70s    Engine tự động chạy K8s command (scale deploy)    AUTO_APPROVED -> Executed (dry-run pass)
              
   [Nếu Risk = Medium]
   T = 70s    Engine gửi card Block Kit lên Slack               Status: PENDING_APPROVAL
   T = 90s    SRE click nút "Approve" trên Slack                APPROVED by @username -> Executed
              
   T = 100s   Engine kích hoạt verify loop trong 5 phút         Verify Loop started (polls every 30s)
   
   [Kịch bản 1: SLO phục hồi (xanh trở lại)]
   T = 160s   Chỉ số lỗi giảm xuống <1%                         VERIFIED: success -> Incident Closed
   
   [Kịch bản 2: SLO vẫn vỡ sau 5 phút (Hoặc Telemetry bị sập)]
   T = 400s   Hết 5 phút verify, lỗi vẫn còn                    VERIFY FAILED -> Auto-rollback triggered
   T = 410s   Engine tự động chạy rollback command              SYSTEM_ROLLED_BACK to original state
```

### Chi tiết các bước trong luồng:

1.  **Phát hiện bất thường (Detection):** Các cảm biến quét chỉ số SLI liên tục mỗi 30 giây. Khi cờ lỗi `paymentFailure` được bật, dịch vụ sẽ bị nghẽn DB connection, SLO Checkout bị vỡ ngay lập tức. Cả hai cửa sổ trượt 5m và 1h của Burn-rate SLO đồng thời vượt ngưỡng $14.4 \rightarrow$ Kích hoạt trạng thái báo động đỏ.
2.  **Gom nhóm & Lọc nhiễu (Correlation):** Nhiều cảnh báo rác từ `payment-service` (do bão retry) và cảnh báo từ `checkout` phát sinh. Bộ gom nhóm topology tính toán khoảng cách hops trên đồ thị và gộp chung toàn bộ thành một Incident duy nhất để tránh spam kênh chat.
3.  **Lập hồ sơ bằng chứng (Evidence Gathering):**
    *   Engine gọi Jaeger để lấy Trace ID lỗi, duyệt đồ thị cuộc gọi tìm ra culprit thực sự là `product-catalog` (nút lá lỗi sâu nhất).
    *   Gọi OpenSearch lấy log lỗi của `product-catalog` trong khoảng thời gian xảy ra lỗi $\pm 30$ giây, chạy qua thuật toán Drain3 để lọc sạch tham số động, bóc tách ra dòng log lỗi: `connection pool connection checkout timeout`.
    *   Tự động đóng gói tất cả vào file `evidence-pack.md`.
4.  **Chẩn đoán bằng AI (LLM Diagnosis):** Engine gửi hồ sơ bằng chứng cho AWS Bedrock. Bedrock đối chiếu dữ liệu log lỗi với lịch sử `INCIDENT_HISTORY.md` và đưa ra kết luận: *"Đây là sự cố cạn kiệt Connection Pool của Database giống sự cố INC-1. Đề xuất hành động khắc phục: scale-up replicas của product-catalog."*
5.  **Phân tích Rủi ro & Thực thi (Risk & Execute):**
    *   Hành động scale-up dịch vụ `product-catalog` (không thuộc Tier-1, có tính idempotent cao) được chấm điểm `Risk = Low` $\rightarrow$ Engine tự động duyệt (`auto_execute`) và gửi lệnh scale trực tiếp đến Kubernetes API (qua dry-run an toàn).
    *   Nếu hành động là restart một dịch vụ Tier-1 $\rightarrow$ chấm điểm `Risk = Medium` $\rightarrow$ bắn card Slack chờ SRE nhấn nút Approve.
6.  **Xác minh & Rollback:** 
    *   Sau khi scale-up, Engine theo dõi Prometheus liên tục. 
    *   Nếu lỗi được sửa $\rightarrow$ Đóng sự cố.
    *   Nếu cờ lỗi của BTC vẫn bật (lỗi dai dẳng không tự hết) $\rightarrow$ SLO vẫn vỡ sau 5 phút $\rightarrow$ Engine tự động chạy lệnh rollback trả số lượng pod về ban đầu để bảo vệ tài nguyên hạ tầng.
