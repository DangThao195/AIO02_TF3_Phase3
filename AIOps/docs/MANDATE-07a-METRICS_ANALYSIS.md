# MANDATE-07a — Phân Tích Chỉ Số Giám Sát Trọng Yếu
## AIOps Engine · Anomaly Detection · Task Force 3 (Team AIO02)

> **Ticket loại:** Analysis / Design Document
> **Trạng thái:** Draft
> **Tác giả:** AIO02 — AIE1 Team
> **Ngày tạo:** 20/07/2026
**Cập nhật lần cuối:** 20/07/2026 — Bổ sung Metric 4 (`memory_usage`) và Metric 5 (`rps`)


---

## 1. Phạm Vi & Mục Tiêu

Tài liệu này xác định **5 chỉ số giám sát (metrics) trọng yếu** được lựa chọn để làm input cho mô hình phát hiện bất thường chủ động (**Isolation Forest**) của AIOps Engine.

Với mỗi metric, tài liệu trình bày:
- **Lý do lựa chọn** — căn cứ vào SLO, lịch sử sự cố và kiến trúc hệ thống.
- **Baseline "bình thường"** — khoảng giá trị dự kiến trong điều kiện vận hành ổn định, suy luận từ SLO, lịch sử sự cố và đặc tính kiến trúc của từng service. Baseline chính xác sẽ được hiệu chỉnh dần sau khi thu thập đủ telemetry production và postmortem thực tế.
- **Ngưỡng bất thường** — điều kiện định lượng để coi một điểm dữ liệu là anomaly.
- **Phương pháp phát hiện** — cơ chế kỹ thuật áp dụng (ML model, derived feature, fallback).

### Dịch vụ ưu tiên phân tích

Dựa trên `SLO.md` và `INCIDENT_HISTORY.md`, ba service được xem là **trọng yếu nhất**:

| Dịch vụ | Lý do ưu tiên |
|---|---|
| **`checkout`** | SLO cứng ≥ 99.0% (cao nhất hệ thống), trực tiếp tạo doanh thu; liên quan INC-1 (checkout chậm + lỗi giờ cao điểm) |
| **`payment`** | Xử lý giao dịch tài chính; liên quan INC-3 (lỗi thanh toán trong lúc deploy); service stateful có rủi ro OOMKill cao |
| **`product-catalog`** | SLO non-5xx ≥ 99.5% và p95 latency < 1s; là upstream của toàn bộ luồng duyệt/tìm sản phẩm, có RPS cao trong hệ thống |

---

## 2. Phân Tích Chi Tiết Từng Metric

---

### Metric 1 — `error_rate` · Error Rate (Tỷ Lệ Lỗi Server-side 5xx)

**Service áp dụng:** `checkout`, `payment`, `product-catalog` (và toàn bộ 7 service)

#### 2.1.1 Lý Do Lựa Chọn

`error_rate` là **Golden Signal** trực tiếp nhất — mỗi lỗi server-side (5xx) đồng nghĩa một request của người dùng thất bại và tiêu thụ Error Budget SLO. Cụ thể:

- **Checkout SLO ≥ 99.0%:** Error budget chỉ 1%. Bất kỳ chuỗi lỗi nào duy trì `error_ratio > 1%` trong một cửa sổ đo đều có nghĩa là **đã vượt SLO ngay trong chu kỳ đó**.
- **INC-1** ghi nhận: tỉ lệ đặt hàng thành công tụt xuống ~95% (error rate ~5%) vào giờ cao điểm — hoàn toàn có thể phát hiện sớm nếu monitor `error_rate` với ngưỡng thích hợp.
- **INC-3** ghi nhận: lỗi thanh toán xuất hiện trong vài phút deploy — spike ngắn trên `payment.error_rate` là dấu hiệu cần bắt được.

Không monitor error_rate đồng nghĩa với việc chỉ biết SLO bị vi phạm **sau khi tác động đã xảy ra với khách hàng**.

#### 2.1.2 Baseline "Bình Thường"

Baseline được suy luận từ SLO và đặc tính kiến trúc — chưa có telemetry production đủ để đo chính xác:

| Service | Baseline Error Rate dự kiến | Ghi chú |
|---|---|---|
| `checkout` | **~0 errors/s** trong điều kiện bình thường | SLO 99.0% cho phép tối đa 1% request lỗi; bất kỳ lỗi kéo dài nào đều đáng điều tra |
| `payment` | **~0 errors/s** trong điều kiện bình thường | Giao dịch tài chính — bất kỳ 5xx nào đều là sự kiện nghiêm trọng |
| `product-catalog` | **~0 errors/s** trong điều kiện bình thường | Service stateless, thuần read; lỗi là dấu hiệu bất thường rõ ràng |

