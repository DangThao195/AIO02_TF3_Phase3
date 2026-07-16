# AI MANDATE #7a — Detection: Implement + Phân tích

**TF3 / AIO02** · Directive #7 "Sự cố phải tự lộ ra" · hạn 18/07 · *chấm như doc, chưa cần chạy thật*

> Đội **đã có detection chạy sẵn** (5 detector, 160 test pass, chaos harness PASS) → theo hướng dẫn
> directive, #7a làm gọn: **link code + phân tích ≥3 metrics + ADR**. Chạy thật e2e + precision/recall
> để #7b (25/07).

---

## 1. Đã implement gì (link code)

Detection đã có sẵn trong `ai-engine/src/ai_engine/aiops/`, chia 2 tầng đúng tinh thần directive
(sàn univariate per service×signal + bonus multivariate):

| Tầng | Module | Vai trò |
|---|---|---|
| **Layer 1 — page critical** | `detector_burnrate.py` | Burn-rate SLO multi-window (Google 14.4×/6×/1×) — nguồn `critical` DUY NHẤT |
| **Layer 2 — univariate (sàn)** | `detector_latency.py` | p95 latency multi-window robust z-score, per service |
| | `detector_anomaly.py` | robust z-score (median+MAD) cho saturation/queue-lag/429/memory |
| **Layer 2 — bonus** | `detector_iforest.py` | IsolationForest đa biến (6 feature) — multivariate/correlation |
| | `detector_logtemplate.py` | log-template miner (tín hiệu từ log, không chỉ metric) |
| **Gom + báo** | `correlator.py` → `alert_emitter.py` | nhiều signal → 1 incident, báo theo mức ảnh hưởng, chống spam |

