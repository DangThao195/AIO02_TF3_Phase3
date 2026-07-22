# MANDATE-07a — Phân Tích Chỉ Số Giám Sát Trọng Yếu
## AIOps Engine · Anomaly Detection · Task Force 3 (Team AIO02)

> **Ticket loại:** Analysis / Design Document
> **Trạng thái:** v2 — Cập nhật baseline từ EKS thực tế
> **Tác giả:** AIO02 — AIE1 Team
> **Ngày tạo:** 20/07/2026
> **Cập nhật lần cuối:** 21/07/2026 — Align toàn bộ baseline với `datametric/*_train.csv` (EKS 14–17/07/2026)

---

## 📌 Nguồn Dữ Liệu Baseline

> **Tất cả baseline trong tài liệu này được đo trực tiếp từ `datametric/*_train.csv`** — dữ liệu thu thập qua `pull_live_prometheus_data.py` từ cụm EKS thực tế, giai đoạn **14/07/2026 00:00 → 17/07/2026 09:30**, step 5 phút, 979 data points/service.
>
> Giá trị baseline sử dụng **median** (không phải mean) vì median bền vững hơn với spike ngắn hạn và outlier.
> Mean được ghi kèm để tham khảo.

---

## 1. Phạm Vi & Mục Tiêu

Tài liệu xác định **5 chỉ số giám sát (metrics) trọng yếu** làm input cho mô hình **Isolation Forest** của AIOps Engine,
với baseline đo từ EKS thực tế và ngưỡng phát hiện bất thường được căn chỉnh theo đó.

### Dịch vụ ưu tiên phân tích

| Dịch vụ | Lý do ưu tiên |
|---|---|
| **`checkout`** | SLO ≥ 99.0% (cao nhất hệ thống), trực tiếp tạo doanh thu; liên quan INC-1 |
| **`payment`** | Xử lý giao dịch tài chính, service stateful; liên quan INC-3 |
| **`product-catalog`** | SLO non-5xx ≥ 99.5%, upstream của toàn luồng duyệt/tìm sản phẩm |

---

## 2. Bảng Baseline Thực Tế (EKS 14–17/07/2026)

| Service | RPS median | RPS max | CPU median (cores) | CPU max | MEM median | MEM max | Latency P90 median (ms) |
|---|---|---|---|---|---|---|---|
| `frontend` | **4.587** | 89.74 | **0.02796** | 0.395 | **0.348** | 1.022 | **33.76** |
| `checkout` | **0.246** | 2.68 | **0.00389** | 0.023 | **0.203** | 0.332 | **41.20** |
| `payment` | **0.088** | 2.31 | **0.01975** | 0.032 | **0.345** | 0.651 | **1.80** |
| `product-catalog` | **2.625** | 44.30 | **0.00495** | 0.042 | **0.210** | 0.578 | **2.50** |
| `product-reviews` | **0.354** | 3.71 | **0.01959** | 0.143 | **0.532** | 1.317 | **5.65** |
| `recommendation` | **0.304** | 3.65 | **0.00897** | 0.068 | **0.088** | 0.190 | **5.76** |
| `shipping` | **0.100** | 4.88 | **0.00072** | 0.004 | **0.071** | 0.156 | **5.08** |

> **Lưu ý đơn vị:**
> - `latency_p90` trong CSV lưu theo **milliseconds**.
> - `cpu_usage` = CPU cores thực tế tiêu thụ (không phải %).
> - `memory_usage` = tỷ lệ 0.0–1.0 (`working_set / memory_limit`). `frontend` và `product-reviews` có lúc > 1.0 do memory limit chưa được set chính xác trên cluster staging.
> - `error_rate` = 0.0 errors/s trên tất cả service trong giai đoạn thu thập (hệ thống ổn định).
> - `kafka_lag` = 0.0 trên tất cả service (không có consumer lag).


---

## 3. Phân Tích Chi Tiết Từng Metric

---