- **Derived feature liên quan:** `error_ratio = error_rate / (rps + ε)` — chuẩn hóa lỗi theo tải; baseline bình thường: **< 0.5%** (tức còn dưới ngưỡng SLO budget).
- Baseline tuyệt đối (số errors/s) sẽ được hiệu chỉnh sau khi có đủ telemetry production và postmortem.

#### 2.1.3 Ngưỡng Bất Thường

| Điều kiện | Mức độ | Lý giải |
|---|---|---|
| `error_rate > 0` liên tục ≥ 2 chu kỳ (10 phút) trên `checkout` hoặc `payment` | **WARNING** | Bất kỳ lỗi nào kéo dài > 1 chu kỳ đều cần điều tra — error budget quá nhỏ |
| `error_ratio > 1.0%` tại bất kỳ chu kỳ nào trên service trọng yếu | **WARNING** | Vượt ngưỡng SLO checkout (1% budget) |
| `error_ratio > 2.0%` | **CRITICAL** | Tiêu cạn toàn bộ error budget 24h trong < 1h nếu duy trì |
| SLO Burn Rate ≥ 14.4× trên cả cửa sổ 5m VÀ 1h | **CRITICAL (SLO)** | Tiêu cạn 100% error budget 30 ngày trong ~50 phút |
| `error_rate` tăng đột biến > 10× baseline trong 1 chu kỳ | **Isolation Forest anomaly** | Spike ngắn — đặc trưng của lỗi deploy (INC-3 pattern) |

#### 2.1.4 Phương Pháp Phát Hiện

| Layer | Phương pháp | Chi tiết |
|---|---|---|
| **Primary (Proactive)** | Isolation Forest | Features: `error_rate` + `error_ratio`; Model học phân phối bình thường (error = 0) và tự coi mọi spike là outlier |
| **Secondary (Reactive)** | SLO Burn Rate Alert | `BurnRate = (error_rate / SLO_budget_rate) × 720`; kích hoạt khi ≥ 14.4× trên cả 5m và 1h |
| **Fallback** | Z-Score | `Z = (error_rate_t - μ_24h) / (σ_24h + ε)`; kích hoạt khi `|Z| ≥ 3.0` và không có model IF |

**Lý do dùng cả `error_rate` lẫn `error_ratio`:** Cùng một giá trị error_rate tuyệt đối sẽ nghiêm trọng hơn nhiều trên service có RPS thấp như `checkout` so với service có RPS cao hơn như `frontend`. `error_ratio` giúp model IF nhận ra sự khác biệt này mà không cần biết số RPS tuyệt đối là bao nhiêu.

---

### Metric 2 — `latency_p90` · Độ Trễ Phân Vị 90 (P90 Latency)

**Service áp dụng chính:** `checkout`, `product-catalog`, `frontend`

#### 2.2.1 Lý Do Lựa Chọn

`latency_p90` là **Golden Signal** đo trải nghiệm người dùng thực tế. SLO về latency được định nghĩa trực tiếp trong `SLO.md`:

- **Duyệt sản phẩm (storefront/product-catalog):** p95 latency < 1s → P90 là proxy tốt, giảm nhạy với outlier đơn lẻ so với P95/P99.
- **INC-1** ghi nhận: "p95 latency checkout vọt lên vài giây" vào giờ cao điểm — latency spike là triệu chứng đầu tiên có thể nhận được trước khi SLO vỡ hẳn.
- **Tại sao P90 chứ không phải P99 hay P50:**
  - P99 quá nhạy với outlier cô lập (GC pause, DNS lookup lần đầu) → false alarm cao.
  - P50 (median) không nhạy với suy giảm ảnh hưởng 10% người dùng → bỏ sót sự cố.
  - P90 phản ánh trải nghiệm của 90% người dùng — **đủ nhạy, đủ ổn định**.

#### 2.2.2 Baseline "Bình Thường"

Baseline latency được suy luận từ SLO và đặc tính kiến trúc của từng service:

| Service | Khoảng latency dự kiến (production) | Ngưỡng cần điều tra |
|---|---|---|
| `checkout` | **50–300 ms** (sync, có DB call) | > 1s — INC-1 ghi nhận khách bỏ giỏ khi latency vọt vài giây |
| `payment` | **100–500 ms** (stateful, I/O DB + downstream) | > 1.5s — giao dịch timeout nguy cơ double-charge |
| `product-catalog` | **20–150 ms** (read-heavy, có thể cache) | > 700ms — SLO p95 < 1s; P90 > 700ms → P95 khả năng đã vi phạm SLO |

