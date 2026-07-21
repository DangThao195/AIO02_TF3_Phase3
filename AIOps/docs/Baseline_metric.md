# Phân Tích Bộ Chỉ Số Giám Sát (Metrics Analysis)
# AIOps Engine — Task Force 3 (Team AIO02)

> **Mục tiêu tài liệu:** Ghi nhận đầy đủ lý do lựa chọn, baseline bình thường đo từ telemetry EKS thật (ngày 14/07/2026), ngưỡng phát hiện bất thường và phương pháp áp dụng cho từng chỉ số được Engine sử dụng để huấn luyện và suy luận mô hình Isolation Forest.
>
> **Nguồn dữ liệu baseline:** `aiops-engine/datametric/*_train.csv` — dữ liệu thu thập từ cụm EKS thực tế ngày 14/07/2026, step 5 phút.

---

## 📌 Tổng Quan Kiến Trúc Thu Thập Dữ Liệu

```
Prometheus (OTLP Span Metrics + cAdvisor + Kafka)
    │
    ├── traces_span_metrics_calls_total       → RPS, Error Rate
    ├── traces_span_metrics_duration_ms_bucket→ P90 Latency
    ├── container_cpu_usage_seconds_total     → CPU Usage
    ├── container_memory_working_set_bytes    → Memory Usage
    └── kafka_consumer_records_lag            → Kafka Lag
              │
              ▼
    extract_features_realtime()  ← query_range 1 giờ, step 5m
              │
              ▼
    7 raw metrics → 7 derived features + 4 contextual = 18 features tổng cộng
              │
              ▼
    Isolation Forest Model (predict: 1 = Normal, -1 = Anomaly)
```

**Dịch vụ trọng yếu được giám sát (7 services):**
`frontend`, `checkout`, `payment`, `product-catalog`, `product-reviews`, `shipping`, `recommendation`

---

## 📊 Bảng Baseline Thực Tế Từ EKS (14/07/2026)

Các giá trị dưới đây được đọc trực tiếp từ `datametric/*_train.csv`:

| Service | RPS (req/s) | CPU (cores) | Memory (ratio) | Latency P90 (s) | Error Rate (req/s) | Kafka Lag |
|---|---|---|---|---|---|---|
| `frontend` | **4.59** | **0.0277** | **0.320** | **0.0** | **0.0** | 0.0 |
| `checkout` | **0.246** | **0.00302** | **0.189** | **0.0** | **0.0** | 0.0 |
| `payment` | **0.046** | **0.0148** | **0.537** | **0.0** | **0.0** | 0.0 |
| `product-catalog` | **2.62** | **0.00145** | **0.308** | **0.0** | **0.0** | 0.0 |
| `product-reviews` | **0.354** | **0.00450** | **0.491** | **0.0** | **0.0** | 0.0 |
| `shipping` | **0.083** | **0.000167** | **0.155** | **0.0** | **0.0** | 0.0 |
| `recommendation` | **0.304** | **0.00403** | **0.083** | **0.0** | **0.0** | 0.0 |

> **Lưu ý đơn vị:**
> - `latency_p90` lưu theo **giây** (seconds). Giá trị `0.0` = sub-millisecond, service đang idle.
> - `cpu_usage` = CPU cores tiêu thụ thực tế (không phải %).
> - `memory_usage` = tỷ lệ (0.0–1.0), tính bằng `working_set / memory_limit`.

---

## 🔵 PHẦN 1: 3 METRICS TRỌNG YẾU (≥3 theo yêu cầu Mandate #7a)

---