### Metric 1 — `error_rate` · Error Rate (Tỷ Lệ Lỗi Server-side 5xx)

**Service áp dụng:** Tất cả 7 service

#### Lý Do Lựa Chọn

`error_rate` là Golden Signal trực tiếp nhất — mỗi lỗi 5xx đồng nghĩa một request thất bại và tiêu Error Budget SLO.
- **Checkout SLO ≥ 99.0%:** Error budget chỉ 1% — bất kỳ chuỗi lỗi kéo dài > 1 chu kỳ đều cần điều tra.
- **INC-1:** tỷ lệ đặt hàng thành công tụt ~95% (error rate ~5%) vào giờ cao điểm.
- **INC-3:** lỗi thanh toán spike ngắn trong lúc deploy.

#### Baseline Thực Tế (EKS 14–17/07/2026)

| Service | Baseline Error Rate | Ngưỡng cảnh báo |
|---|---|---|
| `frontend` | **0.0 errors/s** (median) | > 0.001 errors/s liên tục 2 chu kỳ (10 phút) |
| `checkout` | **0.0 errors/s** (median) | > 0.001 errors/s liên tục 2 chu kỳ |
| `payment` | **0.0 errors/s** (median) | > 0.001 errors/s — bất kỳ lỗi nào đều là sự kiện nghiêm trọng |
| `product-catalog` | **0.0 errors/s** (median) | > 0.002 errors/s |
| `product-reviews` | **0.0 errors/s** (median) | > 0.001 errors/s |
| `shipping` | **0.0 errors/s** (median) | > 0.001 errors/s |
| `recommendation` | **0.0 errors/s** (median) | > 0.001 errors/s |

> **Lưu ý:** Trong 979 data points thực tế, checkout có max error_rate = 0.1625 errors/s (spike cực ngắn), frontend max = 0.089 errors/s. Đây là anomaly spike — không phải baseline bình thường.

#### Ngưỡng Bất Thường

| Điều kiện | Mức độ |
|---|---|
| `error_rate > 0` liên tục ≥ 2 chu kỳ trên `checkout` / `payment` | **WARNING** |
| `error_ratio = error_rate / rps > 1.0%` trên service trọng yếu | **WARNING** |
| `error_ratio > 2.0%` | **CRITICAL** |
| SLO Burn Rate ≥ 14.4× trên cả cửa sổ 5m VÀ 1h | **CRITICAL** |

#### Phương Pháp Phát Hiện

- **Primary:** Isolation Forest — features `error_rate` + `error_ratio`
- **Secondary:** SLO Burn Rate multi-window (reactive)
- **Fallback:** Z-Score `|Z| ≥ 3.0` khi không có IF model


---

### Metric 2 — `latency_p90` · Độ Trễ Phân Vị 90 (ms)

**Service áp dụng chính:** `checkout`, `product-catalog`, `frontend`, `payment`

#### Lý Do Lựa Chọn

P90 phản ánh trải nghiệm của 90% người dùng — đủ nhạy để phát hiện suy giảm sớm, ít bị nhiễu bởi outlier đơn lẻ hơn P99.

#### Baseline Thực Tế (EKS 14–17/07/2026)

| Service | Median P90 (ms) | Mean P90 (ms) | Max P90 (ms) | Ngưỡng WARNING |
|---|---|---|---|---|
| `frontend` | **33.76 ms** | 24.06 ms | 93.05 ms | > 200 ms hoặc `latency_deviation > 2.0` |
| `checkout` | **41.20 ms** | 486.07 ms* | 15,000 ms* | > 500 ms hoặc `latency_deviation > 2.0` |
| `payment` | **1.80 ms** | 1.15 ms | 6.40 ms | > 50 ms hoặc `latency_deviation > 2.0` |
| `product-catalog` | **2.50 ms** | 2.09 ms | 17.13 ms | > 50 ms hoặc `latency_deviation > 2.0` |
| `product-reviews` | **5.65 ms** | 546.32 ms* | 6,753.97 ms* | > 200 ms hoặc `latency_deviation > 2.0` |
| `recommendation` | **5.76 ms** | 4.17 ms | 60.00 ms | > 100 ms hoặc `latency_deviation > 2.0` |
| `shipping` | **5.08 ms** | 9.03 ms | 3,200 ms* | > 100 ms hoặc `latency_deviation > 2.0` |

