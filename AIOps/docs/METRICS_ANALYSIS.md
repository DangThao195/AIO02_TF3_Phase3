# Phân Tích Bộ Chỉ Số Giám Sát (Metrics Analysis)
# AIOps Engine — Task Force 3 (Team AIO02)

> **Mục tiêu tài liệu:** Ghi nhận đầy đủ lý do lựa chọn, baseline bình thường, ngưỡng phát hiện bất thường và phương pháp áp dụng cho toàn bộ 7 chỉ số gốc (raw metrics) và 7 chỉ số phái sinh (derived features) được Engine sử dụng để huấn luyện và suy luận mô hình Isolation Forest.

---

## 📌 Tổng Quan Kiến Trúc Thu Thập Dữ Liệu

```
Prometheus (OTLP Span Metrics + cAdvisor + Kafka)
    │
    ├── traces_span_metrics_calls_total       → RPS, Error Rate
    ├── traces_span_metrics_duration_ms       → P90 Latency
    ├── container_cpu_usage_seconds_total     → CPU Usage
    ├── container_memory_working_set_bytes    → Memory Usage
    └── kafka_consumer_records_lag            → Kafka Lag
              │
              ▼
    extract_features_realtime()  ← query_range 1 giờ, step 5m
              │
              ▼
    7 raw metrics → 7 derived features = 14 features tổng cộng
    + 4 contextual features (giờ/ngày/business hours/traffic peak)
              │
              ▼
    Isolation Forest Model (predict: 1 = Normal, -1 = Anomaly)
```

**Dịch vụ trọng yếu được giám sát (7 services):**
`frontend`, `checkout`, `payment`, `product-catalog`, `product-reviews`, `shipping`, `recommendation`

---

## 🔵 PHẦN 1: 7 CHỈ SỐ GỐC (Raw Metrics)

---

### 📊 Metric 1: RPS — Tốc Độ Xử Lý Yêu Cầu (Requests Per Second)

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(rate(traces_span_metrics_calls_total{service_name="<svc>", span_kind="SPAN_KIND_SERVER"}[5m]))` |
| **Nguồn dữ liệu** | OpenTelemetry Span Metrics Connector → Prometheus |
| **Đơn vị** | req/s |

**Lý do lựa chọn:**
RPS là chỉ số trung tâm phản ánh lượng tải thực tế mà một dịch vụ phải xử lý. Đây là "Golden Signal" đầu tiên trong triết lý SRE của Google. Sự sụt giảm RPS đột ngột có thể chỉ ra dịch vụ bị crash, routing lỗi hoặc downstream dependency bị chặn. Sự tăng vọt bất thường có thể báo hiệu traffic spike hoặc DDoS.

**Baseline bình thường (dựa trên dữ liệu EKS từ 14/07/2026):**
- `frontend`: 5–20 req/s (giờ ban ngày), < 2 req/s (ban đêm)
- `checkout`, `payment`: 1–8 req/s
- `product-catalog`, `recommendation`: 10–50 req/s

**Ngưỡng bất thường:**
- Sụt giảm > 80% so với baseline 1h gần nhất → nghi ngờ dịch vụ down
- Tăng > 300% so với rolling median 1h → nghi ngờ traffic spike/DDoS

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `rps` được đưa trực tiếp vào vector đặc trưng.
- **Derived feature `rps_delta`:** Phát hiện thay đổi đột ngột qua vi phân bậc nhất $\Delta RPS = RPS_t - RPS_{t-1}$.
- **Derived feature `is_high_traffic_period`:** Flag 0/1 khi `RPS > 100` và `RPS > 1.5 × median_1h`.

---

### 📊 Metric 2: Error Rate — Tỷ Lệ Lỗi Máy Chủ (Server-side 5xx)

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(rate(traces_span_metrics_calls_total{service_name="<svc>", span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}[5m]))` |
| **Nguồn dữ liệu** | OpenTelemetry Span Metrics (OTel status codes) → Prometheus |
| **Đơn vị** | errors/s |

**Lý do lựa chọn:**
Error Rate là "Golden Signal" thứ hai. Bất kỳ sự xuất hiện nào của lỗi server-side (gRPC INTERNAL, HTTP 5xx) đều ảnh hưởng trực tiếp đến trải nghiệm người dùng và tiêu thụ Error Budget SLO. Ngay cả error rate nhỏ (0.1%) cũng có thể chỉ ra sự cố tầng database hoặc timeout upstream.