### 📊 Metric 1: Error Rate (Tỷ Lệ Lỗi Server-side 5xx) — **[USER-VISIBLE, ƯU TIÊN CAO NHẤT]**

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(rate(traces_span_metrics_calls_total{service_name="<svc>", span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}[5m]))` |
| **Đơn vị** | errors/s |
| **Nguồn** | OpenTelemetry Span Metrics → Prometheus |

**Lý do lựa chọn:**
Đây là "Golden Signal" quan trọng nhất — ảnh hưởng trực tiếp đến người dùng và tiêu thụ Error Budget SLO. Sự xuất hiện của error rate trên service `checkout` hoặc `payment` tương đương với giao dịch thất bại, tác động doanh thu ngay lập tức.

**Baseline bình thường (đo từ EKS 14/07/2026):**

| Service | Baseline Error Rate | Ngưỡng cảnh báo |
|---|---|---|
| `frontend` | **0.0 errors/s** | > 0.001 errors/s liên tục 2 chu kỳ |
| `checkout` | **0.0 errors/s** | > 0.001 errors/s liên tục 2 chu kỳ |
| `payment` | **0.0 errors/s** | > 0.001 errors/s liên tục 2 chu kỳ |
| `product-catalog` | **0.0 errors/s** | > 0.002 errors/s |
| `product-reviews` | **0.0 errors/s** | > 0.001 errors/s |
| `shipping` | **0.0 errors/s** | > 0.001 errors/s |
| `recommendation` | **0.0 errors/s** | > 0.001 errors/s |

**Thế nào là bất thường:**
- Error rate > 0 liên tục trong 2 chu kỳ quét (10 phút) → cần điều tra
- `error_ratio = error_rate / rps > 1%` → tỷ lệ lỗi trên tải đang cao bất thường
- **SLO Burn Rate ≥ 14.4×** (cả cửa sổ 5m VÀ 1h) → vi phạm SLO khẩn cấp

**Phương pháp phát hiện:**
- **Isolation Forest (primary):** Feature `error_rate` + derived `error_ratio`. `error_ratio` chuẩn hóa theo RPS giúp model phân biệt "lỗi 3% khi RPS = 0.25" (nghiêm trọng) với "lỗi 0.1% khi RPS = 150" (có thể chấp nhận).
- **SLO Burn Rate (secondary):** Reactive layer — kích hoạt khi lỗi tiêu thụ error budget quá nhanh.

---

### 📊 Metric 2: Latency P90 (Độ Trễ Phân Vị 90%) — **[USER-VISIBLE, ƯU TIÊN CAO]**

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="<svc>", span_kind="SPAN_KIND_SERVER"}[5m])) by (le))` |
| **Đơn vị** | **Giây (seconds)** — Prometheus Span Metrics histogram trả về milliseconds, lưu trong datametric theo giây |
| **Nguồn** | OpenTelemetry Span Metrics Histogram → Prometheus |

**Lý do lựa chọn P90 thay vì P99 hoặc P50:**
P99 quá nhạy với outlier đơn lẻ (GC pause, cold start) → false alarm cao. P50 quá mờ nhạt với sự cố ảnh hưởng 10% người dùng. P90 cân bằng: phản ánh trải nghiệm của 90% người dùng, đủ nhạy để phát hiện suy giảm hiệu suất sớm.

**Baseline bình thường (đo từ EKS 14/07/2026):**

| Service | Baseline Latency P90 | Ngưỡng cảnh báo |
|---|---|---|
| `frontend` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` (gấp 2× rolling median 1h) |
| `checkout` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` |
| `payment` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` |
| `product-catalog` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` |
| `product-reviews` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` |
| `shipping` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` |
| `recommendation` | **0.0s** (sub-ms, idle) | `latency_deviation > 2.0` |

> **Giải thích giá trị 0.0:** Cluster EKS thu thập data trong giai đoạn idle/staging (14/07/2026). Khi có traffic thực tế, latency sẽ tăng theo. Model IF học baseline từ đây và phát hiện anomaly dựa trên **độ lệch tương đối** (`latency_deviation`), không phải ngưỡng tuyệt đối.