> **(*) Mean >> Median:** `checkout`, `product-reviews`, `shipping` có mean bị kéo lên rất cao bởi một số spike outlier cực lớn (max 15s, 6.7s, 3.2s). Đây là lý do phải dùng **median làm baseline**, không phải mean. Model IF sẽ học phân phối thực tế từ toàn bộ 979 data points.

#### Ngưỡng Bất Thường

| Điều kiện | Mức độ |
|---|---|
| `latency_deviation = latency_p90 / (rolling_median_1h + ε) > 2.0` | **WARNING** |
| `latency_deviation > 4.0` | **CRITICAL** |
| `latency_p90 > 500 ms` trên `checkout` | **WARNING** (SLO erosion) |
| `latency_p90 > 1000 ms` trên bất kỳ service trọng yếu | **CRITICAL** |

#### Phương Pháp Phát Hiện

- **Primary:** Isolation Forest — features `latency_p90` + `latency_deviation` (rolling median 1h = 12 data points)
- **Fallback:** Static threshold — `latency_p90 > 1s` trên `checkout` / `product-catalog`


---

### Metric 3 — `cpu_usage` · Mức Tiêu Thụ CPU (cores)

**Service áp dụng chính:** `checkout`, `payment`, `product-catalog`

#### Lý Do Lựa Chọn

CPU saturation là dấu hiệu cảnh báo sớm 5–15 phút trước khi latency và error rate tăng:
- CPU cao + RPS ổn định → nghi ngờ memory pressure, retry loop, deadlock (`cpu_per_rps` tăng).
- CPU spike + error rate spike đồng thời → deployment issue (INC-3 pattern).
- CPU sụt về 0 khi có load → pod crash hoặc OOMKill.

#### Baseline Thực Tế (EKS 14–17/07/2026)

| Service | CPU median (cores) | CPU mean (cores) | CPU max (cores) | Ngưỡng WARNING |
|---|---|---|---|---|
| `frontend` | **0.02796** | 0.04180 | 0.39516 | > 0.14 cores (5× median) |
| `checkout` | **0.00389** | 0.00459 | 0.02294 | > 0.020 cores (5× median) |
| `payment` | **0.01975** | 0.01891 | 0.03205 | > 0.099 cores (5× median) |
| `product-catalog` | **0.00495** | 0.00532 | 0.04165 | > 0.025 cores (5× median) |
| `product-reviews` | **0.01959** | 0.01983 | 0.14323 | > 0.098 cores (5× median) |
| `recommendation` | **0.00897** | 0.00929 | 0.06774 | > 0.045 cores (5× median) |
| `shipping` | **0.00072** | 0.00072 | 0.00436 | > 0.004 cores (5× median) |

> **Lưu ý:** CPU median và mean rất gần nhau ở hầu hết service — phân phối CPU ổn định hơn latency. Ngoại lệ là `frontend` (mean 0.042 vs median 0.028) do một số burst ngắn kéo mean lên.

#### Ngưỡng Bất Thường

| Điều kiện | Mức độ |
|---|---|
| `cpu_usage > 5× rolling_median_1h` liên tục ≥ 2 chu kỳ | **WARNING** |
| `cpu_per_rps > 3× rolling_median_1h` trong khi RPS ổn định | **WARNING** (nghẽn nội bộ) |
| `cpu_per_rps` tăng đồng thời với `latency_deviation > 2.0` | **CRITICAL** |
| `cpu_usage` sụt > 80% median trong khi RPS không sụt | **CRITICAL** (pod down) |

#### Phương Pháp Phát Hiện