**Baseline bình thường:**
- Tất cả service: `0 errors/s` trong điều kiện bình thường
- Chấp nhận: < 0.001 errors/s (noise từ health check probe)

**Ngưỡng bất thường:**
- > 0 errors/s liên tục trong 2 chu kỳ (10 phút) → cần điều tra
- **SLO Burn Rate > 14.4x** (cả cửa sổ 5m và 1h) → kích hoạt báo động khẩn cấp

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `error_rate` và derived `error_ratio = error_rate / (rps + ε)`.
- **SLO Burn Rate (Multi-window):** Công thức $\text{BurnRate} = \frac{\text{error\_rate}}{\text{SLO\_target}} \times 720$. Ngưỡng kép: 5m-window AND 1h-window đều phải vượt 14.4 để tránh false positive.

---

### 📊 Metric 3: P90 Latency — Độ Trễ Phân Vị 90%

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="<svc>", span_kind="SPAN_KIND_SERVER"}[5m])) by (le))` |
| **Nguồn dữ liệu** | OpenTelemetry Span Metrics Histogram → Prometheus |
| **Đơn vị** | milliseconds (ms) |

**Lý do lựa chọn:**
P90 (không phải P99) được chọn vì P99 quá nhạy với các outlier đơn lẻ gây false alarm, còn P50 (median) quá mờ nhạt với sự cố ảnh hưởng thiểu số người dùng. P90 cân bằng tốt: phản ánh trải nghiệm của 90% người dùng và đủ nhạy để phát hiện suy giảm hiệu suất sớm trước khi SLO bị vi phạm.

**Baseline bình thường (EKS cluster):**
- `frontend`: 50–200ms
- `checkout`, `payment`: 100–500ms (có gọi DB/external API)
- `product-catalog`: 20–100ms (có cache Redis)

**Ngưỡng bất thường:**
- `latency_p90 > 2× rolling_median_1h` → lệch ngưỡng 2σ → nghi ngờ degradation
- `latency_deviation > 3.0` → Isolation Forest tăng anomaly score mạnh

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `latency_p90`.
- **Derived feature `rolling_median_1h`:** Tính trung vị trượt 12 điểm × 5 phút = 1 giờ làm baseline động.
- **Derived feature `latency_deviation`:** $\frac{P90\_latency}{rolling\_median\_1h + \varepsilon}$ — tỉ lệ lệch so với chính lịch sử của service, không dùng ngưỡng cố định.

---

### 📊 Metric 4: CPU Usage — Mức Tiêu Thụ CPU

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(rate(container_cpu_usage_seconds_total{container="<svc>"}[5m]))` |
| **Nguồn dữ liệu** | cAdvisor (Kubernetes built-in) → Prometheus |
| **Đơn vị** | CPU cores |

**Lý do lựa chọn:**
CPU saturation là dấu hiệu hạ tầng quan trọng, đặc biệt với các service stateless (frontend, product-catalog). CPU vọt cao thường đi kèm với latency tăng do thread contention. Ngược lại, CPU sụt về 0 khi service đáng lẽ phải có load cho thấy dịch vụ đã stopped nhận traffic.

**Baseline bình thường:**
- `frontend`: 0.02–0.08 cores
- `checkout`, `payment`: 0.05–0.15 cores
- `product-catalog`: 0.03–0.10 cores

**Ngưỡng bất thường:**
- > 80% CPU limit liên tục (throttling) → hiệu năng suy giảm
- Z-Score > 3.0 so với baseline 24h → sử dụng làm **fallback** khi không có IF model

**Phương pháp phát hiện:**
- **Isolation Forest (primary):** Feature `cpu_usage`.
- **Derived feature `cpu_per_rps`:** $\frac{CPU}{RPS + \varepsilon}$ — đo chi phí CPU để xử lý mỗi request, phát hiện memory leak hoặc vòng lặp vô tận khi `cpu_per_rps` tăng mà `rps` không tăng.
- **Z-Score Fallback:** $Z = \frac{x - \mu}{\sigma}$ — dùng khi không có IF model, ngưỡng $|Z| \geq 3.0$.

---