> **Lưu ý:** Đây là khoảng ước tính dựa trên đặc tính kiến trúc (sync/async, có DB không, có cache không). Baseline chính xác cần được đo từ telemetry production thực tế và sẽ được cập nhật sau postmortem đầu tiên.

- **Derived feature:** `latency_deviation = latency_p90 / (rolling_median_1h + ε)` — baseline bình thường: **< 2.0** (không vượt quá 2× median 1 giờ gần nhất của chính service đó).

#### 2.2.3 Ngưỡng Bất Thường

| Điều kiện | Mức độ | Lý giải |
|---|---|---|
| `latency_p90 > 700ms` trên `product-catalog` | **WARNING** | Tiệm cận SLO p95 < 1s; P90 > 700ms → P95 khả năng đã > 1s |
| `latency_p90 > 1000ms (1s)` trên `checkout` | **WARNING** | INC-1 pattern: latency checkout vọt lên → khách bỏ giỏ |
| `latency_p90 > 2000ms (2s)` trên bất kỳ service trọng yếu | **CRITICAL** | Trải nghiệm người dùng rõ ràng bị ảnh hưởng |
| `latency_deviation > 2.0` (gấp 2× median 1h) | **WARNING** | Tăng đột ngột không giải thích được bởi tải bình thường |
| `latency_deviation > 4.0` (gấp 4× median 1h) | **CRITICAL** | Tương đương spike latency nghiêm trọng |
| Latency tăng đều qua ≥ 3 chu kỳ liên tiếp (SLO Erosion) | **WARNING** | Xu hướng degradation chậm — khó thấy bằng threshold tĩnh |

#### 2.2.4 Phương Pháp Phát Hiện

| Layer | Phương pháp | Chi tiết |
|---|---|---|
| **Primary (Proactive)** | Isolation Forest | Features: `latency_p90` + `latency_deviation`; `latency_deviation` dùng rolling median 1h (12 data points ở step 5m) làm baseline động — tránh báo nhầm khi hệ thống scale up hợp lý |
| **Trending (Proactive)** | Slope Detection | Kiểm tra `latency_p90` có xu hướng tăng đơn điệu qua ≥ 3 chu kỳ → phát hiện degradation chậm mà ngưỡng tĩnh bỏ sót |
| **Fallback** | Static Threshold | Hard cutoff: `latency_p90 > 1s` trên `checkout/product-catalog` → alert ngay dù model chưa ready |

**Tại sao không dùng ngưỡng tĩnh duy nhất:** Latency bình thường lúc 3h sáng (RPS thấp) khác latency bình thường lúc 11h (giờ cao điểm). `latency_deviation` chuẩn hóa theo lịch sử 1h của chính service đó, tự thích nghi với pattern tải theo thời gian.

---

### Metric 3 — `cpu_usage` · Mức Tiêu Thụ CPU (Saturation)

**Service áp dụng chính:** `checkout`, `payment`, `product-catalog`

#### 2.3.1 Lý Do Lựa Chọn

`cpu_usage` là **Saturation Signal** — đo mức độ bão hòa tài nguyên tính toán. CPU saturation không ảnh hưởng trực tiếp đến người dùng, nhưng là **dấu hiệu cảnh báo sớm** trước khi latency và error rate tăng:

- **INC-1** ghi nhận: "số kết nối tới cơ sở dữ liệu cạn khi tải tăng đột biến" → CPU vọt cao kèm RPS tăng đột biến là pattern tiền thân của DB connection exhaustion.
- **Phát hiện bất thường nội bộ:** `cpu_per_rps = cpu_usage / (rps + ε)` tăng mạnh trong khi RPS không đổi → nghẽn xử lý nội bộ (deadlock, infinite retry loop, memory pressure) mà không thể thấy từ latency/error rate đơn thuần.
- **INC-3 pattern:** Deploy mới gây CPU spike ngắn khi pod khởi động và xử lý burst request lúc readiness chưa đạt → CPU spike + error rate spike đồng thời = dấu hiệu deployment issue.
- **Phát hiện service down ngược chiều:** CPU sụt về 0 khi đáng lẽ phải có tải → pod đã dừng nhận traffic (crash, OOMKill).

#### 2.3.2 Baseline "Bình Thường"

Baseline CPU được suy luận từ đặc tính xử lý của từng service — chưa có telemetry production để định lượng chính xác:

| Service | Đặc tính CPU dự kiến | Dấu hiệu cần chú ý |
|---|---|---|
| `checkout` | Tương đối thấp (sync handler, DB call là bottleneck) | CPU tăng đột biến khi RPS tăng → coi là tiền thân của DB exhaustion (INC-1) |
| `payment` | Vừa phải (transaction processing, có retry logic) | `cpu_per_rps` tăng mà RPS ổn định → retry loop hoặc downstream timeout |
| `product-catalog` | Thấp (read-heavy, stateless) | CPU cao bất thường ngay cả lúc ít request → nghi ngờ background task hoặc memory pressure |