**Thế nào là bất thường:**
- `latency_p90 > 0.5s` khi baseline là 0.0s → tăng đột biến không có lý do
- `latency_deviation = latency_p90 / (rolling_median_1h + ε) > 3.0` → lệch quá xa baseline động 1h
- Latency tăng đều đặn qua nhiều chu kỳ (SLO Erosion) → SCN-H pattern

**Phương pháp phát hiện:**
- **Isolation Forest:** Feature `latency_p90` + derived `latency_deviation`.
- `latency_deviation` dùng rolling median 1h làm ngưỡng động — tránh báo nhầm khi hệ thống scale up hợp lý.
- Không dùng ngưỡng tĩnh vì latency thay đổi theo tải.

---

### 📊 Metric 3: CPU Usage (Mức Tiêu Thụ CPU) — **[SATURATION SIGNAL]**

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(rate(container_cpu_usage_seconds_total{container="<svc>"}[5m]))` |
| **Đơn vị** | CPU cores |
| **Nguồn** | cAdvisor (Kubernetes built-in) → Prometheus |

**Lý do lựa chọn:**
CPU saturation là dấu hiệu hạ tầng quan trọng. CPU vọt cao kèm latency tăng = thread contention. CPU cao mà RPS không tăng = memory leak hoặc infinite loop (`cpu_per_rps` tăng). CPU sụt về 0 khi đáng lẽ có load = dịch vụ đã dừng nhận traffic.

**Baseline bình thường (đo từ EKS 14/07/2026):**

| Service | Baseline CPU | Ngưỡng cảnh báo |
|---|---|---|
| `frontend` | **0.0277 cores** | > 0.15 cores (gấp ~5×) |
| `checkout` | **0.00302 cores** | > 0.02 cores (gấp ~7×) |
| `payment` | **0.0148 cores** | > 0.08 cores (gấp ~5×) |
| `product-catalog` | **0.00145 cores** | > 0.01 cores (gấp ~7×) |
| `product-reviews` | **0.00450 cores** | > 0.03 cores (gấp ~7×) |
| `shipping` | **0.000167 cores** | > 0.002 cores (gấp ~12×) |
| `recommendation` | **0.00403 cores** | > 0.025 cores (gấp ~6×) |

**Thế nào là bất thường:**
- CPU vượt 5× baseline và duy trì > 2 chu kỳ (10 phút)
- `cpu_per_rps = cpu / (rps + ε)` tăng mạnh mà RPS không tăng → nghẽn xử lý nội bộ
- Z-Score > 3.0 so với baseline 24h → dùng làm fallback khi model IF không available

**Phương pháp phát hiện:**
- **Isolation Forest (primary):** Feature `cpu_usage` + derived `cpu_per_rps`.
- **Z-Score Fallback:** `Z = (cpu_t - μ_24h) / σ_24h`, kích hoạt khi `|Z| ≥ 3.0` và không có IF model.

---

### 📊 Metric 4: Memory Usage Ratio (Tỷ Lệ Sử Dụng Bộ Nhớ)

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(container_memory_working_set_bytes{container="<svc>"}) / sum(container_spec_memory_limit_bytes{container="<svc>"})` |
| **Đơn vị** | Tỷ lệ (0.0–1.0) |

**Baseline bình thường (đo từ EKS 14/07/2026):**

| Service | Baseline Memory | Ngưỡng cảnh báo |
|---|---|---|
| `frontend` | **0.320 (32.0%)** | > 0.75 (75%) hoặc `memory_growth > 0.05/30min` |
| `checkout` | **0.189 (18.9%)** | > 0.70 (70%) |
| `payment` | **0.537 (53.7%)** | > 0.85 (85%) ← đã ở mức cao, cần theo dõi |
| `product-catalog` | **0.308 (30.8%)** | > 0.75 (75%) |
| `product-reviews` | **0.491 (49.1%)** | > 0.80 (80%) |
| `shipping` | **0.155 (15.5%)** | > 0.70 (70%) |
| `recommendation` | **0.083 (8.3%)** | > 0.60 (60%) |