### 📊 Metric 5: Memory Usage Ratio — Tỷ Lệ Sử Dụng Bộ Nhớ

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(container_memory_working_set_bytes{container="<svc>"}) / sum(container_spec_memory_limit_bytes{container="<svc>"})` |
| **Nguồn dữ liệu** | cAdvisor → Prometheus |
| **Đơn vị** | Tỷ lệ (0.0 – 1.0) |

**Lý do lựa chọn:**
Dùng tỉ lệ (ratio) thay vì giá trị tuyệt đối để chuẩn hóa across các service có memory limit khác nhau. Memory ratio tiệm cận 1.0 (100%) sẽ dẫn đến OOMKilled — Pod bị xóa đột ngột gây mất dữ liệu trong bộ nhớ (đặc biệt nghiêm trọng với `valkey-cart`).

**Baseline bình thường:**
- Tất cả service: 0.3–0.6 (30%–60% memory limit)
- Cảnh báo sớm: > 0.75 (75%)

**Ngưỡng bất thường:**
- > 0.85 liên tục trong 15 phút → nguy cơ OOMKill cao
- `memory_growth > 0.1` trong 30 phút → memory leak

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `memory_usage`.
- **Derived feature `memory_growth`:** $memory\_usage_t - memory\_usage_{t-6}$ (delta 30 phút) — phát hiện memory leak qua xu hướng tăng dần.

---

### 📊 Metric 6: Kafka Consumer Lag — Độ Trễ Hàng Đợi Sự Kiện

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(kafka_consumer_records_lag{service_name="<svc>"}) or vector(0)` |
| **Nguồn dữ liệu** | Kafka JMX Exporter → Prometheus |
| **Đơn vị** | messages (số tin nhắn tồn đọng) |

**Lý do lựa chọn:**
Hệ thống sử dụng Kafka cho luồng sự kiện bất đồng bộ (checkout events, fraud detection signals). Kafka Lag tăng cao cho thấy consumer đang xử lý chậm hơn tốc độ producer, dẫn đến delay trong xử lý đơn hàng và fraud detection. Đây là chỉ số quan trọng với `checkout` và `fraud-detection`.

**Baseline bình thường:**
- `checkout`, `fraud-detection`: lag < 100 messages
- Các service không dùng Kafka: `vector(0)` → lag = 0 (được padding tự động)

**Ngưỡng bất thường:**
- Lag > 1000 messages liên tục → consumer có vấn đề
- `kafka_lag_growth > 500` trong 5 phút → tốc độ tích tụ quá nhanh

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `kafka_lag`.
- **Derived feature `kafka_lag_growth`:** $lag_t - lag_{t-1}$ — phát hiện tốc độ tăng, phân biệt lag ổn định với lag đang bùng phát.

---

### 📊 Metric 7: Client Error Rate — Tỷ Lệ Lỗi Phía Client (4xx)

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `vector(0)` (placeholder — mở rộng trong phiên bản tiếp theo) |
| **Nguồn dữ liệu** | Dự kiến: OTel HTTP status code 4xx |
| **Đơn vị** | errors/s |

**Lý do lựa chọn:**
4xx errors (Bad Request, Unauthorized, Not Found) phản ánh lỗi từ phía client nhưng tăng đột biến bất thường có thể chỉ ra misconfiguration API, thay đổi schema, hoặc tấn công. Được bao gồm trong feature vector để model có thể phân biệt lỗi client vs server.

**Baseline bình thường:** 0 – 0.5 errors/s (tùy nghiệp vụ)

**Ngưỡng bất thường:** > 5× baseline 1h → điều tra authentication/routing

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `client_error_rate` và `client_error_ratio`.

---

## 🟠 PHẦN 2: 7 CHỈ SỐ PHÁI SINH (Derived Features)

| # | Feature | Công thức | Mục đích |
|---|---|---|---|
| 1 | `error_ratio` | $\frac{error\_rate}{rps + \varepsilon}$ | Tỷ lệ lỗi chuẩn hóa theo tải — tránh false alarm khi load cao |
| 2 | `client_error_ratio` | $\frac{client\_error\_rate}{rps + \varepsilon}$ | Tương tự nhưng cho 4xx |
| 3 | `rolling_median_1h` | `latency_p90.rolling(12).median()` | Baseline động của latency trong 1 giờ |
| 4 | `latency_deviation` | $\frac{latency\_p90}{rolling\_median\_1h + \varepsilon}$ | Mức độ lệch latency so với chính lịch sử service |
| 5 | `rps_delta` | $rps_t - rps_{t-1}$ | Phát hiện traffic spike/drop đột ngột |
| 6 | `cpu_per_rps` | $\frac{cpu\_usage}{rps + \varepsilon}$ | Chi phí CPU/request — phát hiện inefficiency/loop |
| 7 | `memory_growth` | $mem_t - mem_{t-6}$ | Memory leak detection (delta 30 phút) |
| 8 | `kafka_lag_growth` | $lag_t - lag_{t-1}$ | Tốc độ tích tụ Kafka lag |