- **Derived feature:** `cpu_per_rps = cpu_usage / (rps + ε)` — bất thường khi tăng > 3× so với rolling median 1h của chính service đó, bất kể giá trị tuyệt đối là bao nhiêu.
- Ngưỡng tuyệt đối (số cores) sẽ được hiệu chỉnh sau khi có đủ data production — model IF sẽ học baseline thực tế từ telemetry.

#### 2.3.3 Ngưỡng Bất Thường

| Điều kiện | Mức độ | Lý giải |
|---|---|---|
| `cpu_usage` vượt 5× rolling median 1h liên tục ≥ 2 chu kỳ (10 phút) | **WARNING** | Tải tăng bất thường hoặc nghẽn nội bộ |
| `cpu_per_rps` tăng > 3× rolling median 1h trong khi RPS ổn định | **WARNING** | Chi phí CPU/request tăng → nghi ngờ memory pressure, GC storm, hoặc retry loop |
| `cpu_per_rps` tăng đồng thời với `latency_deviation > 2.0` | **CRITICAL** | Thread contention → latency tăng, SLO bị đe dọa |
| `cpu_usage` sụt > 80% so với median 1h trong khi RPS không sụt | **CRITICAL** | Service có thể đang crash-loop hoặc bị OOMKill |
| Z-Score CPU `> 3.0` so với baseline 24h | **WARNING (Fallback)** | Kích hoạt khi model IF không available |

#### 2.3.4 Phương Pháp Phát Hiện

| Layer | Phương pháp | Chi tiết |
|---|---|---|
| **Primary (Proactive)** | Isolation Forest | Features: `cpu_usage` + `cpu_per_rps`; đặc biệt hiệu quả trong không gian đa chiều với `latency_p90` và `error_rate` — phát hiện correlation bất thường (CPU cao + error cao + latency cao) mà rule đơn lẻ không thấy |
| **Correlation Check** | Multi-metric Rule | `cpu_per_rps > 3× median` VÀ `latency_deviation > 2.0` → cảnh báo mức CRITICAL dù IF chưa kết luận |
| **Fallback** | Z-Score | `Z = (cpu_t - μ_24h) / σ_24h`; kích hoạt khi `|Z| ≥ 3.0` — đặc biệt hữu ích trong giai đoạn bootstrap trước khi IF model có đủ data |

**Contextual awareness:** Các feature `hour_of_day`, `is_business_hours`, `is_high_traffic_period` được đưa vào cùng IF model, đảm bảo cùng một mức CPU tiêu thụ lúc 3h sáng được đánh giá khác với lúc 11h trưa giờ cao điểm.

---

### Metric 4 — `memory_usage` · Tỷ Lệ Sử Dụng Bộ Nhớ (Memory Saturation)

**Service áp dụng chính:** `payment`, `product-reviews`, `checkout`

#### 2.4.1 Lý Do Lựa Chọn

`memory_usage` là **Saturation Signal** thứ hai bên cạnh CPU, và có đặc điểm quan trọng là **xu hướng tích lũy** (không phải spike ngắn) — điều này làm nó vô hình với alert ngưỡng tĩnh nếu chỉ theo dõi giá trị tức thời:

- **`payment` là service stateful** xử lý giao dịch tài chính. Đặc tính stateful (giữ session, connection pool, transaction context trong memory) đặt ra nguy cơ OOMKill cao hơn các service stateless — khi memory đạt giới hạn, Kubernetes buộc phải kill pod, gây gián đoạn giao dịch đột ngột.
- **INC-2** ghi nhận: "lớp lưu giỏ hàng chạy đơn lẻ, khi pod bị lên lịch lại thì state trong bộ nhớ mất theo" — memory pressure dẫn đến rescheduling là một trong các trigger. Bài học còn treo: "bản sao/độ bền dữ liệu chưa làm dứt điểm".
- **`product-reviews`** gọi LLM để tạo tóm tắt review; response từ model AI có thể tích lũy trong bộ nhớ nếu không được giải phóng đúng cách (memory leak do stream chưa đóng, buffer response lớn không được flush).
- Memory leak thường biểu hiện qua **xu hướng tăng đều đặn** qua nhiều chu kỳ, không phải spike — feature `memory_growth` được thiết kế đặc biệt để bắt pattern này.

#### 2.4.2 Baseline "Bình Thường"