Baseline: mọi detector layer-2 lập baseline **per-service** từ chuỗi 1 tuần (query `[1w:5m]` ~2016 mẫu),
dùng **median + MAD** (robust) nên tải-cao-bình-thường không đẩy baseline sai (yêu cầu #2).

Bằng chứng code chạy: `tests/` 160 pass · `scripts/chaos_validate.py` → recall 100%/RCA 100%/0 false alarm
(`chaos/scoreboard.md`). Đo lường nhẹ: chỉ đọc PromQL có sẵn (`PrometheusClient.scalar`), không thu thập
thêm, không thêm cụm (yêu cầu ràng buộc "đo phải nhẹ").

---

## 2. Phân tích ≥3 metrics (bắt buộc của #7a)

Chọn 4 metric từ service trọng yếu (storefront + doanh thu), mỗi metric ánh xạ code thật.

### Metric 1 — checkout p95 latency (`checkout_latency_p95_mw`)
- **Vì sao chọn:** checkout là đường doanh thu trực tiếp; chậm = khách bỏ giỏ (đúng INC-1 lịch sử).
  User-visible symptom hàng đầu.
- **Baseline "bình thường":** median của chuỗi p95(5m) suốt 1 tuần (`(p95[5m])[1w:5m]`). Điển hình
  vài trăm ms; MAD hẹp lúc tải ổn định. Baseline theo service nên giờ cao điểm bình thường không báo nhầm.
- **Bất thường khi:** robust z-score = `(p95_hiện_tại − median) / (1.4826·MAD)` vượt ngưỡng **cả long
  (30m) lẫn short (5m)** cùng breach (multi-window, chống spike 5 phút). Warning ở z≈4 (điều chỉnh theo
  focus-weight service).
- **Phương pháp:** `detector_latency.MultiWindowLatencyDetector` — robust z-score median+MAD, multi-window.

### Metric 2 — checkout error burn-rate (`sli:checkout_error:ratio_rate`)
- **Vì sao chọn:** error-rate là triệu chứng user-visible + directive yêu cầu ưu tiên **burn-rate error
  budget**. Đây là tín hiệu quyết định page hay không.
- **Baseline "bình thường":** SLO target checkout = **99%** (`SLOConfig.checkout_target`) → error budget 1%.
  "Bình thường" = error ratio ≪ 1% (burn-rate ≈ 1×).
- **Bất thường khi:** `burn_rate = error_ratio / (1−SLO)` vượt tier Google — **14.4× (1h+5m) → CRITICAL/page**,
  6× (6h+30m) → warning. Chỉ fire khi **cả 2 window** breach → alert đáng tin (precision mục tiêu ≥90%).
- **Phương pháp:** `detector_burnrate.BurnRateDetector` — multi-window multi-burn-rate.

### Metric 3 — product-catalog / kafka saturation & queue-lag
- **Vì sao chọn:** saturation (pool/memory) và **queue lag** là nguyên nhân gốc lặp lại (INC-1 pool, INC-5
  kafka lag). Bắt sớm ở đây = chặn trước khi checkout vỡ.
- **Baseline "bình thường":** median 1 tuần của `sum(kafka_consumergroup_lag)` (lag thường ~0–vài trăm);
  memory `container_memory_working_set_bytes`. Per-service baseline.
- **Bất thường khi:** robust z-score ≥ ngưỡng (warning z≈4 / info z≈3, nhân focus-weight: kafka=0.9,
  product-catalog=0.6). Confidence < 0.7 bị **chặn trước khi rời engine** → không spam.
- **Phương pháp:** `detector_anomaly.AnomalyDetector` (median+MAD, warning-max, không page).

### Metric 4 (bonus multivariate) — anomaly đa biến qua IsolationForest
- **Vì sao chọn:** bắt "pattern lạ" mà z-score điểm đơn bỏ sót (vd giá trị chưa vượt ngưỡng nhưng
  đang leo bất thường — drift/leak). Đây là phần **bonus multivariate** directive nêu.
- **Baseline "bình thường":** fit IsolationForest trên ≥60 mẫu (5h) với **6 feature** (value, rolling
  mean/std, rate-of-change, lag-1, lag-12) — mô tả ngữ cảnh, không chỉ điểm đơn.
- **Bất thường khi:** `predict == −1` (anomaly), `contamination=0.02`, confidence ≥ 0.7 mới báo.
- **Phương pháp:** `detector_iforest.MultiFeatureIForestDetector` (sklearn, degrade nếu thiếu).

---

## 3. Chống spam (yêu cầu #3)

- **Chỉ burn-rate mới page critical** — layer 2 tối đa WARNING, không đánh thức người vì "gợn nhỏ".
- **Multi-window AND** — phải cả long + short cùng breach → spike 5 phút tự tắt, không page.
- **Confidence gate 0.7** — anomaly dưới ngưỡng bị chặn trong engine.
- **Correlator dedup + gom** — nhiều signal cùng cluster → 1 incident (không 10 page); `alert_emitter`
  có digest mode khi storm.

## 4. Bám ràng buộc

- ✅ **Đo nhẹ:** chỉ đọc PromQL có sẵn, không thu thập thêm, không thêm cụm.
- ✅ **Trong ngân sách:** không dựng hạ tầng mới; detector chạy trong engine hiện có.
- ✅ **Không đụng flagd:** detection chỉ ĐỌC telemetry; remediation hard-block mọi target flagd/BTC
  (`remediation._safety_gate`) — tuân Luật §8.

## 5. DoD #7a

| Mục | Trạng thái |
|---|---|
| Đã implement detector + baseline (link code) | ✅ `aiops/detector_*.py`, 160 test pass |
| Phân tích ≥3 metrics (vì sao/baseline/ngưỡng/phương pháp) | ✅ §2 (4 metric) |
| ADR ký tên | ✅ `docs/adr/ADR-007-multi-signal-detection.md` |

## 6. Chuẩn bị cho #7b (25/07)

- Bơm 1 sự cố qua flagd (mentor bật) → chụp detector kêu e2e (đã có chaos harness mô phỏng sẵn để tái hiện).
- Đo trên bộ sự cố có nhãn (K sự cố + giai đoạn bình thường): recall = bắt/K, precision = kêu đúng/tổng kêu,
  lead-time = từ lúc sự cố bắt đầu tới lúc kêu. Harness `chaos_validate.py` đã tính khung này (MTTD mô phỏng),
  #7b thay bằng số đo thật trên cluster.