- **Primary:** Isolation Forest — features `cpu_usage` + `cpu_per_rps`
- **Fallback:** Z-Score `|Z| ≥ 3.0` so với baseline 24h


---

### Metric 4 — `memory_usage` · Tỷ Lệ Sử Dụng Bộ Nhớ (0.0–1.0)

**Service áp dụng chính:** `payment`, `product-reviews`, `checkout`

#### Lý Do Lựa Chọn

Memory leak biểu hiện qua xu hướng tăng đều đặn — vô hình với alert ngưỡng tĩnh theo dõi giá trị tức thời:
- **`payment`** là service stateful (connection pool, transaction context) — nguy cơ OOMKill cao nhất.
- **`product-reviews`** gọi LLM tạo tóm tắt review — response buffer có thể tích lũy nếu stream chưa đóng.
- **INC-2:** pod reschedule do memory pressure → state in-memory bị mất.

#### Baseline Thực Tế (EKS 14–17/07/2026)

| Service | MEM median | MEM mean | MEM max | Ngưỡng WARNING |
|---|---|---|---|---|
| `frontend` | **0.348 (34.8%)** | 0.356 | 1.022* | > 0.75 hoặc `memory_growth > 0.05/30 phút` |
| `checkout` | **0.203 (20.3%)** | 0.207 | 0.332 | > 0.70 |
| `payment` | **0.345 (34.5%)** | 0.404 | 0.651 | > 0.80 ← stateful service |
| `product-catalog` | **0.210 (21.0%)** | 0.244 | 0.578 | > 0.75 |
| `product-reviews` | **0.532 (53.2%)** | 0.562 | 1.317* | > 0.85 ← LLM buffer risk |
| `recommendation` | **0.088 (8.8%)** | 0.086 | 0.190 | > 0.60 |
| `shipping` | **0.071 (7.1%)** | 0.092 | 0.156 | > 0.60 |

> **(*) Memory > 1.0:** `frontend` (max 1.022) và `product-reviews` (max 1.317) vượt 100% — đây là dấu hiệu memory limit chưa được set đúng trên cluster staging. **Cần kiểm tra và set lại resource limits trước khi deploy production.**
>
> **`payment` median thấp hơn snapshot Baseline_metric.md (53.7% → 34.5%):** Snapshot ngày 14/7 bắt được lúc memory cao sau warm-up. Median 3.5 ngày thực tế thấp hơn và đại diện hơn.

#### Ngưỡng Bất Thường

| Điều kiện | Mức độ |
|---|---|
| `memory_growth = mem_t - mem_{t-6} > 0.05` trong 30 phút | **WARNING** (dấu hiệu leak sớm) |
| `memory_growth > 0.05` liên tục ≥ 3 lần (90 phút) | **CRITICAL** (leak xác nhận) |
| `memory_usage > 0.80` trên `payment` | **CRITICAL** (nguy cơ OOMKill) |
| `memory_usage > 0.85` trên `product-reviews` | **CRITICAL** (LLM buffer accumulation) |
| Memory tăng đơn điệu qua ≥ 6 chu kỳ liên tiếp | **WARNING (Trend)** |

#### Phương Pháp Phát Hiện

- **Primary:** Isolation Forest — features `memory_usage` + `memory_growth`
- **Trend Detection:** Monotonic increase check qua ≥ 6 chu kỳ
- **Fallback:** Z-Score trên `memory_growth`


---

### Metric 5 — `rps` · Request Rate (req/s)

**Service áp dụng chính:** `checkout`, `product-catalog`, `frontend`

#### Lý Do Lựa Chọn

RPS là Traffic Signal — điều kiện tiên quyết để hiểu mọi metric khác đúng ngữ cảnh:
- RPS spike → dấu hiệu sớm nhất của INC-1 (trước khi CPU/latency/error tăng).
- RPS sụt về 0 đột ngột → service crash hoặc mất kết nối network.
- `error_ratio`, `cpu_per_rps`, `latency_deviation` đều dùng RPS làm mẫu số — nếu RPS anomaly không được phát hiện, các derived features bị sai lệch.