Baseline được suy luận từ đặc tính kiến trúc của từng service — chưa có telemetry production để định lượng chính xác:

| Service | Đặc tính memory dự kiến | Ngưỡng cảnh báo suy luận |
|---|---|---|
| `checkout` | Thấp đến vừa (stateless handler) | > 70% memory limit; `memory_growth > 0.05` trong 30 phút |
| `payment` | Vừa đến cao (stateful, connection pool, transaction context) | > 85% memory limit — ngưỡng cao hơn do stateful; nhưng `memory_growth` phải được bắt từ sớm |
| `product-reviews` | Vừa, biến động theo LLM batch size | > 80% memory limit; cần theo dõi đặc biệt sau khi LLM feature go-live |

> **Lưu ý:** Ngưỡng tuyệt đối (% memory limit) cần được hiệu chỉnh sau khi có telemetry production. Tốc độ tăng (`memory_growth`) là chỉ số quan trọng hơn giá trị tức thời trong giai đoạn chưa có đủ data.

- **Derived feature:** `memory_growth = memory_t - memory_{t-6}` (delta 30 phút) — baseline bình thường: **< 0.02** (tăng không quá 2 điểm phần trăm trong 30 phút); GC oscillation ngắn hạn (±0.01 trong 1–2 chu kỳ) là bình thường.

#### 2.4.3 Ngưỡng Bất Thường

| Điều kiện | Mức độ | Lý giải |
|---|---|---|
| `memory_usage > 0.85` trên `payment` | **CRITICAL** | Nguy cơ OOMKill cao; giao dịch đang xử lý có thể bị hủy đột ngột |
| `memory_usage > 0.80` trên `product-reviews` | **WARNING** | LLM response tích lũy; cần kiểm tra stream/buffer cleanup |
| `memory_usage > 0.75` trên `checkout` | **WARNING** | Service stateless nên không cần nhiều memory — vượt 75% là bất thường, nghi ngờ session leak |
| `memory_growth > 0.05` trong 30 phút (6 chu kỳ) | **WARNING** | Tốc độ tích lũy bất thường — dấu hiệu memory leak sớm |
| `memory_growth > 0.05` liên tục ≥ 3 lần (90 phút) | **CRITICAL** | Memory leak xác nhận — cần intervention trước khi OOMKill |
| Memory tăng đều đặn qua ≥ 6 chu kỳ mà không giảm | **WARNING (Trend)** | Pattern memory leak kinh điển — phát hiện sớm nhất qua trend, không phải threshold |

#### 2.4.4 Phương Pháp Phát Hiện

| Layer | Phương pháp | Chi tiết |
|---|---|---|
| **Primary (Proactive)** | Isolation Forest | Features: `memory_usage` + `memory_growth`; IF học đặc trưng memory tăng dần (pattern bất thường so với normal có GC oscillation) |
| **Trend Detection** | Monotonic Increase Check | Kiểm tra `memory_usage` tăng đơn điệu qua ≥ 6 chu kỳ liên tiếp (30 phút) → đặc trưng của memory leak, không thể phát hiện bằng ngưỡng tĩnh |
| **Static Threshold** | Hard cutoff | `memory_usage > 0.85` trên `payment` → alert ngay lập tức, không chờ IF model |
| **Fallback** | Z-Score trên `memory_growth` | `Z = (growth_t - μ_24h) / σ_24h`; kích hoạt khi `|Z| ≥ 3.0` |

**Tại sao `memory_growth` quan trọng hơn `memory_usage` tuyệt đối:** Với service stateful như `payment`, memory baseline khi production có thể ở mức vừa phải do connection pool và transaction context thường trực. Nếu chỉ dùng ngưỡng tĩnh, có thể phải đợi hệ thống tăng rất nhiều mới biết có vấn đề. `memory_growth` phát hiện xu hướng bất thường sớm hơn, cho đủ thời gian can thiệp trước khi đạt ngưỡng nguy hiểm.

---

### Metric 5 — `rps` · Request Rate (Lưu Lượng Yêu Cầu)

**Service áp dụng chính:** `checkout`, `product-catalog`, `frontend`

#### 2.5.1 Lý Do Lựa Chọn

`rps` (Requests Per Second) là **Traffic Signal** — đo lưu lượng vào hệ thống. Không phải Golden Signal user-visible như error_rate hay latency, nhưng là **điều kiện tiên quyết** để hiểu mọi metric khác đúng ngữ cảnh:

- **INC-1** ghi nhận: "tải tăng đột biến" vào giờ cao điểm khuyến mãi là nguyên nhân gốc gây DB connection exhaustion → checkout chậm. RPS spike là **dấu hiệu sớm nhất**, xuất hiện trước khi CPU/latency/error tăng.
- **Phát hiện service down:** RPS sụt về 0 đột ngột trong khi upstream service vẫn hoạt động = service đã crash hoặc mất kết nối network. Không có metric nào khác phát hiện nhanh hơn.
- **Điều kiện hóa các metric khác:** `error_ratio`, `cpu_per_rps`, `latency_deviation` đều dùng RPS làm mẫu số — nếu RPS = 0 hoặc bất thường, các derived feature này sẽ cho kết quả sai lệch mà IF model cần biết ngữ cảnh.
- **INC-1 pattern — giờ cao điểm:** Spike RPS tại 11h–13h và 19h–22h (is_high_traffic_period) kết hợp với CPU/latency tăng theo là pattern bình thường; cùng spike đó lúc 3h sáng là anomaly. Feature `rps_delta` + context flags giúp IF phân biệt.

#### 2.5.2 Baseline "Bình Thường"

Baseline RPS được suy luận từ vị trí của service trong luồng xử lý — chưa có telemetry production để định lượng chính xác:

| Service | Vị trí trong luồng & đặc tính tải | Khoảng RPS dự kiến production |
|---|---|---|
| `checkout` | Cuối funnel — chỉ user đã thêm giỏ và muốn đặt hàng mới gọi | Thấp hơn `product-catalog` và `frontend` đáng kể; tăng đột biến lúc giờ cao điểm khuyến mãi |
| `product-catalog` | Gần đầu funnel — mọi request duyệt/tìm sản phẩm đều đi qua | RPS cao trong hệ thống; ổn định theo giờ, tăng rõ giờ cao điểm |
| `frontend` | Entry point — nhận toàn bộ traffic người dùng | RPS cao nhất hệ thống; biến động lớn nhất theo giờ |

> **Lưu ý:** Tỉ lệ tương đối giữa các service (frontend > product-catalog > checkout > payment) ổn định hơn con số tuyệt đối và được dùng làm tín hiệu sanity-check khi phân tích anomaly.

- **Derived feature:** `rps_delta = rps_t - rps_{t-1}` — bất thường khi `|rps_delta| > 50% của rps_{t-1}` trong một chu kỳ 5 phút, ngoài cửa sổ `is_high_traffic_period`.
- Baseline tuyệt đối sẽ được model IF học từ telemetry production thực tế qua các chu kỳ re-training.

#### 2.5.3 Ngưỡng Bất Thường

| Điều kiện | Mức độ | Lý giải |
|---|---|---|
| `rps` sụt > 80% so với rolling median 1h trong 1 chu kỳ | **CRITICAL** | Service ngừng nhận traffic — nghi ngờ crash, network partition, hoặc upstream timeout |
| `rps` = 0 liên tục ≥ 2 chu kỳ (10 phút) trong giờ kinh doanh | **CRITICAL** | Service down — không còn phục vụ request nào |
| `rps_delta > 3×` của `rps_{t-1}` ngoài `is_high_traffic_period` | **WARNING** | Traffic spike bất thường — nghi ngờ retry storm, bot scan, hoặc upstream misbehavior |
| `rps_delta > 5×` bất kể thời điểm | **CRITICAL** | Spike cực lớn — nguy cơ DDoS hoặc cascading retry |
| `rps` tăng đồng thời với `cpu_per_rps > 3× median` VÀ `latency_deviation > 2.0` | **CRITICAL** | INC-1 pattern: overload dẫn đến DB connection exhaustion |

#### 2.5.4 Phương Pháp Phát Hiện

| Layer | Phương pháp | Chi tiết |
|---|---|---|
| **Primary (Proactive)** | Isolation Forest | Features: `rps` + `rps_delta` + context flags (`hour_of_day`, `is_high_traffic_period`); IF học rằng spike lúc 11h trưa là bình thường, cùng spike lúc 3h sáng là anomaly |
| **Drop Detection** | Threshold + Duration | `rps < 20% median_1h` liên tục ≥ 2 chu kỳ → immediate alert, không chờ IF |
| **Correlation Rule** | Multi-metric | `rps_delta > 3×` VÀ `cpu_per_rps > 3× median` → escalate thành CRITICAL (INC-1 pattern) |
| **Fallback** | Z-Score trên `rps_delta` | `|Z| ≥ 3.0` trên delta → phát hiện spike/drop bất thường khi model chưa available |

**Tại sao `rps_delta` quan trọng hơn `rps` tuyệt đối:** Cùng một mức RPS có thể bình thường lúc cao điểm nhưng bất thường lúc 2h sáng. `rps_delta` đo tốc độ thay đổi — một spike tăng 10× trong một chu kỳ 5 phút là bất thường bất kể giá trị tuyệt đối. Kết hợp `rps_delta` với context flags (`hour_of_day`, `is_high_traffic_period`) giúp IF phân biệt được tăng tải bình thường theo giờ với spike bất thường.