> **Lưu ý `payment`:** Baseline memory 53.7% — đây là service stateful với các tác vụ xử lý giao dịch. Ngưỡng cảnh báo đặt cao hơn các service stateless.

**Thế nào là bất thường:**
- Memory tăng liên tục đều đặn qua nhiều chu kỳ → memory leak (SCN-C pattern)
- `memory_growth = mem_t - mem_{t-6} > 0.05` trong 30 phút → tốc độ tích tụ bất thường
- Memory > 0.85 → nguy cơ OOMKill cao

**Phương pháp phát hiện:** Isolation Forest qua feature `memory_usage` + derived `memory_growth`.

---

### 📊 Metric 5: RPS (Tốc Độ Xử Lý Yêu Cầu)

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(rate(traces_span_metrics_calls_total{service_name="<svc>", span_kind="SPAN_KIND_SERVER"}[5m]))` |
| **Đơn vị** | req/s |

**Baseline bình thường (đo từ EKS 14/07/2026):**

| Service | Baseline RPS |
|---|---|
| `frontend` | **4.59 req/s** |
| `checkout` | **0.246 req/s** |
| `payment` | **0.046 req/s** |
| `product-catalog` | **2.625 req/s** |
| `product-reviews` | **0.354 req/s** |
| `shipping` | **0.083 req/s** |
| `recommendation` | **0.304 req/s** |

**Thế nào là bất thường:**
- Sụt giảm > 80% so với rolling median 1h → nghi ngờ service down
- `rps_delta` âm lớn đột ngột → mất kết nối hoặc upstream fail
- Tăng đột biến kèm error rate = DDoS hoặc bug loop

**Phương pháp phát hiện:** Feature `rps` + derived `rps_delta` + `is_high_traffic_period` trong Isolation Forest.

---

### 📊 Metric 6: Kafka Consumer Lag

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `sum(kafka_consumer_records_lag{service_name="<svc>"}) or vector(0)` |
| **Đơn vị** | messages (tin nhắn tồn đọng) |

**Baseline bình thường (đo từ EKS 14/07/2026):**
- Tất cả service: **0.0 messages** (không có Kafka consumer lag khi idle)
- Service có Kafka (`checkout`, `shipping`): lag < 100 messages là bình thường khi có traffic

**Thế nào là bất thường:**
- Lag > 500 messages và tăng liên tục → consumer chậm hơn producer
- `kafka_lag_growth = lag_t - lag_{t-1} > 200` trong 5 phút → tốc độ tích tụ nguy hiểm

**Phương pháp phát hiện:** Feature `kafka_lag` + derived `kafka_lag_growth`. Đặc biệt quan trọng cho `shipping` (SCN-H: INC-5 pattern).

---

### 📊 Metric 7: Client Error Rate (Lỗi 4xx)

| Thuộc tính | Chi tiết |
|---|---|
| **PromQL** | `vector(0)` (placeholder, mở rộng phase tiếp) |
| **Đơn vị** | errors/s |

**Baseline:** 0.0 errors/s. Tăng đột biến > 5× baseline → API misconfiguration hoặc security scan.

---

## 🟠 PHẦN 2: 7 ĐẶC TRƯNG PHÁI SINH (Derived Features)

| # | Feature | Công thức | Mục đích |
|---|---|---|---|
| 1 | `error_ratio` | `error_rate / (rps + ε)` | Chuẩn hóa lỗi theo tải — không báo nhầm khi tải cao |
| 2 | `client_error_ratio` | `client_error_rate / (rps + ε)` | Tương tự cho lỗi 4xx |
| 3 | `rolling_median_1h` | `latency_p90.rolling(12).median()` | Baseline động của latency trong 1 giờ |
| 4 | `latency_deviation` | `latency_p90 / (rolling_median_1h + ε)` | Lệch latency so với chính lịch sử service |
| 5 | `rps_delta` | `rps_t - rps_{t-1}` | Phát hiện spike/drop đột ngột |
| 6 | `cpu_per_rps` | `cpu_usage / (rps + ε)` | Chi phí CPU/request — phát hiện leak/loop |
| 7 | `memory_growth` | `mem_t - mem_{t-6}` (delta 30 phút) | Phát hiện memory leak qua xu hướng |
| 8 | `kafka_lag_growth` | `lag_t - lag_{t-1}` | Tốc độ tích tụ queue |

---

## 🟢 PHẦN 3: 4 ĐẶC TRƯNG NGỮ CẢNH (Contextual Features)

| Feature | Giá trị | Mục đích |
|---|---|---|
| `hour_of_day` | 0–23 | Phân biệt pattern ngày/đêm |
| `day_of_week` | 0 (Mon) – 6 (Sun) | Phân biệt ngày làm việc/cuối tuần |
| `is_business_hours` | 0 hoặc 1 | Flag 1 nếu 8h–18h ngày thường |
| `is_high_traffic_period` | 0 hoặc 1 | Flag 1 nếu `RPS > 100` VÀ `RPS > 1.5× median_1h` |

> **Tại sao cần contextual features:** CPU `0.0277 cores` lúc 3h sáng là bất thường, nhưng lúc 10h sáng là hoàn toàn bình thường. Isolation Forest không thể phân biệt nếu không có temporal context.

---

## 🔴 PHẦN 4: SLO BURN RATE — TẦNG REACTIVE

| Thuộc tính | Chi tiết |
|---|---|
| **Loại giám sát** | Reactive (SLO đang bị vi phạm) |
| **Công thức** | `BurnRate = (error_rate_window / SLO_target_0.1%) × 720` |
| **Ngưỡng kích hoạt** | BurnRate ≥ **14.4×** trên **CẢ HAI** cửa sổ 5m và 1h |
| **Ý nghĩa** | Hệ thống tiêu cạn 100% error budget 30 ngày trong ~50 phút |

**Lý do Multi-Window (5m + 1h):**
- 5m: Phát hiện nhanh sự cố mới
- 1h: Xác nhận sự cố có độ bền — loại bỏ spike ngắn < 2 phút
- Yêu cầu cả hai → Precision cao, không spam cảnh báo

---

## 📋 PHẦN 5: TỔNG HỢP PHƯƠNG PHÁP PHÁT HIỆN

| Phương pháp | Áp dụng khi | Ngưỡng | Output |
|---|---|---|---|
| **SLO Burn Rate (Multi-window)** | SLO đang bị vi phạm | ≥ 14.4× (5m AND 1h) | Reactive Alert → Slack card |
| **Isolation Forest (ML, 18 features)** | SLO còn xanh nhưng metrics lệch | `prediction == -1` | Proactive Warning |
| **Confidence scoring** | Sau IF | score < -0.3 → HIGH; < -0.1 → MEDIUM | Phân loại rủi ro tự động |
| **Z-Score Fallback** | Không có IF model | `\|Z\| ≥ 3.0` | Cảnh báo tạm thời |

---

## 🎯 PHẦN 6: LÝ DO CHỌN ISOLATION FOREST

1. **Unsupervised:** Không cần nhãn lịch sử — cụm EKS chỉ có data từ 14/07/2026, quá ít để supervised learning.
2. **Đa chiều 18 features:** Isolation Forest hoạt động tốt trên không gian chiều cao mà không cần giảm chiều.
3. **Tốc độ suy luận O(n log n):** Phù hợp với chu kỳ quét 30 giây.
4. **Baseline tự thích nghi:** Học phân phối bình thường từ data training, không dùng ngưỡng cứng.
5. **Chống drift:** CronJob re-train mỗi thứ Hai 2h sáng (UTC 19h Chủ Nhật) cập nhật baseline tuần.

Tham chiếu: [ADR-008-anomaly-detection-baseline.md](./adr/ADR-008-anomaly-detection-baseline.md)