#### Baseline Thực Tế (EKS 14–17/07/2026)

| Service | RPS median | RPS mean | RPS max | RPS p90 | RPS p95 |
|---|---|---|---|---|---|
| `frontend` | **4.587** | 6.927 | 89.74 | 10.70 | 24.05 |
| `checkout` | **0.246** | 0.328 | 2.68 | 0.384 | 1.139 |
| `payment` | **0.088** | 0.171 | 2.31 | 0.533 | 0.968 |
| `product-catalog` | **2.625** | 3.918 | 44.30 | 11.483 | 16.204 |
| `product-reviews` | **0.354** | 0.415 | 3.71 | 0.417 | 1.669 |
| `recommendation` | **0.304** | 0.364 | 3.65 | 0.929 | 1.600 |
| `shipping` | **0.100** | 0.291 | 4.88 | 0.503 | 1.897 |

> **`is_high_traffic_period` — LỖI CẦN SỬA:** Condition hiện tại `rps > 100` không bao giờ được trigger trên EKS thật (RPS max toàn hệ thống là 89.74 req/s ở `frontend`). Feature này đang là dead code. Ngưỡng đúng cần dùng là **relative threshold**: `rps > 2.0 × rolling_median_rps_1h` thay vì hard threshold tuyệt đối.

#### Ngưỡng Bất Thường

| Điều kiện | Mức độ |
|---|---|
| `rps` sụt > 80% so với rolling_median_1h trong 1 chu kỳ | **CRITICAL** (service có thể down) |
| `rps = 0` liên tục ≥ 2 chu kỳ trong giờ kinh doanh | **CRITICAL** |
| `rps_delta > 3× rps_{t-1}` ngoài giờ cao điểm | **WARNING** (spike bất thường) |
| `rps_delta > 5×` bất kể thời điểm | **CRITICAL** |
| RPS tăng đồng thời với `cpu_per_rps > 3× median` VÀ `latency_deviation > 2.0` | **CRITICAL** (INC-1 pattern) |

#### Phương Pháp Phát Hiện

- **Primary:** Isolation Forest — features `rps` + `rps_delta` + context flags
- **Drop Detection:** `rps < 20% median_1h` liên tục ≥ 2 chu kỳ → immediate alert
- **Fallback:** Z-Score `|Z| ≥ 3.0` trên `rps_delta`


---

## 4. Tổng Hợp Ma Trận Metric × Service

| Metric | `checkout` | `payment` | `product-catalog` | `product-reviews` | `frontend` | Mức ưu tiên |
|---|---|---|---|---|---|---|
| `error_rate` | ✅ CRITICAL | ✅ CRITICAL | ✅ HIGH | ⚠️ MEDIUM | ✅ HIGH | **P0** |
| `latency_p90` | ✅ CRITICAL | ✅ HIGH | ✅ CRITICAL | ⚠️ MEDIUM | ✅ HIGH | **P0** |
| `cpu_usage` | ✅ HIGH | ✅ HIGH | ✅ HIGH | ⚠️ MEDIUM | ✅ HIGH | **P1** |
| `memory_usage` | ✅ HIGH | ✅ CRITICAL (stateful) | ⚠️ MEDIUM | ✅ HIGH (LLM buffer) | ⚠️ MEDIUM | **P1** |
| `rps` | ✅ CRITICAL | ✅ HIGH | ✅ CRITICAL | ⚠️ MEDIUM | ✅ CRITICAL | **P1** |

---

## 5. Derived Features & Context Flags