---

## 3. Tổng Hợp Ma Trận Metric × Service

| Metric | `checkout` | `payment` | `product-catalog` | `product-reviews` | `frontend` | Mức ưu tiên |
|---|---|---|---|---|---|---|
| `error_rate` *(Metric 1)* | ✅ CRITICAL | ✅ CRITICAL | ✅ HIGH | ⚠️ MEDIUM | ✅ HIGH | **P0** |
| `latency_p90` *(Metric 2)* | ✅ CRITICAL | ✅ HIGH | ✅ CRITICAL | ⚠️ MEDIUM | ✅ HIGH | **P0** |
| `cpu_usage` *(Metric 3)* | ✅ HIGH | ✅ HIGH | ✅ HIGH | ⚠️ MEDIUM | ✅ HIGH | **P1** |
| `memory_usage` *(Metric 4)* | ✅ HIGH | ✅ CRITICAL (stateful) | ⚠️ MEDIUM | ✅ HIGH (LLM buffer) | ⚠️ MEDIUM | **P1** |
| `rps` *(Metric 5)* | ✅ CRITICAL | ✅ HIGH | ✅ CRITICAL | ⚠️ MEDIUM | ✅ CRITICAL | **P1** |
| `kafka_lag`† | ✅ HIGH | — | — | — | — | **P2** |

> †`kafka_lag` không thuộc 5 metrics chính của document này nhưng được đưa vào full feature set của Isolation Forest (18 features theo `datametric_schema.md`). Phân tích đầy đủ dự kiến bổ sung trong phiên bản tiếp theo.

---

## 4. Phương Pháp Phát Hiện Tổng Hợp

### 4.1 Kiến Trúc Hai Tầng

```
                    ┌─────────────────────────────────────────────┐
                    │           TẦNG 1: PROACTIVE (ML)            │
                    │                                             │
                    │   Isolation Forest — 18 features           │
                    │   ┌──────────────────────────────────────┐  │
                    │   │  Raw: rps, error_rate, latency_p90,  │  │
                    │   │       cpu_usage, memory_usage,        │  │
                    │   │       client_error_rate, kafka_lag    │  │
                    │   │  Derived: error_ratio, latency_dev,  │  │
                    │   │       cpu_per_rps, memory_growth...  │  │
                    │   │  Context: hour, dow, biz_hrs, peak   │  │
                    │   └──────────────────────────────────────┘  │
                    │         Output: prediction = -1 → Anomaly   │
                    │         Confidence: score < -0.3 → HIGH     │
                    └─────────────────────────────────────────────┘
                                         │
                                         ▼ (khi SLO bắt đầu bị ăn mòn)
                    ┌─────────────────────────────────────────────┐
                    │           TẦNG 2: REACTIVE (SLO)            │
                    │                                             │
                    │   SLO Burn Rate Multi-Window                │
                    │   BurnRate ≥ 14.4× trên CẢ 5m VÀ 1h        │
                    │   Output: Immediate Alert → Slack           │
                    └─────────────────────────────────────────────┘
```

### 4.2 Lý Do Chọn Isolation Forest

| Tiêu chí | Lý do |
|---|---|
| **Unsupervised** | Không cần nhãn lịch sử — chưa có đủ postmortem thực tế để làm supervised learning; IF học phân phối bình thường từ telemetry thu thập được |
| **Hiệu quả đa chiều** | Hoạt động tốt trên 18 features mà không cần giảm chiều thủ công |
| **Phát hiện correlation** | Nhận ra tổ hợp bất thường (CPU cao + latency cao + RPS ổn định) mà rule đơn lẻ bỏ sót |
| **Tốc độ suy luận** | O(n log n) — phù hợp chu kỳ quét 30 giây của Engine |
| **Baseline tự thích nghi** | CronJob re-train mỗi thứ Hai 2h sáng cập nhật baseline tuần; không cần tune ngưỡng thủ công |

### 4.3 Derived Features Quan Trọng Nhất

| Feature | Công thức | Tác dụng |
|---|---|---|
| `error_ratio` | `error_rate / (rps + ε)` | Chuẩn hóa lỗi theo tải — tránh false negative khi RPS cao |
| `latency_deviation` | `latency_p90 / (rolling_median_1h + ε)` | Baseline động — tự thích nghi với tải theo giờ |
| `cpu_per_rps` | `cpu_usage / (rps + ε)` | Phát hiện tăng chi phí xử lý nội bộ không giải thích được |
| `memory_growth` | `memory_t - memory_{t-6}` (delta 30 phút) | Phát hiện xu hướng leak sớm — quan trọng hơn giá trị tuyệt đối với `payment` |
| `rps_delta` | `rps_t - rps_{t-1}` (delta 5 phút) | Phát hiện spike/drop đột ngột — điều kiện tiên quyết của INC-1 pattern |

