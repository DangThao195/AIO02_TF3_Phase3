# METRIC_ANALYSIS.md
# Phân Tích Metric - AIOps CMDR Engine
## TechX Corp · Platform Observability · Phiên bản 1.0

> **Ticket liên quan:** AIOps-01 — Phát hiện Anomaly & Cảnh báo Burn-rate SLO  
> **Trạng thái:** Active  
> **Cập nhật lần cuối:** 2026-06

---

## Mục lục

1. [Tổng quan & Mục tiêu](#1-tổng-quan--mục-tiêu)
2. [Bảng Dịch vụ Quan trọng](#2-bảng-dịch-vụ-quan-trọng)
3. [Phân tích Chi tiết 5 Metric](#3-phân-tích-chi-tiết-5-metric)
   - [Metric 1: checkout · latency_p90](#metric-1-checkout--latency_p90)
   - [Metric 2: payment · error_rate + error_ratio](#metric-2-payment--error_rate--error_ratio)
   - [Metric 3: product-catalog · memory_usage + memory_growth](#metric-3-product-catalog--memory_usage--memory_growth)
   - [Metric 4: checkout · error_rate + error_ratio](#metric-4-checkout--error_rate--error_ratio)
   - [Metric 5 (Bonus): accounting · kafka_lag](#metric-5-bonus-accounting--kafka_lag)
4. [Bảng Tổng hợp theo Golden Signal](#4-bảng-tổng-hợp-theo-golden-signal)
5. [Feature Engineering Pipeline](#5-feature-engineering-pipeline)
6. [PromQL cho từng Metric](#6-promql-cho-từng-metric)
7. [Ngưỡng Cảnh báo & Routing](#7-ngưỡng-cảnh-báo--routing)
8. [Hạn chế Đã biết & Khoảng trống](#8-hạn-chế-đã-biết--khoảng-trống)
9. [Tài liệu tham khảo](#9-tài-liệu-tham-khảo)

---

## 1. Tổng quan & Mục tiêu


### 1.1 Bối cảnh dự án

**TechX Corp** vận hành một nền tảng thương mại điện tử trên Kubernetes/EKS với kiến trúc microservice polyglot (~18 service). Toàn bộ telemetry được thu thập qua **OpenTelemetry Collector** và phân phối tới:

- **Prometheus** — metrics (time-series)
- **Jaeger** — distributed traces
- **OpenSearch** — logs tập trung
- **Grafana** — dashboards tổng hợp

Luồng chính cần bảo vệ: `user → frontend → checkout → payment → payments-db`

### 1.2 Kiến trúc 2 lớp của CMDR Engine (AIOps-01)

AIOps CMDR Engine áp dụng chiến lược phát hiện **2 lớp bổ sung nhau** để đảm bảo không bỏ sót sự cố:

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 1 – SLO Burn-Rate Monitor (Rule-Based)           │
│  • PromQL dual-window: 5m + 1h                          │
│  • Ngưỡng K = 14.4 (tương đương 2% error budget/giờ)   │
│  • Phát hiện: error spike, availability drop            │
│  • Điểm mù: latency thuần (INC-6), cold start (INC-8)  │
├─────────────────────────────────────────────────────────┤
│  LAYER 2 – Isolation Forest per-service (ML-Based)      │
│  • 7 service có model IF đã train                       │
│  • Feature vector 18 chiều (raw + derived + temporal)   │
│  • Phát hiện: pattern bất thường đa chiều               │
│  • Fallback: Z-Score CPU khi không có model IF          │
└─────────────────────────────────────────────────────────┘
              │                      │
              ▼                      ▼
       Alert → Slack           RCA → LLM Diagnostician
```

### 1.3 Mục tiêu của tài liệu này

Tài liệu được tạo theo yêu cầu của **AIOps-01** nhằm:

1. Ghi lại chi tiết **lý do chọn** từng metric đưa vào feature vector.
2. Định nghĩa **baseline bình thường** dựa trên dữ liệu CSV thực tế.
3. Xác định **ngưỡng phát hiện** rõ ràng cho từng tầng (IF score, Z-Score, burn-rate).
4. Cung cấp **PromQL chuẩn** làm nguồn duy nhất (single source of truth) cho mọi query.
5. Ghi nhận **hạn chế và khoảng trống** hiện tại để định hướng cải tiến.


---

## 2. Bảng Dịch vụ Quan trọng

Topology phụ thuộc được định nghĩa trong `services.json`:

```
frontend → [checkout, product-catalog, cart, recommendation]
checkout → [payment, shipping, currency]
payment  → [payments-db]
product-catalog → [postgresql]
cart     → [valkey-cart]
product-reviews → [llm]
accounting → [kafka]
fraud-detection → [flagd]
```

| Service | SLO Availability | SLO Latency | Error Budget | Criticality | Ghi chú |
|---|---|---|---|---|---|
| `checkout` | ≥ 99.0% | p95 < 1s | 1% | **P1** | Luồng ra tiền, ưu tiên cao nhất |
| `frontend` | ≥ 99.5% | p95 < 1s | 0.5% | **P1** | Cổng vào duy nhất (Envoy :8080) |
| `cart` | ≥ 99.5% | p95 < 500ms | 0.5% | **P1** | Mất giỏ = mất đơn hàng (INC-2) |
| `payment` | ≥ 99.0% (kế thừa) | p95 < 1s (kế thừa) | 1% | **P1** | Downstream của checkout |
| `product-catalog` | ≥ 99.5% | p95 < 1s | 0.5% | **P2** | Ảnh hưởng UX duyệt sản phẩm |
| `product-reviews` | Best-effort | N/A | Không giới hạn | **P3** | AI tóm tắt, không SLA cứng |
| `accounting` | N/A | N/A | N/A | **P2** | Consumer Kafka — trễ gây lệch sổ |
| `fraud-detection` | N/A | N/A | N/A | **P2** | Consumer Kafka — trễ gây rủi ro gian lận |
| `shipping` | N/A | N/A | N/A | **P3** | Tính phí ship — ít nhạy cảm |
| `recommendation` | N/A | N/A | N/A | **P3** | Degradation graceful |

> **Ghi chú:** P1 = mất revenue trực tiếp, P2 = ảnh hưởng UX hoặc compliance, P3 = best-effort.


---

## 3. Phân tích Chi tiết 5 Metric

---

### Metric 1: checkout · `latency_p90`

#### 3.1.1 Lý do chọn

`checkout` là service **P1 quan trọng nhất** — mọi đơn hàng đều đi qua đây. Latency của checkout tích lũy latency của toàn bộ chuỗi phụ thuộc: `payment`, `shipping`, `currency`, `cart`, `product-catalog`. Vì vậy, latency_p90 của checkout là **"early warning signal" sớm nhất** cho cascade failure.

**Bằng chứng từ lịch sử sự cố:**
- **INC-1:** DB connection pool cạn → request xếp hàng chờ kết nối → latency p95 checkout vọt lên vài giây. Không có lỗi ngay, Layer 1 (burn-rate) không trigger. Chỉ latency tăng mới phát hiện được.
- **INC-6:** GC pressure → latency tăng từ 50ms lên 5s với `error_rate = 0.0`. Đây là **điểm mù hoàn toàn của Layer 1**.
- **INC-8:** Cold start latency 3× với HTTP 200 — không error, không burn-rate, chỉ có latency lệch.

Cả ba sự cố trên đều chứng minh: **latency là tín hiệu phát hiện sớm nhất**, trước khi error_rate tăng.

#### 3.1.2 Baseline bình thường (từ `checkout_train.csv`)

Dữ liệu train thực tế 14 ngày, sample mỗi 5 phút:

| Thống kê | `latency_p90` (giây) | `rps` | `memory_usage` | `cpu_usage` |
|---|---|---|---|---|
| Mean | ~0.044 | ~18.5 | ~0.305 | ~0.121 |
| Min (quan sát) | 0.034 | ~10 | ~0.274 | ~0.050 |
| Max bình thường | ~0.065 | ~28 | ~0.347 | ~0.247 |
| Mẫu điển hình | 0.0477 | 27.1 | 0.311 | 0.136 |

> **Lưu ý quan trọng:** CSV train hiện tại là dữ liệu **synthetic** (RPS ~10–28). Môi trường production EKS thực tế có thể có baseline khác nhau đáng kể tùy load. Giá trị `latency_p90 = 0.0` xuất hiện trong một số mẫu (ví dụ timestamp `00:10:00`) là **synthetic gap** — thiếu span, không phải latency thật bằng 0.

#### 3.1.3 Ngưỡng phát hiện

| Ngưỡng | Giá trị | Phương pháp | Hành động |
|---|---|---|---|
| `latency_deviation` > 2.0 | latency hiện tại > 2× median 1h | IF Feature | MEDIUM alert |
| `latency_deviation` > 3.5 | latency hiện tại > 3.5× median 1h | IF Feature | HIGH alert → trigger RCA |
| IF score < -0.1 | Kết hợp 18 features | Isolation Forest | MEDIUM confidence |
| IF score < -0.3 | Kết hợp 18 features | Isolation Forest | HIGH confidence → page SRE |
| Z-Score latency |z| ≥ 3.0 | Z-Score fallback (window 1d) | Fallback alert |
| SLO p95 > 1s | Burn-rate K ≥ 14.4 trên 5m+1h | Layer 1 | SLO breach alert |

#### 3.1.4 Phương pháp phát hiện với code

```python
# Feature engineering cho latency_p90 — từ anomaly_detector.py
df["rolling_median_1h"] = df["latency_p90"].rolling(window=12, min_periods=1).median()
df["latency_deviation"] = df["latency_p90"] / (df["rolling_median_1h"] + 1e-5)

# Inference tại thời điểm t
feature_cols = [
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
    "client_error_rate", "kafka_lag", "error_ratio", "client_error_ratio",
    "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth",
    "kafka_lag_growth", "hour_of_day", "day_of_week",
    "is_business_hours", "is_high_traffic_period"
]
X_t = df_features[feature_cols].iloc[-1].values.reshape(1, -1)
model = iforest_models["checkout"]
score = float(model.decision_function(X_t)[0])

if score < -0.3:
    confidence = "HIGH"    # → page SRE immediately
elif score < -0.1:
    confidence = "MEDIUM"  # → log + Slack warning
else:
    confidence = "borderline"  # → monitor, no action
```


---

### Metric 2: payment · `error_rate` + `error_ratio`

#### 3.2.1 Lý do chọn

`payment` là service **P1 cuối chuỗi checkout** — lỗi ở đây đồng nghĩa với đơn hàng thất bại trực tiếp. Quan trọng hơn, payment dễ bị ảnh hưởng bởi:

- **INC-3:** Deploy thiếu readiness probe → pod nhận traffic trước khi sẵn sàng → 5xx spike trong khi checkout không lỗi. Nếu chỉ monitor checkout, sự cố này sẽ bị phát hiện muộn.
- `error_rate` (số lỗi tuyệt đối) kết hợp `error_ratio` (tỷ lệ lỗi/tổng request) tạo ra 2 góc nhìn bổ sung nhau: `error_rate` cao khi traffic lớn, `error_ratio` cao khi traffic nhỏ nhưng lỗi nhiều.

#### 3.2.2 Baseline bình thường (từ `payment_train.csv`)

Dữ liệu train thực tế:

| Thống kê | `rps` | `error_rate` | `error_ratio` | `memory_usage` | `cpu_usage` |
|---|---|---|---|---|---|
| Mean | ~18.9 | ~0.00088 | ~0.0000466 | ~0.318 | ~0.119 |
| Min | ~13.6 | ~0.000141 | ~5.25e-6 | ~0.279 | ~0.050 |
| Max bình thường | ~30.2 | ~0.00185 | ~0.000135 | ~0.352 | ~0.195 |
| Mẫu điển hình (t=0) | 13.64 | 0.001845 | 0.0001353 | 0.312 | 0.158 |

> **Lưu ý:** Dữ liệu train là synthetic — RPS ~13–30 là giá trị synthetic, không phải production thực. `error_rate` baseline rất thấp (~0.001), bất kỳ spike nào lên > 0.05 là dấu hiệu rõ ràng.

#### 3.2.3 Ngưỡng phát hiện

| Ngưỡng | Giá trị | Phương pháp | Hành động |
|---|---|---|---|
| `error_rate` > 0.05 | > 5% của tổng request | Raw signal | MEDIUM alert |
| `error_rate` > 0.20 | > 20% của tổng request | Raw signal | HIGH alert → SLO breach |
| `error_ratio` > 0.01 | Tỷ lệ lỗi/rps > 1% | Derived feature | MEDIUM |
| `error_ratio` > 0.05 | Tỷ lệ lỗi/rps > 5% | Derived feature | HIGH |
| IF score < -0.1 | Multivariate | Isolation Forest | MEDIUM confidence |
| IF score < -0.3 | Multivariate | Isolation Forest | HIGH confidence |
| Burn-rate K ≥ 14.4 | Dual window 5m+1h | Layer 1 | SLO alert ngay |

#### 3.2.4 Phương pháp phát hiện với PromQL

```promql
# PromQL: error_rate cho payment
sum(rate(traces_span_metrics_calls_total{
    service_name="payment",
    span_kind="SPAN_KIND_SERVER",
    status_code="STATUS_CODE_ERROR"
}[5m]))

# PromQL: error_ratio (tính ngoài Prometheus hoặc trong recording rule)
(
  sum(rate(traces_span_metrics_calls_total{
      service_name="payment",
      span_kind="SPAN_KIND_SERVER",
      status_code="STATUS_CODE_ERROR"
  }[5m]))
  /
  (sum(rate(traces_span_metrics_calls_total{
      service_name="payment",
      span_kind="SPAN_KIND_SERVER"
  }[5m])) + 0.00001)
)

# PromQL: SLO Burn-Rate Layer 1 (K=14.4, cửa sổ kép)
# Short window 5m (720 = 1/0.01 * 7.2)
(
  sum(rate(traces_span_metrics_calls_total{
      span_kind="SPAN_KIND_SERVER",
      status_code="STATUS_CODE_ERROR"
  }[5m])) by (service_name)
  /
  sum(rate(traces_span_metrics_calls_total{
      span_kind="SPAN_KIND_SERVER"
  }[5m])) by (service_name)
  * 720
) > 14.4
```


---

### Metric 3: product-catalog · `memory_usage` + `memory_growth`

#### 3.3.1 Lý do chọn

`product-catalog` (Go) phụ thuộc vào `postgresql` và là backend cho cả `checkout`, `frontend`, `recommendation`. Memory leak trong service Go thường biểu hiện **rất chậm** (0.3–0.5%/5 phút), không trigger bất kỳ rule alert nào trong ngắn hạn nhưng tích lũy đến OOM eviction (tương tự INC-2 với `valkey-cart`).

`memory_growth` (delta 30 phút) được thiết kế để bắt tín hiệu này, nhưng hiện tại **có giới hạn về window** (xem phần hạn chế).

#### 3.3.2 Baseline bình thường (từ `product-catalog_train.csv`)

| Thống kê | `rps` | `memory_usage` | `cpu_usage` | `latency_p90` |
|---|---|---|---|---|
| Mean | ~17.4 | ~0.299 | ~0.122 | ~0.049 |
| Min | ~6.07 | ~0.277 | ~0.039 | ~0.037 |
| Max bình thường | ~29.5 | ~0.319 | ~0.224 | ~0.065 |
| Mẫu điển hình (t=0) | 14.97 | 0.2768 | 0.0395 | 0.0502 |

Ngưỡng OOM trong Kubernetes thường xảy ra khi `memory_usage` đạt **≥ 0.90** (90% memory limit). Từ baseline ~30%, hệ thống có ~60% headroom nhưng leak liên tục sẽ lấp đầy nếu không phát hiện sớm.

#### 3.3.3 Ngưỡng phát hiện

| Ngưỡng | Giá trị | Phương pháp | Hành động |
|---|---|---|---|
| `memory_usage` > 0.70 | 70% memory limit | Raw signal | WARNING: theo dõi |
| `memory_usage` > 0.85 | 85% memory limit | Raw signal | HIGH: chuẩn bị restart |
| `memory_usage` > 0.92 | 92% memory limit | Raw signal | CRITICAL: OOM imminent |
| `memory_growth` > 0.05 | Tăng >5% trong 30 phút | Derived feature | Theo dõi leak trend |
| `memory_growth` > 0.10 | Tăng >10% trong 30 phút | Derived feature | MEDIUM alert |
| IF score < -0.3 | Multivariate | Isolation Forest | HIGH confidence |

#### 3.3.4 Phương pháp phát hiện và đề xuất CUSUM

```python
# Feature hiện tại: memory_growth (window 30 phút)
df["memory_growth"] = df["memory_usage"] - df["memory_usage"].shift(6).fillna(0)

# === ĐỀ XUẤT: CUSUM cho slow memory leak ===
# CUSUM phát hiện drift nhỏ liên tục tốt hơn threshold tĩnh
def cusum_detect(series: pd.Series, k: float = 0.003, h: float = 0.05) -> pd.Series:
    """
    CUSUM one-sided upper để phát hiện memory leak từ từ.
    k = slack (allowance) — tốc độ tăng "bình thường" cho phép mỗi bước
    h = decision threshold — tích lũy vượt ngưỡng này = anomaly
    
    Với memory_growth 0.3%/5m → k=0.003, h=0.05 → phát hiện sau ~17 mẫu (85 phút)
    vs window 30m hiện tại chỉ thấy 1.5-2.5% = trong ngưỡng bình thường
    """
    cusum_pos = pd.Series(0.0, index=series.index)
    S = 0.0
    for i in range(1, len(series)):
        delta = series.iloc[i] - series.iloc[i-1]
        S = max(0, S + delta - k)
        cusum_pos.iloc[i] = S
    return cusum_pos > h

# Sử dụng:
# df["memory_leak_cusum"] = cusum_detect(df["memory_usage"])
# Khi memory_leak_cusum = True → trigger investigation
```

```promql
# PromQL: memory_usage cho product-catalog
sum(container_memory_working_set_bytes{container="product-catalog"})
/
sum(container_spec_memory_limit_bytes{container="product-catalog"})

# PromQL: tỷ lệ memory growth theo thời gian (1h lookback)
(
  sum(container_memory_working_set_bytes{container="product-catalog"})
  -
  sum(container_memory_working_set_bytes{container="product-catalog"} offset 1h)
)
/
sum(container_spec_memory_limit_bytes{container="product-catalog"})
```


---

### Metric 4: checkout · `error_rate` + `error_ratio`

#### 3.4.1 Lý do chọn (Bổ sung trực giao với Metric 1)

Mặc dù `checkout` đã được giám sát qua `latency_p90` (Metric 1), `error_rate` và `error_ratio` của `checkout` là **tín hiệu trực giao hoàn toàn** và cần được theo dõi độc lập vì:

1. **INC-3 pattern tại checkout:** Trong một deploy thiếu liveness probe, request vào checkout mới trong khi pod đang khởi động → 5xx spike tức thì, nhưng latency có thể bình thường (fail fast < 100ms).
2. **SLO Burn-Rate:** SLO checkout availability ≥ 99.0% — error budget 1%. Công thức burn-rate cần `error_rate` trực tiếp, không phải latency.
3. **Kết hợp 2 chiều:** Sự cố thật thường làm **cả 2 tăng cùng lúc** (latency + error). Khi chỉ một chiều tăng, cần điều tra thêm.

#### 3.4.2 SLO Burn-Rate Formula

Burn-rate K = 14.4 nghĩa là: error budget đang cạn **14.4× nhanh hơn** so với tốc độ bình thường.

```
Với SLO availability = 99.0% → error_budget = 1% = 0.01

burn_rate(window) = error_rate_in_window / error_budget_per_unit_time
                 = (errors_in_5m / total_in_5m) / 0.01

K = 14.4 → Nếu burn trong cửa sổ 5m = 14.4% → error budget 1 giờ sẽ cháy hoàn toàn
         → Tương đương: error_rate ≥ 14.4% trong 5m VÀ ≥ 14.4% trong 1h
```

```python
# Tính burn rate trong code
def calculate_burn_rate(error_count: float, total_count: float, 
                        slo_target: float = 0.99) -> float:
    """
    Tính SLO error budget burn rate.
    
    Args:
        error_count: Số request lỗi trong cửa sổ thời gian
        total_count: Tổng số request trong cửa sổ thời gian
        slo_target: SLO mục tiêu (0.99 = 99%)
    
    Returns:
        burn_rate: Tốc độ tiêu error budget (K=14.4 là ngưỡng alert)
    """
    error_budget = 1.0 - slo_target  # = 0.01 cho checkout
    if total_count < 1e-5:
        return 0.0
    error_ratio = error_count / total_count
    # Nhân với 1/error_budget * normalizing_factor
    # normalizing_factor = 720 (= 1/0.01 * 7.2, window normalization)
    burn_rate = (error_ratio / error_budget)
    return burn_rate

# Trigger khi burn_rate_5m >= 14.4 AND burn_rate_1h >= 14.4
```

#### 3.4.3 Ngưỡng phát hiện

| Ngưỡng | Giá trị | Phương pháp | Hành động |
|---|---|---|---|
| `error_rate` > 0.005 | > 0.5% | Soft warning | LOG: monitoring |
| `error_rate` > 0.01 | > 1% = error budget | Hard threshold | MEDIUM alert |
| `error_rate` > 0.05 | > 5% | Raw signal | HIGH alert |
| Burn-rate 5m ≥ 14.4 | Dual window | Layer 1 | SLO Breach alert ngay |
| Burn-rate 5m ≥ 14.4 AND 1h ≥ 14.4 | Cả 2 cửa sổ | Layer 1 confirmed | Page SRE + RCA |
| IF score < -0.3 | Multivariate | Isolation Forest | HIGH confidence |


---

### Metric 5 (Bonus): accounting · `kafka_lag`

#### 3.5.1 Lý do chọn

`accounting` là **Kafka consumer** nhận event đơn hàng từ `checkout` qua Kafka topic. Kafka lag đo lường **khoảng cách giữa message được produce và message được consume** — khi lag tăng, đơn hàng chưa được ghi sổ (accounting delay), có thể dẫn tới:

- Báo cáo tài chính sai lệch nếu lag kéo dài > threshold SLA kế toán.
- **INC-5 pattern:** CPU/resource saturation làm consumer chậm lại, lag tích lũy.
- Khi lag tăng đột biến, thường là dấu hiệu consumer crash hoặc hết tài nguyên.

`kafka_lag_growth` (delta mỗi 5 phút) là feature chẩn đoán quan trọng: lag tăng đều (consumer chậm) vs lag spike đột ngột (consumer dead).

#### 3.5.2 Baseline bình thường

Không có CSV train riêng cho `accounting`. Dựa trên thiết kế hệ thống:

| Thống kê | `kafka_lag` (messages) | `kafka_lag_growth` |
|---|---|---|
| Bình thường | 0–50 messages | < 10/5m |
| Cảnh báo | 50–500 messages | 10–100/5m |
| Nguy hiểm | > 500 messages | > 100/5m hoặc tăng liên tục |
| Consumer dead | Tăng tuyến tính không dừng | > 500/5m liên tục |

#### 3.5.3 Ngưỡng phát hiện

| Ngưỡng | Giá trị | Phương pháp | Hành động |
|---|---|---|---|
| `kafka_lag` > 100 | > 100 messages tồn đọng | Raw signal | MEDIUM: theo dõi |
| `kafka_lag` > 500 | > 500 messages | Raw signal | HIGH: kiểm tra consumer |
| `kafka_lag_growth` > 50 | Tăng > 50 msg/5m | Derived feature | WARNING: consumer chậm |
| `kafka_lag_growth` > 200 | Tăng > 200 msg/5m | Derived feature | HIGH: consumer likely dead |
| Z-Score lag |z| ≥ 3.0 | Z-Score (window 1d) | Fallback alert |

#### 3.5.4 Đề xuất River HalfSpaceTrees (HST) cho online learning

`accounting` hiện **không có Isolation Forest model** (chỉ dùng Z-Score CPU fallback). Vì Kafka lag có tính chất **time-series với seasonal pattern**, River HST phù hợp hơn IF cho online detection:

```python
# === ĐỀ XUẤT: River HalfSpaceTrees cho accounting kafka_lag ===
# pip install river

from river import anomaly
from river import preprocessing

# Khởi tạo model
hst_model = anomaly.HalfSpaceTrees(
    n_trees=25,
    height=15,
    window_size=250,   # ~20 giờ tại step 5 phút
    seed=42
)

# Scaler để chuẩn hóa trước khi đưa vào model
scaler = preprocessing.StandardScaler()

def score_kafka_lag_online(
    kafka_lag: float,
    kafka_lag_growth: float,
    hour_of_day: int
) -> float:
    """
    Online anomaly scoring cho accounting kafka lag.
    Trả về score 0.0–1.0: càng gần 1.0 càng bất thường.
    
    Không cần batch train — model tự học từ stream dữ liệu.
    Phù hợp cho accounting vì không có historical CSV.
    """
    x = {
        "kafka_lag": kafka_lag,
        "kafka_lag_growth": kafka_lag_growth,
        "hour_of_day": float(hour_of_day)
    }
    # Scale
    x_scaled = scaler.learn_one(x).transform_one(x)
    # Score (learn_one cập nhật model, score_one đánh giá)
    score = hst_model.score_one(x_scaled)
    hst_model.learn_one(x_scaled)
    return score

# Ngưỡng: score > 0.8 → anomaly (tương đương IF score < -0.1)
# score > 0.95 → HIGH confidence anomaly

# Chạy trong polling loop (mỗi 5 phút):
# for metric_point in kafka_metrics_stream:
#     score = score_kafka_lag_online(
#         metric_point["kafka_lag"],
#         metric_point["kafka_lag_growth"],
#         metric_point["hour_of_day"]
#     )
#     if score > 0.8:
#         trigger_alert("accounting", "kafka_lag", score)
```

```promql
# PromQL: kafka_lag cho accounting
sum(kafka_consumer_records_lag{service_name="accounting"})

# PromQL: kafka_lag_growth (delta 5 phút)
sum(kafka_consumer_records_lag{service_name="accounting"})
-
sum(kafka_consumer_records_lag{service_name="accounting"} offset 5m)
```


---

## 4. Bảng Tổng hợp theo Golden Signal

Google SRE định nghĩa **4 Golden Signals**: Latency, Traffic, Errors, Saturation. Bảng dưới ánh xạ toàn bộ 18 feature hiện tại theo framework này:

| Golden Signal | Feature(s) | Service(s) được bảo vệ | Mức độ phủ | Ghi chú |
|---|---|---|---|---|
| **Latency** | `latency_p90`, `latency_deviation`, `rolling_median_1h` | checkout, payment, product-catalog, frontend, shipping | ✅ Đầy đủ | Thiếu p95 (SLO dùng p95, model dùng p90) |
| **Traffic** | `rps`, `rps_delta`, `is_high_traffic_period` | Tất cả 7 service có IF | ⚠️ Một phần | `is_high_traffic_period` luôn = 0 với synthetic data |
| **Errors** | `error_rate`, `error_ratio`, `client_error_rate`, `client_error_ratio` | Tất cả 7 service | ⚠️ Suy yếu | `client_error_rate` = vector(0) → 2 feature vô dụng |
| **Saturation** | `cpu_usage`, `memory_usage`, `cpu_per_rps`, `memory_growth`, `kafka_lag`, `kafka_lag_growth` | Tất cả 7 service | ✅ Khá tốt | `memory_growth` window 30m quá ngắn cho slow leak |
| **Context** | `hour_of_day`, `day_of_week`, `is_business_hours` | Tất cả 7 service | ✅ Đầy đủ | Temporal features hoạt động tốt |

**Phân tích khoảng trống theo Golden Signal:**

- **Latency:** SLO cam kết p95 nhưng model chỉ có p90 → khoảng trống ở đuôi phân phối (5% request chậm nhất không được giám sát đúng).
- **Traffic:** `is_high_traffic_period` với ngưỡng hardcoded `rps > 100` không bao giờ trigger cho checkout (RPS synthetic ~10–28), payment (RPS ~14–30).
- **Errors:** `client_error_rate = vector(0)` là hardcoded trong PromQL — signal này không có giá trị thực.
- **Saturation:** Kafka lag chỉ có giá trị cho service sử dụng Kafka (`accounting`, `fraud-detection`, `checkout` producer). Với các service khác, feature này luôn = 0.


---

## 5. Feature Engineering Pipeline

Pipeline chuyển đổi từ raw telemetry (Prometheus) sang 18 features đưa vào Isolation Forest:

```
Prometheus (PromQL)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  RAW SIGNALS (7 features)                                   │
│                                                             │
│  rps            ← traces_span_metrics_calls_total [5m rate] │
│  error_rate     ← traces_span_metrics_calls_total [ERROR]   │
│  client_error_rate ← vector(0) ⚠️ LUÔN BẰNG 0             │
│  latency_p90    ← traces_span_metrics_duration_ms_bucket    │
│  cpu_usage      ← container_cpu_usage_seconds_total [5m]   │
│  memory_usage   ← working_set_bytes / spec_limit_bytes      │
│  kafka_lag      ← kafka_consumer_records_lag (or 0)         │
└─────────────────────────────────────────────────────────────┘
       │
       ▼ feature_engineering()
┌─────────────────────────────────────────────────────────────┐
│  DERIVED FEATURES (7 features)                              │
│                                                             │
│  error_ratio         ← error_rate / (rps + 1e-5)           │
│  client_error_ratio  ← client_error_rate / (rps + 1e-5)    │
│                        ⚠️ LUÔN BẰNG 0 (vì client_error_rate=0) │
│  rolling_median_1h   ← latency_p90.rolling(12).median()    │
│  latency_deviation   ← latency_p90 / (rolling_median_1h + 1e-5) │
│  rps_delta           ← rps - rps.shift(1)                  │
│  cpu_per_rps         ← cpu_usage / (rps + 1e-5)            │
│  memory_growth       ← memory_usage - memory_usage.shift(6) │
│                        (delta 30 phút = 6 samples × 5m)    │
│  kafka_lag_growth    ← kafka_lag - kafka_lag.shift(1)       │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  TEMPORAL FEATURES (4 features)                             │
│                                                             │
│  hour_of_day         ← timestamp.dt.hour (0–23)            │
│  day_of_week         ← timestamp.dt.weekday (0=Mon, 6=Sun)  │
│  is_business_hours   ← (8 ≤ hour ≤ 18) AND (weekday < 5)   │
│  is_high_traffic_period ← (rps > 100) AND                  │
│                           (rps > 1.5 × rolling_median_rps)  │
│                           ⚠️ LUÔN BẰNG 0 với RPS thực < 30  │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  ISOLATION FOREST INFERENCE                                 │
│                                                             │
│  X_t = [18 features].iloc[-1].reshape(1, -1)               │
│  score = model.decision_function(X_t)[0]                   │
│  prediction = model.predict(X_t)[0]  # 1=Normal, -1=Anomaly│
│                                                             │
│  score < -0.3 → HIGH confidence anomaly                    │
│  score < -0.1 → MEDIUM confidence anomaly                  │
│  else         → borderline (monitor only)                  │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
   CMDR Engine → RCA → LLM Diagnostician → Slack Alert
```

**Ghi chú về các feature có vấn đề (đánh dấu ⚠️):**

| Feature | Vấn đề | Ảnh hưởng |
|---|---|---|
| `client_error_rate` | Hardcoded `vector(0)` trong PromQL | Luôn = 0, lãng phí 1 slot feature |
| `client_error_ratio` | Tính từ `client_error_rate` = 0 | Luôn = 0, lãng phí thêm 1 slot nữa |
| `is_high_traffic_period` | Ngưỡng `rps > 100` không bao giờ đúng với dữ liệu thực | Luôn = 0 |

3/18 features đang **không mang thông tin** (constant = 0), tương đương 16.7% chiều vector bị lãng phí.


---

## 6. PromQL cho từng Metric

Đây là **nguồn chân lý duy nhất (single source of truth)** cho tất cả PromQL được sử dụng trong CMDR Engine. Template `{service}` được thay thế bằng tên service thực tế khi runtime.

### 6.1 Throughput (Traffic)

```promql
# rps — requests per second (server spans)
sum(rate(traces_span_metrics_calls_total{
    service_name="{service}",
    span_kind="SPAN_KIND_SERVER"
}[5m]))
```

### 6.2 Error Signals

```promql
# error_rate — absolute error rate
sum(rate(traces_span_metrics_calls_total{
    service_name="{service}",
    span_kind="SPAN_KIND_SERVER",
    status_code="STATUS_CODE_ERROR"
}[5m]))

# client_error_rate — hiện tại hardcoded, cần fix
# TODO: thay vector(0) bằng query HTTP 4xx thực
vector(0)
# Proposed fix (xem Recommend.md):
# sum(rate(http_requests_total{service="{service}", status=~"4.."}[5m]))
```

### 6.3 Latency

```promql
# latency_p90
histogram_quantile(0.90,
    sum(rate(
        traces_span_metrics_duration_milliseconds_bucket{
            service_name="{service}",
            span_kind="SPAN_KIND_SERVER"
        }[5m]
    )) by (le)
)

# latency_p95 (cần bổ sung để match SLO — xem Recommend.md)
histogram_quantile(0.95,
    sum(rate(
        traces_span_metrics_duration_milliseconds_bucket{
            service_name="{service}",
            span_kind="SPAN_KIND_SERVER"
        }[5m]
    )) by (le)
)
```

### 6.4 Resource Saturation

```promql
# cpu_usage — container CPU usage rate
sum(rate(container_cpu_usage_seconds_total{
    container="{service}"
}[5m]))

# memory_usage — % of memory limit used
sum(container_memory_working_set_bytes{container="{service}"})
/
sum(container_spec_memory_limit_bytes{container="{service}"})

# kafka_lag — consumer lag (0 nếu service không dùng Kafka)
(sum(kafka_consumer_records_lag{service_name="{service}"}) or vector(0))
```

### 6.5 SLO Burn-Rate (Layer 1)

```promql
# Burn-rate short window 5m (checkout SLO = 99.0%, error_budget = 1%)
(
  sum(rate(traces_span_metrics_calls_total{
      service_name="checkout",
      span_kind="SPAN_KIND_SERVER",
      status_code="STATUS_CODE_ERROR"
  }[5m]))
  /
  (sum(rate(traces_span_metrics_calls_total{
      service_name="checkout",
      span_kind="SPAN_KIND_SERVER"
  }[5m])) + 1e-5)
  * 100  -- chuyển sang %
) > 14.4

# Burn-rate long window 1h (dual-window confirmation)
(
  sum(rate(traces_span_metrics_calls_total{
      service_name="checkout",
      span_kind="SPAN_KIND_SERVER",
      status_code="STATUS_CODE_ERROR"
  }[1h]))
  /
  (sum(rate(traces_span_metrics_calls_total{
      service_name="checkout",
      span_kind="SPAN_KIND_SERVER"
  }[1h])) + 1e-5)
  * 100
) > 14.4

# All-services burn-rate (dùng trong check_slo_burn_rate())
(
  sum(rate(traces_span_metrics_calls_total{
      span_kind="SPAN_KIND_SERVER",
      status_code="STATUS_CODE_ERROR"
  }[5m])) by (service_name)
  /
  sum(rate(traces_span_metrics_calls_total{
      span_kind="SPAN_KIND_SERVER"
  }[5m])) by (service_name)
  * 720
) > 14.4
```

### 6.6 Z-Score Fallback (Layer 2 Fallback)

```promql
# Mean của metric trong 1 ngày
avg_over_time(
    (sum(rate(container_cpu_usage_seconds_total{container="{service}"}[5m])))[1d:5m]
)

# Stddev của metric trong 1 ngày
stddev_over_time(
    (sum(rate(container_cpu_usage_seconds_total{container="{service}"}[5m])))[1d:5m]
)
```


---

## 7. Ngưỡng Cảnh báo & Routing

Bảng dưới tổng hợp tất cả ngưỡng alert và routing action tương ứng. "Routing" là hành động CMDR Engine thực hiện sau khi phát hiện.

| Service | Metric/Signal | Ngưỡng WARNING | Ngưỡng HIGH | Ngưỡng CRITICAL | Routing |
|---|---|---|---|---|---|
| `checkout` | `latency_p90` | deviation > 2.0× | deviation > 3.5× | IF score < -0.3 | MEDIUM → Slack log; HIGH → Page SRE + RCA |
| `checkout` | `error_rate` | > 0.5% | > 1.0% (error budget) | Burn-rate ≥ 14.4 | MEDIUM → Slack; CRITICAL → immediate page |
| `checkout` | SLO burn-rate | K > 5 | K > 10 | K ≥ 14.4 (5m+1h) | Layer 1 trigger → full CMDR pipeline |
| `payment` | `error_rate` | > 1% | > 5% | > 20% | HIGH → page immediately (P1 service) |
| `payment` | `error_ratio` | > 0.5% | > 1% | > 5% | HIGH → RCA checkout chain |
| `product-catalog` | `memory_usage` | > 70% | > 85% | > 92% | WARNING → monitor; HIGH → prep restart |
| `product-catalog` | `memory_growth` | > 5%/30m | > 10%/30m | CUSUM drift | WARNING → trend report; HIGH → alert |
| `cart` | `error_rate` | > 0.5% | > 1% | > 5% | HIGH → check valkey-cart (INC-2 history) |
| `cart` | `memory_usage` | > 75% | > 88% | > 95% | CRITICAL → check valkey OOM risk |
| `accounting` | `kafka_lag` | > 100 msgs | > 500 msgs | Growth > 200/5m | MEDIUM → investigate consumer |
| `accounting` | `kafka_lag_growth` | > 50/5m | > 100/5m | > 200/5m | HIGH → consumer likely dead |
| ALL services | IF score | score < -0.1 | score < -0.3 | N/A | MEDIUM/HIGH per score range |
| ALL services | Z-Score CPU | \|z\| > 2.0 | \|z\| > 3.0 | \|z\| > 5.0 | Fallback (khi không có IF model) |

**Routing logic trong CMDR Engine:**

```
IF Layer 1 (burn-rate) triggered:
    → immediate: collect evidence (Jaeger traces + OpenSearch logs)
    → run Layer 2 IF check for all upstream services
    → LLM diagnosis with collected evidence
    → Slack card with Approve/Reject remediation button
    → wait for human approval (AIOps-04 Safety Gate)

ELIF Layer 2 (IF score < -0.3, HIGH):
    → collect evidence
    → LLM diagnosis
    → Slack notification (MEDIUM urgency)
    → suggested remediation (no auto-execute without approval)

ELIF Layer 2 (IF score < -0.1, MEDIUM):
    → log anomaly
    → Slack notification (LOW urgency)
    → continue monitoring

ELSE (borderline or normal):
    → log only, no alert
```


---

## 8. Hạn chế Đã biết & Khoảng trống

Bảng dưới liệt kê **5 khoảng trống quan trọng nhất** trong thiết kế giám sát hiện tại, với đề xuất giải pháp cụ thể. Đây là đầu vào trực tiếp cho `Recommend.md`.

| # | Khoảng trống | Ví dụ sự cố bị bỏ sót | Đề xuất giải pháp | Ưu tiên |
|---|---|---|---|---|
| **G1** | **Layer 1 mù với latency-only anomaly** | INC-6: GC pressure, latency 50ms→5s, `error_rate = 0.0` → Layer 1 không trigger. INC-8: cold start 3×, HTTP 200 → Layer 1 hoàn toàn không phát hiện. | Thêm `latency_p95` SLO alert rule độc lập: `latency_p95 > 1s AND sustained > 5m → page`. Thêm feature `latency_growth` (delta 15–30m) vào IF vector. | **P1 · Gấp** |
| **G2** | **`client_error_rate` = 0 làm lãng phí 2/18 features** | Mọi service. `client_error_rate` hardcoded `vector(0)` → `client_error_ratio` cũng = 0. 2 features không mang thông tin, làm nhiễu IF model. | Thay `vector(0)` bằng PromQL thực cho HTTP 4xx: `sum(rate(http_requests_total{status=~"4.."}[5m]))`. Hoặc xóa và thay bằng `latency_growth` + `memory_growth_2h`. | **P1 · Gấp** |
| **G3** | **`memory_growth` window 30m quá ngắn cho slow leak** | Leak tốc độ 0.3–0.5%/5m → chỉ tăng 1.5–2.5% trong 30m, nằm trong ngưỡng bình thường. CUSUM sẽ phát hiện sau ~85 phút. | Thêm `memory_growth_2h = memory_usage - memory_usage.shift(24)` song song với `memory_growth_30m`. Implement CUSUM như mô tả trong Metric 3. | **P2 · Sprint tiếp** |
| **G4** | **Không có cross-service features → cascade blind** | INC-1: checkout chậm do payments-db, nhưng IF model checkout không biết DB đang bị gì. Phát hiện muộn 10–15 phút so với lý tưởng. | Thêm upstream latency feature: `checkout_to_payment_latency` từ Jaeger span. Hoặc tổng hợp `downstream_error_rate` = sum error của services phụ thuộc. | **P2 · Sprint tiếp** |
| **G5** | **Không có deployment context → false positive khi deploy** | INC-3: payment errors trong rolling update hoàn toàn bình thường (pod chưa ready). IF/burn-rate trigger nhưng không phải sự cố thật. Gây alert fatigue. | Thêm feature `is_deployment_window` từ K8s Deployment events: khi có rolling update đang xảy ra, giảm sensitivity hoặc suppress alert 5–10 phút. | **P2 · Sprint tiếp** |

### 8.1 Ma trận phủ sóng sự cố

| Sự cố | Layer 1 (Burn-rate) | Layer 2 (IF) | Phát hiện? | Điểm mù nào |
|---|---|---|---|---|
| INC-1: checkout slow, DB pool exhausted | ⚠️ Muộn (latency không trigger burn-rate) | ✅ Phát hiện qua latency_deviation | ⚠️ Muộn ~5–10m | G1, G4 |
| INC-2: cart OOM, valkey eviction | ✅ error_rate spike | ✅ memory_usage + error spike | ✅ Phát hiện | — |
| INC-3: payment 5xx during deploy | ✅ Trigger ngay | ✅ error_ratio spike | ✅ Nhưng false positive | G5 |
| INC-6: GC pressure, latency only | ❌ Không phát hiện | ⚠️ Chỉ nếu latency_deviation đủ cao | ⚠️ Rủi ro bỏ sót | G1 |
| INC-8: cold start 3×, HTTP 200 | ❌ Không phát hiện | ⚠️ Phụ thuộc latency_deviation | ⚠️ Rủi ro bỏ sót | G1 |


---

## 9. Tài liệu tham khảo

### Nguồn nội bộ

| Tài liệu | Đường dẫn | Nội dung |
|---|---|---|
| AIOps Backlog | `AIOps/docs/backlog_aiops.md` | Định nghĩa task AIOps-01, priority scoring |
| Service Topology | `AIOps/aiops-engine/services.json` | Dependency graph đầy đủ |
| SLO Definitions | `AIE1/onboarding/SLO.md` | Cam kết SLO theo luồng |
| Architecture | `AIE1/onboarding/ARCHITECTURE.md` | 18 services, ngôn ngữ, phụ thuộc |
| Incident History | `AIE1/onboarding/INCIDENT_HISTORY.md` | INC-1, INC-2, INC-3 chi tiết |
| Anomaly Detector | `AIOps/aiops-engine/anomaly_detector.py` | Implementation Layer 1 + Layer 2 |
| Training Script | `AIOps/aiops-engine/train_anomaly_model_local.py` | Feature engineering + IF training |
| Training Data | `AIOps/aiops-engine/data/checkout_train.csv` | Baseline values checkout |
| Training Data | `AIOps/aiops-engine/data/payment_train.csv` | Baseline values payment |
| Training Data | `AIOps/aiops-engine/data/product-catalog_train.csv` | Baseline values product-catalog |
| Budget | `AIE1/onboarding/BUDGET.md` | ~$300/week budget constraint |

### Tài liệu kỹ thuật bên ngoài

| Tài liệu | Mô tả |
|---|---|
| Google SRE Book — Chapter 6 | Monitoring Distributed Systems, 4 Golden Signals |
| Prometheus documentation | PromQL reference, histogram_quantile, rate() |
| scikit-learn IsolationForest | `contamination`, `decision_function`, scoring semantics |
| River library — HalfSpaceTrees | Online anomaly detection for streaming time-series |
| Alerting on SLOs (Google SRE Workbook) | Multi-window burn-rate alerting, K=14.4 derivation |
| OpenTelemetry Semantic Conventions | `traces_span_metrics_*` metric naming |

### Định nghĩa thuật ngữ

| Thuật ngữ | Định nghĩa |
|---|---|
| **SLO** | Service Level Objective — mục tiêu chất lượng dịch vụ |
| **Error Budget** | 1 - SLO target = phần "được phép lỗi" |
| **Burn-rate K** | Tốc độ tiêu error budget so với tốc độ bình thường |
| **Isolation Forest** | Thuật toán phát hiện bất thường không giám sát, isolate outlier |
| **decision_function** | IF output: âm = bất thường, 0 = ranh giới, dương = bình thường |
| **contamination** | Tỷ lệ outlier ước tính trong tập train (0.03 = 3%) |
| **latency_deviation** | latency hiện tại / rolling median 1h — đo độ lệch tương đối |
| **CUSUM** | Cumulative Sum Control Chart — phát hiện drift nhỏ liên tục |
| **HST** | HalfSpaceTrees (River) — online anomaly detection tree ensemble |

---

*Tài liệu này được tạo theo yêu cầu ticket **AIOps-01** và phản ánh trạng thái hệ thống tại thời điểm ghi nhận. Mọi thay đổi feature vector hoặc ngưỡng alert cần được cập nhật tại đây đồng thời với code.*

*Xem thêm: [`Recommend.md`](Recommend.md) — Đánh giá chi tiết chất lượng feature vector hiện tại và 7 đề xuất cải tiến.*