---

## 🟢 PHẦN 3: 4 CHỈ SỐ NGỮ CẢNH (Contextual Features)

| Feature | Giá trị | Mục đích |
|---|---|---|
| `hour_of_day` | 0–23 | Phân biệt pattern ngày/đêm |
| `day_of_week` | 0 (Mon) – 6 (Sun) | Phân biệt pattern ngày làm việc/cuối tuần |
| `is_business_hours` | 0 hoặc 1 | Flag 1 nếu 8h–18h ngày thường |
| `is_high_traffic_period` | 0 hoặc 1 | Flag 1 nếu `RPS > 100` VÀ `RPS > 1.5× median_1h` |

> **Lý do cần contextual features:** Isolation Forest cần biết ngữ cảnh để tránh báo nhầm. CPU 0.08 cores vào 3h sáng là bất thường, nhưng CPU 0.08 cores vào 10h sáng là bình thường. Không có contextual features, model sẽ fail trên data có seasonality.

---

## 🔴 PHẦN 4: SLO BURN RATE — TẦNG BẢO VỆ THỨ NHẤT

| Thuộc tính | Chi tiết |
|---|---|
| **Loại giám sát** | Reactive (SLO đang bị vi phạm) |
| **Công thức** | $\text{BurnRate} = \frac{\text{error\_rate\_window}}{\text{SLO\_target} = 0.1\%} \times 720$ |
| **Ngưỡng kích hoạt** | BurnRate ≥ **14.4×** trên **CẢ HAI** cửa sổ 5m và 1h |
| **Ý nghĩa ngưỡng** | Hệ thống đang tiêu thụ Error Budget nhanh gấp 14.4 lần mức cho phép → sẽ cạn kiệt toàn bộ budget 30 ngày trong vòng **~50 phút** |

**Lý do dùng Multi-Window (5m + 1h):**
- Cửa sổ 5m: Phát hiện nhanh sự cố mới (nhưng dễ false alarm với spike ngắn)
- Cửa sổ 1h: Xác nhận sự cố có độ bền (loại bỏ spike ngắn hạn)
- **Yêu cầu cả hai** → Precision cao, không spam cảnh báo

---

## 📋 PHẦN 5: TỔNG HỢP PHƯƠNG PHÁP PHÁT HIỆN

| Phương pháp | Áp dụng khi | Ngưỡng | Output |
|---|---|---|---|
| **SLO Burn Rate (Multi-window)** | SLO đang bị vi phạm tức thời | ≥ 14.4× (5m AND 1h) | Reactive Alert → Approve/Reject |
| **Isolation Forest (ML)** | SLO còn xanh nhưng metrics lệch | `prediction == -1` | Proactive Warning |
| **Confidence scoring** | Sau IF | score < -0.3 → HIGH; < -0.1 → MEDIUM | Phân loại rủi ro |
| **Z-Score Fallback** | Không có IF model | `|Z| ≥ 3.0` | Tạm thời |

---

## 🎯 PHẦN 6: LÝ DO CHỌN ISOLATION FOREST LÀM CORE MODEL

1. **Không cần nhãn (Unsupervised):** Không có dữ liệu lỗi lịch sử được gán nhãn sẵn trên cụm EKS mới (chỉ có từ 14/07/2026).
2. **Hiệu quả trên dữ liệu có chiều cao:** 18 features, Isolation Forest hoạt động tốt không cần giảm chiều.
3. **Tốc độ suy luận thấp:** O(n log n), phù hợp với chu kỳ quét 30 giây.
4. **Ngưỡng tự thích nghi:** Không dùng ngưỡng cứng mà học phân phối bình thường từ dữ liệu training 7 ngày.
5. **Chống drift tự động:** CronJob re-train mỗi thứ Hai 2h sáng để cập nhật baseline mới nhất.

---

*Tài liệu tham chiếu thiết kế: [CONSOLIDATED_ADR.md](./adr/CONSOLIDATED_ADR.md) — ADR-003 (Isolation Forest), ADR-004 (SLO Burn Rate)*