---

## 5. Căn Cứ Quyết Định & Liên Kết Sự Cố

| Metric | Căn cứ SLO | Căn cứ Incident | Rủi ro nếu bỏ qua |
|---|---|---|---|
| `error_rate` | Checkout SLO ≥ 99.0%; non-5xx ≥ 99.5% | INC-1 (checkout lỗi ~5%), INC-3 (payment lỗi lúc deploy) | Không biết SLO đang bị tiêu cho đến khi khách hàng phàn nàn |
| `latency_p90` | Storefront p95 < 1s | INC-1 (p95 checkout vọt vài giây) | Phát hiện suy giảm muộn sau khi khách đã bỏ giỏ |
| `cpu_usage` | Không có SLO trực tiếp | INC-1 (DB exhaustion do overload), INC-3 (deploy spike) | Bỏ sót dấu hiệu cảnh báo sớm 5–15 phút trước khi latency/error rate tăng |
| `memory_usage` | Không có SLO trực tiếp | INC-2 (pod reschedule → state loss); `payment` là service stateful có rủi ro OOMKill cao nhất | OOMKill gây gián đoạn giao dịch đột ngột; memory leak phát hiện quá muộn nếu chỉ dùng threshold tĩnh |
| `rps` | Gián tiếp: mọi SLO đều tính trên số request | INC-1 (traffic spike giờ cao điểm là trigger gốc) | Bỏ sót trigger gốc của sự cố; derived features (error_ratio, cpu_per_rps) sai lệch nếu RPS anomaly không được phát hiện |

---

## 6. Ghi Chú & Ràng Buộc

1. **Baseline trong tài liệu này là ước tính, không phải ground truth:** Tất cả khoảng giá trị baseline được suy luận từ SLO, lịch sử sự cố (INC-1, INC-2, INC-3) và đặc tính kiến trúc từng service. Chưa có đủ telemetry production để đo baseline chính xác. Các con số sẽ được hiệu chỉnh sau khi tích lũy đủ dữ liệu vận hành thực tế và qua các postmortem tiếp theo.

2. **Ưu tiên ngưỡng tương đối hơn tuyệt đối:** Do baseline chưa đo được từ production, các điều kiện phát hiện dựa trên tỉ lệ (`latency_deviation`, `cpu_per_rps`, `rps_delta`, `memory_growth`) bền vững hơn ngưỡng tuyệt đối và không bị lỗi thời khi tải thay đổi theo mùa. Các hard threshold tuyệt đối (ví dụ `latency > 1s`, `memory > 0.85`) chỉ đóng vai trò fallback.

3. **`payment` là service cần ưu tiên theo dõi memory:** Đây là service stateful duy nhất trong nhóm trọng yếu — giữ connection pool, transaction context và session state trong bộ nhớ. Rủi ro OOMKill cao hơn hẳn các service stateless. Cần thiết lập alert riêng cho `memory_growth` trên service này ngay khi có telemetry production.

4. **`product-reviews` cần theo dõi sau LLM go-live:** Đặc tính gọi LLM để tạo tóm tắt review tạo ra rủi ro memory tích lũy (response buffer, stream chưa đóng) không có trên các service khác. Cần baseline riêng sau khi feature AI đi vào production.

5. **SLO Burn Rate là tầng reactive, không proactive:** Burn Rate chỉ kích hoạt khi SLO **đã đang bị vi phạm**. Isolation Forest là tầng chính phát hiện **trước khi** SLO bị vỡ. Mục tiêu dài hạn là phần lớn sự cố được phát hiện bởi IF trước khi Burn Rate alert được kích hoạt.

6. **Kafka lag sẽ được bổ sung ở phiên bản tiếp theo:** `checkout` và `shipping` sử dụng Kafka. `kafka_lag` là metric quan trọng cho `shipping` (backlog xử lý đơn hàng) và cần phân tích riêng khi có đủ ngữ cảnh về topology Kafka của hệ thống.

---

*Tài liệu tham chiếu: `datametric_schema.md`, `SLO.md`, `INCIDENT_HISTORY.md`*
*Phiên bản v2 dự kiến: bổ sung phân tích `kafka_lag`; hiệu chỉnh baseline sau khi có telemetry production và postmortem thực tế (target: tuần 3)*