| Feature | Công thức | Tác dụng |
|---|---|---|
| `error_ratio` | `error_rate / (rps + ε)` | Chuẩn hóa lỗi theo tải |
| `latency_deviation` | `latency_p90 / (rolling_median_1h + ε)` | Baseline động — tự thích nghi với tải theo giờ |
| `cpu_per_rps` | `cpu_usage / (rps + ε)` | Phát hiện tăng chi phí xử lý nội bộ |
| `memory_growth` | `mem_t - mem_{t-6}` (delta 30 phút) | Phát hiện xu hướng leak sớm |
| `rps_delta` | `rps_t - rps_{t-1}` (delta 5 phút) | Phát hiện spike/drop đột ngột |
| `hour_of_day` | 0–23 | Phân biệt pattern ngày/đêm |
| `day_of_week` | 0–6 | Phân biệt ngày thường/cuối tuần |
| `is_business_hours` | 1 nếu 8h–18h ngày thường | Context flag giờ hành chính |
| `is_high_traffic_period` | **`rps > 2.0 × rolling_median_rps_1h`** *(đã sửa)* | Context flag giờ cao điểm — bỏ hard threshold 100 req/s vì không bao giờ đạt trên EKS thực tế |

---

## 6. Kiến Trúc Phát Hiện Hai Tầng

```
TẦNG 1: PROACTIVE (ML)
  Isolation Forest — 18 features
  Raw: rps, error_rate, latency_p90, cpu_usage, memory_usage,
       client_error_rate, kafka_lag
  Derived: error_ratio, latency_deviation, cpu_per_rps,
           memory_growth, rps_delta, ...
  Context: hour_of_day, day_of_week, is_business_hours,
           is_high_traffic_period
  → prediction == -1: Anomaly | score < -0.3: HIGH confidence

TẦNG 2: REACTIVE (SLO Burn Rate)
  BurnRate >= 14.4× trên CẢ cửa sổ 5m VÀ 1h
  → Immediate Alert → Slack
  (Chỉ kích hoạt khi SLO đang bị ăn mòn — không proactive)
```

---

## 7. Lý Do Chọn Isolation Forest

| Tiêu chí | Lý do |
|---|---|
| **Unsupervised** | Không cần nhãn lịch sử — EKS chỉ có data từ 14/07/2026 |
| **Đa chiều 18 features** | Hoạt động tốt không cần giảm chiều thủ công |
| **Phát hiện correlation** | Nhận ra tổ hợp bất thường mà rule đơn lẻ bỏ sót |
| **Tốc độ O(n log n)** | Phù hợp chu kỳ quét 30 giây |
| **Baseline tự thích nghi** | CronJob re-train mỗi thứ Hai 2h sáng — không tune ngưỡng thủ công |

---

## 8. Vấn Đề Đã Xác Nhận & Cần Xử Lý

| # | Vấn đề | Mức độ | Hành động |
|---|---|---|---|
| 1 | `is_high_traffic_period` hard threshold `rps > 100` — dead code trên EKS thực tế (max RPS chỉ 89.74) | **HIGH** | Đổi thành `rps > 2.0 × rolling_median_rps_1h` trong `anomaly_detector.py` và `train_anomaly_model_local.py` |
| 2 | `frontend` memory_usage max = 1.022, `product-reviews` max = 1.317 — vượt 100% | **MEDIUM** | Kiểm tra và set lại `resources.limits.memory` trong Kubernetes manifest |
| 3 | `checkout` latency_p90 mean = 486 ms nhưng median = 41 ms — outlier spike rất lớn (max 15s) | **MEDIUM** | Điều tra nguyên nhân spike 15s — có thể là cold start hay DB timeout cần investigate thêm |
| 4 | Baseline CPU trong `Baseline_metric.md` lấy từ instant snapshot một thời điểm — không đại diện cho 3.5 ngày thực tế | **LOW** | `Baseline_metric.md` đã được ghi chú, dùng `datametric/*_train.csv` làm nguồn baseline chính thức |

---

*Tài liệu tham chiếu: `datametric/*_train.csv`, `Baseline_metric.md`, `SLO.md`, `INCIDENT_HISTORY.md`, `ADR-008-anomaly-detection-baseline.md`*
*Nguồn baseline v2: EKS Prometheus, pull qua `pull_live_prometheus_data.py`, giai đoạn 14/07/2026 – 17/07/2026*
