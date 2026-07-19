# ADR-002: Lựa Chọn Baseline Và Ngưỡng Phát Hiện Sự Cố Đa Tầng (Busy vs Broken)

- **Trạng thái**: Approved
- **Ngày quyết định**: 17/07/2026
- **Tác giả**: Hảo (Leader team AIOps)

---

## 1. Bối cảnh (Context)

Một hệ thống giám sát sự cố (AIOps Engine) chỉ hữu ích khi nó bắt đúng lỗi thật và không báo động giả khi hệ thống chỉ đang bận (High traffic nhưng healthy). Ngoài ra, hệ thống phải chịu được hiện tượng **Masking** — khi một đợt tăng tải cực lớn (nhiễu) che mờ đi một lỗi nhỏ âm ỉ kéo dài bên dưới.

Để đạt được mục tiêu này, chúng tôi cần thiết lập một kiến trúc baseline động kết hợp giữa **giám sát SLO Burn Rate (tầng phản ứng)** và **mô hình Isolation Forest đa chiều (tầng chủ động)**.

---

## 2. Quyết định thiết kế (Decisions)

### 2.1. Lựa chọn Ngưỡng K = 14.4 cho SLO Burn Rate (Tầng Phản ứng)
Chúng tôi áp dụng công thức Multi-window Multi-service Burn Rate cho ngân sách lỗi (Error Budget) với mục tiêu SLO khả dụng là $99.9\%$ (tỷ lệ lỗi tối đa $0.1\%$).
* **Tại sao chọn K = 14.4?**
  * Tốc độ tiêu thụ (Burn Rate) bằng 1.0 nghĩa là hệ thống sẽ tiêu thụ hết 100% ngân sách lỗi trong đúng 30 ngày.
  * Với $K = 14.4$, hệ thống sẽ tiêu hao sạch 100% ngân sách lỗi trong vòng:
    $$t = \frac{30 \text{ ngày} \times 24 \text{ giờ} \times 60 \text{ phút}}{14.4} \approx 50 \text{ phút}$$
  * Đây là ngưỡng tối ưu được khuyến nghị bởi Google SRE để gửi cảnh báo khẩn cấp (PagerDuty/Slack) vì lỗi này đe dọa trực tiếp đến tính ổn định của hệ thống trong chưa đầy 1 giờ.
* **Cơ chế chống báo động giả (Multi-Window):**
  * Chúng tôi yêu cầu **cả hai cửa sổ** 5 phút và 1 giờ đều phải vượt qua $14.4$.
  * Cửa sổ 5m giúp phát hiện nhanh. Cửa sổ 1h đảm bảo lỗi kéo dài ổn định (loại bỏ các spike nhiễu tức thời dưới 2 phút).

### 2.2. Lựa chọn 18 Đặc Trưng (Features) cho Isolation Forest (Tầng Chủ động)
Để phân biệt "Bận" vs "Hỏng" và chống Masking, chúng tôi sử dụng mô hình học máy không giám sát Isolation Forest trên 18 đặc trưng:
* **Nhóm đặc trưng hạ tầng & ứng dụng gốc (7 raw):** CPU, Memory, RPS, Latency P90, Server Error Rate, Client Error Rate, Kafka Lag.
* **Nhóm đặc trưng chuẩn hóa & phái sinh (7 derived):**
  * `error_ratio` & `client_error_ratio`: Chuẩn hóa lỗi theo RPS, giúp mô hình nhận diện lỗi 3% bất kể RPS là 10 hay 150 (chống masking).
  * `latency_deviation`: Độ lệch latency so với trung vị trượt 1h (`rolling_median_1h`). Tránh sử dụng ngưỡng tĩnh.
  * `cpu_per_rps`: CPU tiêu hao trên mỗi request. Nếu CPU tăng mà RPS không tăng $\rightarrow$ nghẽn luồng/leak.
  * `memory_growth` & `kafka_lag_growth`: Tốc độ tích tụ tài nguyên.
* **Nhóm đặc trưng ngữ cảnh (4 contextual):** `hour_of_day`, `day_of_week`, `is_business_hours`, và đặc biệt là `is_high_traffic_period` (giúp mô hình biết hệ thống đang trong đợt tải cao bình thường để không báo động giả).

### 2.3. Quy trình Tự sinh Tóm tắt Sự cố (LLM Incident Summary)
Khi chỉ số vi phạm các ngưỡng trên, Engine sẽ tự động kích hoạt Bedrock LLM (`amazon.nova-lite-v1:0`) để sinh tóm tắt sự cố với template bắt buộc:
* **Hiện tượng:** Mô tả ngắn gọn triệu chứng (ví dụ: Latency tăng vọt).
* **Nguyên nhân gốc:** Chỉ ra lý do kỹ thuật kèm theo **Trích dẫn nguồn (Citation)** từ Bedrock Knowledge Base (ví dụ: *Nguồn tham chiếu: INC-3 từ Bedrock Knowledge Base*).
* **Bằng chứng (Evidence):** Phải chứa thông tin liên kết Jaeger Trace ID, Log template thu thập từ Drain3, và trị số Metrics vi phạm.
* **Vùng ảnh hưởng (Blast Radius):** Dự đoán các dịch vụ bị lỗi dây chuyền dựa trên đồ thị topo.

### 2.4. MTTD Baseline (Mean Time To Detect)
* **Phương thức đo lường:** Đo khoảng cách từ lúc metrics bắt đầu lệch trong dữ liệu fixture cho đến khi hệ thống phát cảnh báo.
* **Mốc Before:** Standard Alertmanager kích hoạt sau 10 - 50 phút.
* **Mốc After:** Isolation Forest phát hiện bất thường trong **30 - 35 giây** (ngay chu kỳ quét đầu tiên).

---

## 3. Hệ quả (Consequences)

* **Ưu điểm:**
  * Không còn báo động giả khi tải cao nhờ mô hình tự động thích nghi baseline theo thời gian trong ngày.
  * Bắt được các lỗi nhỏ âm ỉ dưới các đợt spike lớn nhờ các đặc trưng tỷ lệ chuẩn hóa.
  * Rút ngắn thời gian phát hiện sự cố xuống dưới 1 phút.
* **Nhược điểm:** Cần tiến trình CronJob re-train mô hình hàng tuần để cập nhật baseline khi hệ thống thay đổi quy mô.
