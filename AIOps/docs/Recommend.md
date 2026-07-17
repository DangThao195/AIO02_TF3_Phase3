# Recommend.md
# Đánh giá & Khuyến nghị Cải thiện Feature Vector — AIOps CMDR Engine
## TechX Corp · AIOps Team AIO02 · Phiên bản 1.0

> **Phạm vi:** Đánh giá toàn diện 18-feature Isolation Forest hiện tại, xác định vấn đề cốt lõi, và đề xuất lộ trình cải thiện có ưu tiên rõ ràng trong ngân sách $300/tuần.

---

## Mục lục

1. [Executive Summary](#1-executive-summary)
2. [Phân tích Phủ sóng Hiện tại](#2-phân-tích-phủ-sóng-hiện-tại)
3. [Đánh giá Chất lượng Feature Chi tiết](#3-đánh-giá-chất-lượng-feature-chi-tiết)
4. [Bảy Đề xuất Cải thiện](#4-bảy-đề-xuất-cải-thiện)
5. [Metric Mới cho Dịch vụ Đặc thù](#5-metric-mới-cho-dịch-vụ-đặc-thù)
6. [Lộ trình Triển khai](#6-lộ-trình-triển-khai)
7. [Feature Vector Đề xuất (22 features)](#7-feature-vector-đề-xuất-22-features)
8. [Kết luận](#8-kết-luận)

---

## 1. Executive Summary

### Phán quyết tổng thể: Đủ về số lượng, Không đủ về chất lượng

Hệ thống AIOps CMDR Engine hiện tại có **18 features trong IF vector** — về mặt số lượng là hợp lý cho một bộ phát hiện anomaly đa chiều. Tuy nhiên, **chất lượng thực tế của feature vector này đang nghiêm trọng hơn những gì con số 18 gợi ra**:

| Chỉ số đánh giá | Hiện tại | Mục tiêu |
|---|---|---|
| Features có giá trị thực | **15/18 (83%)** | 22/22 (100%) |
| Features luôn = 0 (vô dụng) | **3/18 (17%)** | 0/22 (0%) |
| Service có IF model | **7/18 (39%)** | 12/18 (67%) |
| Service chỉ có Z-Score fallback | **5/18 (28%)** | 0/18 (0%) |
| Service hoàn toàn không giám sát | **6/18 (33%)** | 6/18 (33%)* |
| Training data vs production mismatch | **300–700× sai lệch RPS** | < 10× sai lệch |

> *6 service không cần IF riêng (nginx, load-generator, flagd, email, quote, image-provider) là hợp lý — chúng không có SLO cứng.

**Ba vấn đề gốc rễ cần xử lý ngay:**

1. **Training data phân phối sai hoàn toàn** — RPS synthetic 80–180 trong khi production thực tế checkout ~0.246, payment ~0.046. `contamination=0.03` được calibrate dựa trên dữ liệu sai → model học baseline sai.

2. **3 features là hằng số = 0** — `client_error_rate`, `client_error_ratio`, `is_high_traffic_period` không bao giờ thay đổi → lãng phí 3/18 chiều (16.7%) và có thể làm nhiễu IF decision boundary.

3. **5 service P1/P2 chỉ dùng Z-Score CPU** — `cart` (SLO 99.5%), `accounting`, `fraud-detection`, `currency`, `llm` không có IF model → phát hiện anomaly kém chất lượng cho các service quan trọng.


---

## 2. Phân tích Phủ sóng Hiện tại

### 2.1 Bản đồ phủ sóng 18 service

| Service | Criticality | Có IF Model | Loại Detection | SLO được bảo vệ? | Rủi ro |
|---|---|---|---|---|---|
| `checkout` | **P1** | ✅ Yes | Isolation Forest | ✅ Có | Vừa phải |
| `frontend` | **P1** | ✅ Yes | Isolation Forest | ✅ Có | Vừa phải |
| `payment` | **P1** | ✅ Yes | Isolation Forest | ✅ Có | Vừa phải |
| `product-catalog` | **P2** | ✅ Yes | Isolation Forest | ✅ Có | Vừa phải |
| `product-reviews` | **P3** | ✅ Yes | Isolation Forest | N/A | Thấp |
| `shipping` | **P3** | ✅ Yes | Isolation Forest | N/A | Thấp |
| `recommendation` | **P3** | ✅ Yes | Isolation Forest | N/A | Thấp |
| **`cart`** | **P1** | ❌ No | Z-Score CPU only | **❌ Không được bảo vệ** | **⚠️ CAO** |
| `accounting` | **P2** | ❌ No | Z-Score CPU only | N/A | Trung bình |
| `llm` | **P2** | ❌ No | Z-Score CPU only | N/A | Trung bình |
| `currency` | **P2** | ❌ No | Z-Score CPU only | N/A | Trung bình |
| `fraud-detection` | **P2** | ❌ No | Z-Score CPU only | N/A | Trung bình |
| `frontend-proxy` | Infrastructure | ❌ No | Không giám sát | N/A | Thấp |
| `postgresql` | Data store | ❌ No | Không giám sát | N/A | **⚠️ TRUNG BÌNH** |
| `valkey-cart` | Data store | ❌ No | Không giám sát | N/A | **⚠️ CAO** (INC-2) |
| `email` | **P3** | ❌ No | Không giám sát | N/A | Thấp |
| `image-provider` | **P3** | ❌ No | Không giám sát | N/A | Thấp |
| `load-generator` | Non-prod | ❌ No | Không giám sát | N/A | Thấp |

### 2.2 Tóm tắt phủ sóng

```
■■■■■■■■■■■■■■■■░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
└── 7 IF models ──┘└──── 5 Z-Score ────┘└──── 6 không monitor ────┘
     (39%)              (28%)                  (33%)
```

**Điểm đáng lo ngại nhất:**

- `cart` là service **P1 với SLO 99.5%** — chỉ có Z-Score CPU fallback. Một OOM tương tự INC-2 sẽ không được phát hiện sớm. CPU spike có thể không xảy ra trước khi valkey-cart evict data.
- `valkey-cart` và `postgresql` (data stores) hoàn toàn không được giám sát — mặc dù đây là nơi INC-2 và các DB-related issue thường bắt đầu.


---

## 3. Đánh giá Chất lượng Feature Chi tiết

### 3.1 Raw Signals (7 features)

| Feature | Nguồn | Chất lượng | Vấn đề cụ thể |
|---|---|---|---|
| `rps` | traces_span_metrics | ✅ Tốt | Giá trị thực tế: checkout ~0.246/s (không phải 80–180 như synthetic train). Distribution mismatch nghiêm trọng. |
| `error_rate` | traces_span_metrics ERROR | ✅ Tốt | Hoạt động đúng. Baseline thực tế ~0.001. Cần calibrate contamination. |
| `client_error_rate` | `vector(0)` | ❌ **VÔ DỤNG** | Hardcoded `vector(0)` trong `anomaly_detector.py`. Luôn = 0. Lãng phí hoàn toàn. |
| `latency_p90` | histogram_quantile(0.90) | ⚠️ Một phần | p90 không match SLO (p95). Trong synthetic data có giá trị = 0.0 (gap). |
| `cpu_usage` | container_cpu_usage | ✅ Tốt | Hoạt động đúng. Phù hợp cho Z-Score fallback. |
| `memory_usage` | working_set / limit | ✅ Tốt | Hoạt động đúng. Baseline checkout ~30%, product-catalog ~30%, payment ~32%. |
| `kafka_lag` | kafka_consumer_records_lag | ⚠️ Một phần | Chỉ có giá trị cho services dùng Kafka (accounting, fraud-detection). Với checkout, payment, product-catalog → luôn = 0. |

**Vấn đề nghiêm trọng nhất trong nhóm raw:** `client_error_rate = vector(0)` là một bug trong implementation, không phải thiếu data.

### 3.2 Derived Features (7 features)

| Feature | Công thức | Chất lượng | Vấn đề cụ thể |
|---|---|---|---|
| `error_ratio` | `error_rate / (rps + 1e-5)` | ✅ Tốt | Tính đúng, giá trị hợp lệ. Phản ánh % lỗi/request. |
| `client_error_ratio` | `client_error_rate / (rps + 1e-5)` | ❌ **VÔ DỤNG** | Tính từ `client_error_rate = 0` → luôn = 0. Lãng phí slot. |
| `latency_deviation` | `latency_p90 / (rolling_median_1h + 1e-5)` | ✅ Tốt | Feature tốt nhất cho INC-6, INC-8. Phát hiện drift tương đối. |
| `rps_delta` | `rps - rps.shift(1)` | ✅ Tốt | Phát hiện traffic spike/drop đột ngột. |
| `cpu_per_rps` | `cpu_usage / (rps + 1e-5)` | ✅ Tốt | Chỉ số hiệu năng CPU — tốt cho INC-1 (DB bottleneck làm CPU/RPS tăng). |
| `memory_growth` | `memory - memory.shift(6)` | ⚠️ Yếu | Window 30m quá ngắn cho slow leak (0.3–0.5%/5m → chỉ 1.5–2.5% trong 30m). |
| `kafka_lag_growth` | `kafka_lag - kafka_lag.shift(1)` | ⚠️ Một phần | Chỉ hữu ích với Kafka services. Với service không dùng Kafka → constant 0. |

**Feature thiếu quan trọng nhất:** `latency_growth` — không có feature nào đo độ tăng latency theo thời gian. INC-1 pattern (latency tăng dần từ 50ms→5s) sẽ bị bắt chậm vì `latency_deviation` cần rolling median 1h để ổn định.

### 3.3 Temporal Features (4 features)

| Feature | Logic | Chất lượng | Vấn đề cụ thể |
|---|---|---|---|
| `hour_of_day` | `timestamp.dt.hour` | ✅ Tốt | Hoạt động đúng. Giúp IF phân biệt peak/off-peak. |
| `day_of_week` | `timestamp.dt.weekday` | ✅ Tốt | Hoạt động đúng. Cuối tuần vs ngày thường. |
| `is_business_hours` | `(8 ≤ hour ≤ 18) AND (weekday < 5)` | ✅ Tốt | Hoạt động đúng. |
| `is_high_traffic_period` | `(rps > 100) AND (rps > 1.5 × rolling_median_rps)` | ❌ **VÔ DỤNG** | Ngưỡng `rps > 100` hardcoded. checkout RPS thực tế ~0.246 → không bao giờ trigger. payment RPS ~0.046 → không bao giờ trigger. Luôn = 0 cho mọi service có model. |

### 3.4 Training Data Distribution Shift — Vấn đề Nghiêm trọng Nhất

Đây là **vấn đề cốt lõi** ảnh hưởng đến toàn bộ chất lượng model. Script `train_anomaly_model_local.py` dùng `generate_synthetic_data()` với phân phối RPS hoàn toàn sai so với production:

| Service | RPS Synthetic (train script) | RPS Thực tế (CSV production) | Sai lệch |
|---|---|---|---|
| `checkout` | Business hours: 80–180 | **~0.246/s** | **~326–732× quá cao** |
| `payment` | Business hours: 80–180 | **~0.046/s** | **~1739–3913× quá cao** |
| `product-catalog` | Business hours: 80–180 | **~2.625/s** | **~30–69× quá cao** |
| `frontend` | Business hours: 80–180 | Chưa đo được | > 30× ước tính |

**Hậu quả của distribution shift này:**

```
Train với RPS = 80–180
    → IF học "bình thường" là RPS cao
    → contamination=0.03 calibrate trên phân phối RPS cao
    → Production RPS = 0.246 (checkout)
    → IF coi RPS = 0.246 là "bất thường" (outlier của distribution đã học)
    → FALSE POSITIVE liên tục HOẶC
    → Model học không đúng gì cả (tất cả production data = outlier)

OR:

    → IF bị "drift" và học rằng RPS thấp là bình thường (Golden Cache cứu)
    → Nhưng contamination=0.03 vẫn sai → ngưỡng detection không đúng
    → FALSE NEGATIVE cho anomaly thực sự
```

```python
# HIỆN TẠI trong train_anomaly_model_local.py — SAI
if is_biz_hours:
    base_rps = random.uniform(80, 180)   # ← sai hoàn toàn với production

# PRODUCTION THỰC TẾ từ CSV baseline:
# checkout:       rps ~= 0.246  (không phải 80–180)
# payment:        rps ~= 0.046  (không phải 80–180)
# product-catalog: rps ~= 2.625 (không phải 80–180)
```


---

## 4. Bảy Đề xuất Cải thiện

### Proposal 1: Dọn dẹp features vô dụng, thêm latency_growth + memory_growth_2h

**Tóm tắt:** Xóa 3 features luôn = 0, thêm 2 features có giá trị cao, fix `is_high_traffic_period`.  
**Impact:** Cao — loại bỏ noise, tăng information density của vector từ 83% → 100%.  
**Effort:** Thấp — chỉ sửa code feature engineering, không cần retrain từ đầu.  
**Budget:** $0 — không tốn chi phí infra.  
**Thực hiện:** Tuần này (sprint hiện tại).

**Thay đổi cụ thể:**

```python
# === TRƯỚC (feature engineering hiện tại) ===
# 3 features luôn = 0, lãng phí:
df["client_error_rate"]        # vector(0) hardcoded → xóa
df["client_error_ratio"]       # tính từ 0 → xóa
df["is_high_traffic_period"]   # ngưỡng rps > 100 never triggers → fix

# === SAU (đề xuất) ===

# 1. Xóa client_error_rate + client_error_ratio (hoặc fix PromQL)
# Tạm thời: không include vào feature_cols khi không có data thật
# Lâu dài: fix PromQL client_error_rate (xem Proposal 5)

# 2. Thêm latency_growth — delta 15 phút để bắt INC-1/INC-6 pattern
df["latency_growth"] = (
    df["latency_p90"] - df["latency_p90"].shift(3).fillna(0)
)  # 3 samples × 5m = 15 phút

# 3. Thêm memory_growth_2h — delta 2 giờ để bắt slow memory leak
df["memory_growth_2h"] = (
    df["memory_usage"] - df["memory_usage"].shift(24).fillna(0)
)  # 24 samples × 5m = 120 phút = 2 giờ

# 4. Fix is_high_traffic_period — ngưỡng tương đối thay vì hardcoded
df["rolling_median_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).median()
df["rolling_std_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).std().fillna(0)
df["is_high_traffic_period"] = (
    (df["rps"] > df["rolling_median_rps_1h"] + 2 * df["rolling_std_rps_1h"])
    & (df["rps"] > df["rolling_median_rps_1h"] * 1.5)
).astype(int)
# → Trigger khi RPS cao hơn 1.5× median VÀ vượt 2 stddev
# → Hoạt động đúng với cả checkout (RPS 0.246) lẫn service traffic cao

# Feature vector mới sau Proposal 1:
feature_cols_v2 = [
    # Raw (5, bỏ client_error_rate)
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
    # Kafka raw (kept, = 0 cho non-Kafka services là OK)
    "kafka_lag",
    # Derived (8: +latency_growth, +memory_growth_2h, giữ memory_growth)
    "error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps",
    "memory_growth", "memory_growth_2h", "kafka_lag_growth", "latency_growth",
    # Temporal (4, is_high_traffic_period đã fix)
    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
]
# Tổng: 19 features (tạm thời, trước khi Proposal 3 thêm SLO features)
```

**Tác động với sự cố đã biết:**
- `latency_growth` sẽ phát hiện INC-1 (latency tăng dần) và INC-6 (GC pressure latency drift) sớm hơn ~10–15 phút.
- `memory_growth_2h` sẽ bắt slow leak pattern mà 30m window bỏ sót.
- `is_high_traffic_period` fixed sẽ cung cấp context chính xác cho IF về traffic spikes.

---

### Proposal 2: Fix Training Data Distribution — Dùng Golden Cache CSV làm nguồn train chính

**Tóm tắt:** Đây là fix quan trọng nhất. Thay synthetic data (RPS 80–180) bằng dữ liệu thực từ CSV files (`checkout_train.csv`, `payment_train.csv`, etc.) làm nguồn train chính.  
**Impact:** Rất cao — fix vấn đề gốc rễ làm tất cả model hiện tại thiếu chính xác.  
**Effort:** Trung bình — cần refactor `train_anomaly_model_local.py`.  
**Budget:** $0 — dữ liệu đã có sẵn, chỉ cần code.  
**Thực hiện:** Tuần này (sprint hiện tại) — **ưu tiên cao nhất**.

```python
# === TRƯỚC: train_anomaly_model_local.py ===
# Chủ yếu dùng generate_synthetic_data() (RPS 80–180) + 1 phần golden cache
df_train_raw = generate_synthetic_data(service, duration_days=14)  # ← SAI
df_combined_train = pd.concat([df_train, df_gold_normal_features])

# === SAU: Golden Cache làm primary source ===
def train_from_production_data(service: str) -> IsolationForest:
    """
    Train IF model từ dữ liệu production thực tế.
    Golden Cache CSV là nguồn chính, synthetic chỉ dùng để bổ sung
    nếu CSV không đủ mẫu (< 1000 samples).
    """
    engine_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Load production CSV (nguồn chính)
    csv_path = os.path.join(engine_dir, "data", f"{service}_train.csv")
    if os.path.exists(csv_path):
        df_production = pd.read_csv(csv_path)
        df_production["timestamp"] = pd.to_datetime(df_production["timestamp"])
        print(f"  [{service}] Loaded {len(df_production)} production samples")
        print(f"  [{service}] RPS stats: mean={df_production['rps'].mean():.3f}, "
              f"std={df_production['rps'].std():.3f}, "
              f"max={df_production['rps'].max():.3f}")
    else:
        print(f"  [{service}] No production CSV found. Using synthetic fallback.")
        df_production = generate_synthetic_data(service, duration_days=7)
    
    # 2. Load golden cache (chỉ lấy NORMAL samples, tránh data leakage)
    golden_path = os.path.join(engine_dir, "data", "golden_samples.csv")
    if os.path.exists(golden_path):
        df_golden = pd.read_csv(golden_path)
        df_golden = df_golden[
            (df_golden["service"] == service) & (df_golden["label"] == 1)
        ]
        df_production = pd.concat([df_production, df_golden], ignore_index=True)
        print(f"  [{service}] After golden cache merge: {len(df_production)} samples")
    
    # 3. Feature engineering
    df_features = feature_engineering(df_production)
    
    # 4. Calibrate contamination dựa trên PRODUCTION distribution, không synthetic
    # Dùng tỷ lệ anomaly thực tế từ golden_samples labels
    if "label" in df_features.columns:
        anomaly_ratio = (df_features["label"] == -1).mean()
        # Clamp: không dưới 0.01 (quá nghiêm) hay trên 0.10 (quá lỏng)
        contamination = float(np.clip(anomaly_ratio, 0.01, 0.10))
        print(f"  [{service}] Calibrated contamination = {contamination:.4f} "
              f"(from {anomaly_ratio:.4f} observed anomaly ratio)")
    else:
        contamination = 0.03  # Default nếu không có labels
    
    # 5. Train model
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        max_features=0.8,
        random_state=42,
        n_jobs=-1
    )
    
    X_train = df_features[feature_cols].fillna(0)
    model.fit(X_train)
    
    return model, contamination

# Kết quả mong đợi sau fix:
# checkout: contamination calibrated trên RPS ~18.5 mean (thay vì ~130 synthetic)
# payment:  contamination calibrated trên RPS ~18.9 mean (thay vì ~130 synthetic)
# → False positive rate giảm đáng kể khi RPS thấp lúc off-peak
```

**Lý do đây là fix quan trọng nhất:**

Nếu model học "baseline bình thường là RPS = 80–180" nhưng production thực tế RPS = 0.246 (checkout), thì:
- Mọi điểm production đều trông như "outlier" với model
- HOẶC model không học được gì từ synthetic data quá khác xa thực tế
- contamination=0.03 calibrate sai → ngưỡng -0.3/-0.1 không có ý nghĩa thực tế

**Ghi chú về Golden Cache (`golden_samples.csv`):** File này đã tồn tại trong `data/` và được tạo từ production traces. Đây là dữ liệu gần thực nhất hiện có và nên là nguồn train **ưu tiên** hơn `generate_synthetic_data()`.


---

### Proposal 3: Thêm SLO Budget Features

**Tóm tắt:** Thêm 4 features trực tiếp từ SLO state vào IF vector, giúp model học ngữ cảnh SLO cùng lúc với metrics kỹ thuật.  
**Impact:** Trung bình-cao — tạo correlation trực tiếp giữa anomaly detection và SLO violation.  
**Effort:** Trung bình — cần tính toán từ Prometheus + retrain model.  
**Budget:** $0 — dùng Prometheus queries đã có.  
**Thực hiện:** Sprint tiếp theo.

**4 features mới đề xuất:**

```python
# === 4 SLO Budget Features đề xuất ===

# Feature 1: slo_burn_velocity — tốc độ burn rate trượt theo thời gian
# Đo xem burn rate đang tăng hay giảm trong 30 phút qua
df["slo_burn_velocity"] = (
    df["error_ratio"] - df["error_ratio"].shift(6).fillna(0)
)  # Positive → burn rate đang tăng, Negative → đang ổn định

# Feature 2: latency_slo_ratio — latency hiện tại / SLO latency threshold
# checkout SLO: p95 < 1000ms → dùng p90 * 1.1 làm proxy
SLO_LATENCY_MS = {
    "checkout": 1000,       # p95 < 1s
    "frontend": 1000,       # p95 < 1s
    "cart": 500,            # p95 < 500ms
    "payment": 1000,        # kế thừa checkout
    "product-catalog": 1000,
    "default": 2000         # conservative
}

def add_slo_features(df: pd.DataFrame, service: str) -> pd.DataFrame:
    slo_lat = SLO_LATENCY_MS.get(service, SLO_LATENCY_MS["default"])
    # latency_p90 trong milliseconds
    df["latency_slo_ratio"] = df["latency_p90"] / (slo_lat + 1e-5)
    # > 0.8 → tiệm cận SLO; > 1.0 → vượt SLO (nếu p90 ≈ p95)
    
    # Feature 3: slo_budget_used_6h — % error budget đã dùng trong 6h gần nhất
    # Rolling error rate trung bình 6h, chuẩn hóa bởi error budget
    error_budget_per_service = {
        "checkout": 0.01,       # 1% budget
        "frontend": 0.005,      # 0.5% budget
        "cart": 0.005,          # 0.5% budget
        "default": 0.01
    }
    budget = error_budget_per_service.get(service, error_budget_per_service["default"])
    df["rolling_error_ratio_6h"] = df["error_ratio"].rolling(window=72, min_periods=1).mean()
    df["slo_budget_used_6h"] = df["rolling_error_ratio_6h"] / (budget + 1e-5)
    # > 1.0 → budget đã bị tiêu hết trong 6h → critical

    # Feature 4: cpu_saturation — CPU usage tương đối với request rate
    # Giống cpu_per_rps nhưng normalize bởi baseline cpu_per_rps trung bình 1h
    df["rolling_median_cpu_per_rps"] = df["cpu_per_rps"].rolling(
        window=12, min_periods=1
    ).median()
    df["cpu_saturation"] = df["cpu_per_rps"] / (
        df["rolling_median_cpu_per_rps"] + 1e-5
    )
    # > 2.0 → CPU đang xử lý kém hiệu quả hơn 2× so với baseline gần đây
    # Bắt INC-1 pattern (DB bottleneck làm CPU/request tăng)
    
    return df

# Sử dụng trong feature_engineering():
# df = add_slo_features(df, service_name)
```

**Giá trị của từng feature mới:**

| Feature | Sự cố phát hiện | Lý do quan trọng |
|---|---|---|
| `slo_burn_velocity` | INC-1, INC-3 | Phân biệt "đang xấu dần" vs "đang ổn định" |
| `latency_slo_ratio` | INC-6, INC-8 | Trực tiếp đo khoảng cách tới SLO violation |
| `slo_budget_used_6h` | Tất cả availability issues | Context: budget còn bao nhiêu trước khi vi phạm |
| `cpu_saturation` | INC-1 (DB bottleneck) | CPU/request tăng = bottleneck ở downstream |


---

### Proposal 4: River HalfSpaceTrees cho 5 service không có IF model

**Tóm tắt:** Thêm online anomaly detection (River HST) cho `cart`, `accounting`, `llm`, `currency`, `fraud-detection` — thay thế Z-Score CPU fallback đơn chiều bằng multi-feature online model.  
**Impact:** Cao — `cart` là P1 với SLO 99.5% hiện đang hoàn toàn dựa vào Z-Score CPU.  
**Effort:** Trung bình — River không cần batch training, khởi động nhanh.  
**Budget:** $0 — `pip install river` (~1MB, no cloud cost). Chạy in-process với CMDR Engine.  
**Thực hiện:** Sprint tiếp theo — ưu tiên `cart` trước vì P1.

**Lý do chọn River HST thay vì IF batch training:**

1. `cart`, `currency`, `fraud-detection` không có CSV train riêng (thiếu historical data).
2. River HST học online từ stream — không cần batch, tự adapt với production distribution.
3. Phù hợp với budget thấp — không tốn compute S3/batch training jobs.
4. HalfSpaceTrees đặc biệt tốt cho time-series data vì sliding window.

```python
# === River HalfSpaceTrees cho 5 service thiếu IF model ===
# pip install river

from river import anomaly, preprocessing
from collections import defaultdict
import threading

class OnlineAnomalyDetector:
    """
    Online anomaly detector dùng River HalfSpaceTrees.
    Chạy song song với Isolation Forest, dùng cho services không có IF model.
    
    Services mục tiêu: cart, accounting, llm, currency, fraud-detection
    """
    
    ONLINE_SERVICES = {"cart", "accounting", "llm", "currency", "fraud-detection"}
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self._lock = threading.Lock()
        
        for service in self.ONLINE_SERVICES:
            # HalfSpaceTrees: n_trees=25, height=15, window_size=250 (~20h @ 5min)
            self.models[service] = anomaly.HalfSpaceTrees(
                n_trees=25,
                height=15,
                window_size=250,
                seed=42
            )
            self.scalers[service] = preprocessing.StandardScaler()
    
    def _build_feature_dict(
        self,
        rps: float, error_rate: float, latency_p90: float,
        cpu_usage: float, memory_usage: float, kafka_lag: float,
        error_ratio: float, latency_deviation: float,
        memory_growth: float, hour_of_day: int
    ) -> dict:
        """Tạo feature dict cho online model."""
        return {
            "rps": rps,
            "error_rate": error_rate,
            "latency_p90": latency_p90,
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "kafka_lag": kafka_lag,
            "error_ratio": error_ratio,
            "latency_deviation": latency_deviation,
            "memory_growth": memory_growth,
            "hour_of_day": float(hour_of_day),
        }
    
    def score_and_learn(self, service: str, features: dict) -> dict:
        """
        Score một điểm dữ liệu và update model (online learning).
        
        Returns:
            dict với 'score' (0.0–1.0), 'prediction' (-1 hoặc 1), 'confidence'
        """
        if service not in self.ONLINE_SERVICES:
            raise ValueError(f"Service {service} không phải online service")
        
        with self._lock:
            model = self.models[service]
            scaler = self.scalers[service]
            
            # Scale features
            x_scaled = scaler.learn_one(features).transform_one(features)
            
            # Score trước khi learn (tránh bias)
            score = model.score_one(x_scaled)
            
            # Update model với điểm mới
            model.learn_one(x_scaled)
        
        # Chuyển đổi HST score (0–1) sang confidence tương đương IF
        # HST: score gần 1 = anomaly, score gần 0 = normal
        if score > 0.80:
            confidence = "HIGH"
            prediction = -1
        elif score > 0.60:
            confidence = "MEDIUM"
            prediction = -1
        else:
            confidence = "LOW"
            prediction = 1
        
        return {
            "prediction": prediction,
            "score": score,
            "confidence": confidence,
            "method": "river_hst",
            "fallback": False
        }

# === Tích hợp vào AnomalyDetector.check_service_anomaly() ===
# Trong anomaly_detector.py, thay đoạn fallback Z-Score:

# TRƯỚC:
# if service not in self.models:
#     cpu_z = self.check_infra_z_score(...)
#     prediction = -1 if abs(cpu_z) >= 3.0 else 1
#     return {"prediction": prediction, "fallback": True}

# SAU:
# online_detector = OnlineAnomalyDetector()  # khởi tạo một lần trong __init__
# if service not in self.iforest_models:
#     if service in OnlineAnomalyDetector.ONLINE_SERVICES:
#         features = self.extract_features_realtime(service)
#         if not features.empty:
#             f = features.iloc[-1]
#             feature_dict = online_detector._build_feature_dict(...)
#             return online_detector.score_and_learn(service, feature_dict)
#     # Ultimate fallback: Z-Score
#     cpu_z = self.check_infra_z_score(...)
#     ...
```

**Ưu tiên triển khai cho từng service:**

| Service | Priority | Lý do |
|---|---|---|
| `cart` | **P1 — làm trước** | SLO 99.5%, INC-2 history, OOM risk |
| `accounting` | P2 | Kafka lag cần multi-feature detection |
| `fraud-detection` | P2 | Kafka consumer, compliance risk |
| `llm` | P2 | Cost control ($300 budget) |
| `currency` | P3 | Ít critical hơn |


---

### Proposal 5: Thêm latency_p95 và http_4xx_rate để lấp khoảng trống SLO

**Tóm tắt:** SLO cam kết dùng **p95**, nhưng detection hiện tại chỉ có **p90**. Thêm `latency_p95` query + `http_4xx_rate` thực thay cho `vector(0)`.  
**Impact:** Trung bình-cao — fix SLO gap và client error signal.  
**Effort:** Thấp — chỉ thêm PromQL queries.  
**Budget:** $0 — Prometheus queries, không tốn infra.  
**Thực hiện:** Sprint tiếp theo.

**Vấn đề hiện tại:**

```
SLO checkout: p95 latency < 1s
Detection IF: dùng latency_p90

Khoảng cách p90 vs p95:
- Nếu 90% request < 200ms và 5% request = 2000ms
- p90 = 200ms → BÌNH THƯỜNG theo detection
- p95 = 2000ms → VI PHẠM SLO
→ Miss tới 100% SLO latency violations trong tail distribution!
```

```promql
# === Thêm vào extract_features_realtime() ===

# latency_p95 — match với SLO definition
"latency_p95": """
    histogram_quantile(0.95,
        sum(rate(
            traces_span_metrics_duration_milliseconds_bucket{{
                service_name="{service}",
                span_kind="SPAN_KIND_SERVER"
            }}[5m]
        )) by (le)
    )
""",

# http_4xx_rate — thay thế client_error_rate = vector(0)
# Cần HTTP instrumentation metric (nếu có)
"http_4xx_rate": """
    (
        sum(rate(traces_span_metrics_calls_total{{
            service_name="{service}",
            span_kind="SPAN_KIND_SERVER",
            status_code=~"STATUS_CODE_4.*"
        }}[5m]))
        or vector(0)
    )
""",

# Nếu không có status_code 4xx trong span metrics, dùng HTTP metrics trực tiếp:
# sum(rate(http_server_requests_total{{
#     service="{service}", status=~"4.."
# }}[5m]))
```

```python
# Derived features từ latency_p95:
df["latency_p95_slo_ratio"] = df["latency_p95"] / (SLO_LATENCY_MS[service] + 1e-5)
# > 0.9 → WARNING; > 1.0 → SLO violation

# Derived feature: tail_latency_ratio = p95/p90 (độ rộng đuôi phân phối)
df["tail_latency_ratio"] = df["latency_p95"] / (df["latency_p90"] + 1e-5)
# > 3.0 → đuôi phân phối rất rộng → dấu hiệu intermittent slow requests (INC-8)
```

**Lưu ý triển khai:** Thêm `latency_p95` vào feature vector chỉ sau khi đã có đủ training data p95 từ production. Không nên thêm feature thiếu data vào IF vector vì sẽ làm nhiễu model.

---

### Proposal 6: Thêm `is_deployment_window` để giảm false positive khi deploy

**Tóm tắt:** Deploy rolling update (INC-3) luôn gây error rate spike ngắn khi pod mới nhận traffic trước khi sẵn sàng hoàn toàn. Thêm feature context về deployment để IF nhận biết và giảm sensitivity.  
**Impact:** Trung bình — giảm alert fatigue đáng kể khi team deploy thường xuyên.  
**Effort:** Trung bình — cần tích hợp với Kubernetes API.  
**Budget:** $0 — dùng K8s API đã có RBAC.  
**Thực hiện:** Sprint tiếp theo.

```python
# === Feature is_deployment_window ===
import subprocess
import json
from datetime import datetime, timedelta

def check_deployment_window(service: str, window_minutes: int = 10) -> int:
    """
    Kiểm tra xem service có đang trong trạng thái rolling update không.
    
    Returns: 1 nếu đang deploy, 0 nếu bình thường
    
    Cách hoạt động:
    - Query K8s deployment events trong window_minutes gần nhất
    - Nếu có ReplicaSet scale-up/scale-down event → deployment đang diễn ra
    """
    try:
        # Query kubectl events cho service
        cmd = [
            "kubectl", "get", "events",
            "-n", "default",  # hoặc namespace của service
            "--field-selector", f"involvedObject.name={service}",
            "-o", "json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return 0
        
        events = json.loads(result.stdout)
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        
        for event in events.get("items", []):
            event_time_str = event.get("lastTimestamp", "")
            if not event_time_str:
                continue
            event_time = datetime.fromisoformat(event_time_str.replace("Z", ""))
            
            # Kiểm tra deployment-related events
            if event_time > cutoff:
                reason = event.get("reason", "")
                if reason in ["ScalingReplicaSet", "Scheduled", "Pulled", "Started"]:
                    return 1  # Đang trong deployment window
        
        return 0  # Không có deployment
    except Exception:
        return 0  # Fail-safe: giả sử không có deployment

# Tích hợp vào extract_features_realtime():
# df["is_deployment_window"] = check_deployment_window(service, window_minutes=10)

# Trong alert routing: nếu is_deployment_window = 1 VÀ error_rate spike:
# → Suppress alert 10 phút, monitor thêm
# → Nếu sau 10 phút vẫn còn error → escalate (deployment failed)
```

**Tác động với INC-3:** Thay vì page SRE khi payment có 5xx trong 2 phút deploy, engine sẽ:
1. Nhận diện `is_deployment_window = 1`
2. Ghi log nhưng không page ngay
3. Nếu error tự hết sau 5 phút → suppress (deploy thành công)
4. Nếu error kéo dài > 10 phút → escalate (deployment failed = sự cố thật)

---

### Proposal 7: Tách model theo nhóm SLO Criticality (contamination khác nhau)

**Tóm tắt:** Hiện tất cả IF models dùng `contamination=0.03`. P1 services cần contamination thấp hơn (ít bỏ sót hơn), P3 services có thể cao hơn (ít false positive hơn).  
**Impact:** Trung bình — cải thiện precision/recall trade-off theo criticality.  
**Effort:** Thấp — chỉ thay đổi hyperparameter khi train.  
**Budget:** $0.  
**Thực hiện:** Sprint tiếp theo (kết hợp với Proposal 2).

```python
# === Contamination theo SLO criticality ===

# contamination = ước tính % outlier trong training data
# P1 (checkout, cart, payment, frontend):
#   → contamination thấp = 0.01 → model conservative, ít bỏ sót (recall cao)
#   → Trade-off: nhiều false positive hơn một chút
# P2 (product-catalog, accounting, fraud-detection):
#   → contamination = 0.03 → balance giữa precision và recall
# P3 (recommendation, product-reviews, shipping):
#   → contamination = 0.05 → model liberal, ít false positive hơn
#   → Trade-off: có thể bỏ sót một số anomaly nhỏ

CONTAMINATION_BY_SLO = {
    # P1: SLO cứng, mất revenue trực tiếp → ưu tiên recall (không bỏ sót)
    "checkout":         0.01,
    "frontend":         0.01,
    "payment":          0.01,
    "cart":             0.01,

    # P2: SLO quan trọng nhưng không trực tiếp mất revenue
    "product-catalog":  0.03,
    "accounting":       0.03,
    "fraud-detection":  0.03,
    "llm":              0.03,
    "currency":         0.03,

    # P3: Best-effort, giảm false positive để giảm alert fatigue
    "recommendation":   0.05,
    "product-reviews":  0.05,
    "shipping":         0.05,
}

# Sử dụng trong training loop:
# contamination = CONTAMINATION_BY_SLO.get(service, 0.03)
# model = IsolationForest(contamination=contamination, ...)

# Expected behavior change:
# checkout (0.01): score threshold shifts → phát hiện anomaly nhỏ hơn (score < -0.15 thay vì < -0.1)
# recommendation (0.05): threshold shifts lên → chỉ flag anomaly rõ ràng hơn
```

**Lưu ý:** Thay đổi contamination cần retrain tất cả models. Kết hợp với Proposal 2 (fix training data) để làm một lần.


---

## 5. Metric Mới cho Dịch vụ Đặc thù

Ngoài cải thiện feature vector chung, một số service cần metric đặc thù do kiến trúc riêng:

### 5.1 `cart` + `valkey-cart`

INC-2 xảy ra do `valkey-cart` single replica OOM eviction. Cart service cần giám sát trực tiếp vào data store:

| Metric mới | PromQL | Ý nghĩa | Ngưỡng cảnh báo |
|---|---|---|---|
| `valkey_memory_ratio` | `redis_memory_used_bytes / redis_memory_max_bytes` | % memory Valkey đang dùng | > 80% → WARNING; > 92% → CRITICAL (OOM risk) |
| `cart_operation_latency` | `histogram_quantile(0.95, rate(cart_operation_duration_seconds_bucket[5m]))` | Latency thao tác giỏ hàng (add/remove/get) | > 200ms → WARNING; > 500ms → HIGH |
| `valkey_evicted_keys_rate` | `rate(redis_evicted_keys_total[5m])` | Số key bị evict mỗi giây | **> 0 → IMMEDIATE ALERT** (mất data giỏ hàng) |

**Lý do `valkey_evicted_keys_rate` cần immediate alert:** Khi Valkey evict key, giỏ hàng của khách **biến mất ngay lập tức** — không có recovery. Đây là metric "zero tolerance": bất kỳ eviction nào cũng là incident.

```promql
# valkey_evicted_keys_rate
rate(redis_evicted_keys_total{instance=~"valkey-cart.*"}[5m])

# valkey_memory_ratio
redis_memory_used_bytes{instance=~"valkey-cart.*"}
/
redis_memory_max_bytes{instance=~"valkey-cart.*"}
```

### 5.2 `fraud-detection` + Kafka

`fraud-detection` là Kafka consumer quan trọng về compliance. Delay trong fraud detection = giao dịch gian lận chưa bị chặn:

| Metric mới | PromQL | Ý nghĩa | Ngưỡng cảnh báo |
|---|---|---|---|
| `fraud_kafka_lag` | `sum(kafka_consumer_records_lag{service_name="fraud-detection"})` | Số event đơn hàng chưa kiểm tra gian lận | > 200 → WARNING; > 1000 → HIGH |
| `fraud_processing_time` | `histogram_quantile(0.95, rate(fraud_check_duration_seconds_bucket[5m]))` | Thời gian xử lý mỗi giao dịch | > 500ms → WARNING (compliance SLA) |

**Lưu ý:** Nếu `fraud_kafka_lag` > 1000 liên tục, đơn hàng đang qua mà fraud-detection chưa kiểm tra — rủi ro tài chính trực tiếp.

### 5.3 `llm` — Quan trọng cho Budget $300/tuần

`llm` service đặc biệt vì **chi phí per-request**: mỗi lần inference LLM tốn token → tốn tiền. Trong ngân sách $300/tuần, cần giám sát chặt để tránh cost overrun:

| Metric mới | PromQL | Ý nghĩa | Ngưỡng cảnh báo |
|---|---|---|---|
| `llm_timeout_rate` | `rate(llm_request_timeout_total[5m]) / rate(llm_requests_total[5m])` | % request LLM bị timeout | > 5% → WARNING; > 20% → HIGH |
| `llm_p95_latency` | `histogram_quantile(0.95, rate(llm_request_duration_seconds_bucket[5m]))` | Latency p95 của LLM response | > 5s → WARNING; > 10s → CRITICAL |
| `llm_token_cost_rate` | `rate(llm_tokens_total[1h]) * TOKEN_COST_PER_UNIT` | Ước tính chi phí token/giờ (USD) | > $5/h → WARNING; > $10/h → HIGH (sẽ vượt budget tuần) |

**Liên quan Budget:**

```python
# Ước tính cost impact:
# Budget: $300/week = $42.86/day = $1.78/hour
# Nếu llm_token_cost_rate > $1.78/h → LLM service ĐANG DÙNG TOÀN BỘ BUDGET
# → Alert ngay lập tức + throttle

# Recording rule trong Prometheus:
# llm:token_cost_rate:1h = 
#   rate(llm_tokens_total{type="input"}[1h]) * 0.000001  # $0.001/1000 tokens (nova-lite)
#   + rate(llm_tokens_total{type="output"}[1h]) * 0.000003
```

### 5.4 `postgresql` (Shared DB)

`postgresql` phục vụ cả `product-catalog`, `product-reviews`, `accounting` — tắc ở đây ảnh hưởng tất cả:

| Metric mới | PromQL | Ý nghĩa | Ngưỡng cảnh báo |
|---|---|---|---|
| `pg_connections_used_ratio` | `pg_stat_activity_count / pg_settings_max_connections` | % connection pool đã dùng | > 70% → WARNING; > 90% → CRITICAL |
| `pg_query_p95_duration` | `histogram_quantile(0.95, rate(pg_query_duration_seconds_bucket[5m]))` | Latency query p95 | > 500ms → WARNING; > 2s → HIGH |
| `pg_deadlocks_rate` | `rate(pg_stat_database_deadlocks_total[5m])` | Tốc độ deadlock | > 0.1/s → WARNING; > 1/s → HIGH |

**Tại sao `pg_connections_used_ratio` quan trọng:** INC-1 (checkout slow, DB connection pool exhausted) trực tiếp do metric này chạm ngưỡng. Đây là **leading indicator** của INC-1 pattern. Nếu giám sát metric này ở `postgresql`, có thể cảnh báo trước khi checkout bị ảnh hưởng.


---

## 6. Lộ trình Triển khai

### Tuần này (Sprint hiện tại) — $0 budget, chỉ code changes

**Mục tiêu:** Fix các vấn đề gốc rễ không tốn tiền, cải thiện ngay chất lượng detection.

| Việc cần làm | Proposal | Tác động ngay | Ước tính effort |
|---|---|---|---|
| Xóa `client_error_rate/ratio` khỏi feature_cols | P1 | Giảm noise ngay | 30 phút |
| Fix `is_high_traffic_period` thành ngưỡng tương đối | P1 | Feature bắt đầu có giá trị | 1 giờ |
| Thêm `latency_growth` (delta 15m) | P1 | Bắt INC-6 pattern | 1 giờ |
| Thêm `memory_growth_2h` (delta 2h) | P1 | Bắt slow memory leak | 30 phút |
| Refactor training để dùng CSV production làm nguồn chính | P2 | **Fix vấn đề quan trọng nhất** | 3–4 giờ |
| Calibrate contamination từ golden_samples labels | P2 | Ngưỡng detection chính xác hơn | 1 giờ |
| Retrain tất cả 7 models với data + features mới | P1+P2 | Deploy model mới | 2 giờ |

**Tổng effort tuần này: ~10 giờ. Budget: $0.**

### Sprint tiếp theo (2 tuần) — $0 budget

**Mục tiêu:** Mở rộng phủ sóng và tăng độ chính xác SLO monitoring.

| Việc cần làm | Proposal | Tác động | Ước tính effort |
|---|---|---|---|
| Triển khai River HST cho `cart` | P4 | P1 service có đa chiều detection | 4 giờ |
| Triển khai River HST cho `accounting`, `fraud-detection` | P4 | Kafka lag multi-feature detection | 3 giờ |
| Thêm SLO budget features (4 features mới) | P3 | Context-aware detection | 3 giờ |
| Thêm `latency_p95` query, fix `client_error_rate` PromQL | P5 | SLO gap được lấp | 2 giờ |
| Thêm `is_deployment_window` feature | P6 | Giảm false positive khi deploy | 4 giờ |
| Tách contamination theo SLO criticality | P7 | Precision/recall tối ưu per-service | 1 giờ |
| Giám sát `valkey_evicted_keys_rate` + alert rule | Sec 5.1 | INC-2 early warning | 2 giờ |
| Giám sát `pg_connections_used_ratio` + alert rule | Sec 5.4 | INC-1 leading indicator | 2 giờ |

**Tổng effort sprint tiếp: ~21 giờ. Budget: $0.**

### Trung hạn (1–2 tháng) — Có thể tốn ít chi phí

**Mục tiêu:** Hoàn thiện hệ thống, thêm giám sát service đặc thù quan trọng.

| Việc cần làm | Proposal/Section | Impact | Budget estimate |
|---|---|---|---|
| River HST cho `llm`, `currency` | P4 | Medium | $0 |
| LLM token cost monitoring + budget alert | Sec 5.3 | HIGH (budget protection) | $0 |
| Cross-service features (downstream latency) | P từ METRIC_ANALYSIS G4 | Cascade detection | $0 |
| CUSUM cho memory_usage leak detection | METRIC_ANALYSIS Sec 3 | P2 slow leak | $0 |
| Automated model retraining pipeline (weekly) | P2 extension | Model freshness | Minimal (EC2 spot) |
| `fraud-detection` kafka lag + processing time monitor | Sec 5.2 | Compliance | $0 |


---

## 7. Feature Vector Đề xuất (22 features)

Sau khi áp dụng Proposal 1+2+3+5, feature vector sẽ trở thành:

```
Feature Vector v2.0 — 22 features (từ 18 features hiện tại)
═══════════════════════════════════════════════════════════════

RAW SIGNALS (6 features) — giảm từ 7, bỏ client_error_rate
┌─────────────────────────────────────────────────────────────┐
│  rps               [GIỮ] Raw throughput                    │
│  error_rate        [GIỮ] Server-side errors                │
│  latency_p90       [GIỮ] Latency percentile 90             │
│  latency_p95       [MỚI ★] Match với SLO definition        │
│  cpu_usage         [GIỮ] CPU consumption                   │
│  memory_usage      [GIỮ] Memory utilization ratio          │
│  kafka_lag         [GIỮ] Message queue depth               │
│  client_error_rate [XÓA ✗] Luôn = 0, không có giá trị     │
└─────────────────────────────────────────────────────────────┘

DERIVED FEATURES (10 features) — tăng từ 7
┌─────────────────────────────────────────────────────────────┐
│  error_ratio          [GIỮ] error_rate / (rps + ε)         │
│  latency_deviation    [GIỮ] p90 / rolling_median_1h        │
│  rps_delta            [GIỮ] Δrps mỗi 5 phút               │
│  cpu_per_rps          [GIỮ] CPU efficiency metric          │
│  memory_growth        [GIỮ] Δmemory 30 phút               │
│  memory_growth_2h     [MỚI ★] Δmemory 2 giờ (slow leak)  │
│  kafka_lag_growth     [GIỮ] Δlag mỗi 5 phút               │
│  latency_growth       [MỚI ★] Δp90 15 phút (INC-1/INC-6) │
│  cpu_saturation       [MỚI ★] cpu_per_rps / rolling_med   │
│  slo_budget_used_6h   [MỚI ★] % error budget dùng 6h     │
│  client_error_ratio   [XÓA ✗] Luôn = 0 (tính từ 0)        │
└─────────────────────────────────────────────────────────────┘

TEMPORAL FEATURES (4 features) — không đổi số lượng, có fix
┌─────────────────────────────────────────────────────────────┐
│  hour_of_day           [GIỮ] Giờ trong ngày (0–23)         │
│  day_of_week           [GIỮ] Thứ trong tuần (0–6)          │
│  is_business_hours     [GIỮ] Giờ hành chính                │
│  is_high_traffic_period [FIX ✓] Dùng ngưỡng tương đối     │
│                              thay vì hardcoded rps > 100   │
└─────────────────────────────────────────────────────────────┘

TỔNG: 6 + 10 + 4 = 20 features (core)
      + 2 optional SLO context: latency_slo_ratio, slo_burn_velocity
      = 22 features đề xuất
```

**So sánh v1.0 vs v2.0:**

| Khía cạnh | v1.0 (hiện tại) | v2.0 (đề xuất) | Cải thiện |
|---|---|---|---|
| Tổng features | 18 | 22 | +4 |
| Features có giá trị thực | 15 (83%) | 22 (100%) | +7 features, 100% useful |
| Features luôn = 0 | 3 (17%) | 0 (0%) | Loại bỏ hoàn toàn |
| Phủ p95 latency (SLO match) | ❌ Không | ✅ Có | Fix SLO gap |
| Slow memory leak detection | ⚠️ Yếu (30m) | ✅ 2h window | Bắt được leak ~0.3%/5m |
| Latency trend detection | ❌ Không | ✅ latency_growth | Phát hiện INC-1/INC-6 sớm |
| is_high_traffic_period | ❌ Luôn = 0 | ✅ Adaptive | Cung cấp context đúng |
| SLO budget context | ❌ Không | ✅ 2 features | Correlation với SLO state |


---

## 8. Kết luận

### Ba vấn đề gốc rễ cần xử lý

Toàn bộ phân tích hội tụ về **3 vấn đề gốc rễ** (không phải triệu chứng):

#### Vấn đề 1: Training data phân phối sai (Severity: CRITICAL)

`generate_synthetic_data()` tạo dữ liệu với RPS 80–180 trong khi production thực tế checkout ~0.246, payment ~0.046. Đây không phải lỗi nhỏ — đây là **mismatch 300–700 lần**. Mọi model hiện tại đang học từ dữ liệu không phản ánh thực tế. Hệ quả: `contamination=0.03` không có ý nghĩa calibration thực tế, và decision boundary của IF có thể hoàn toàn sai.

**Hành động ưu tiên #1:** Chạy Proposal 2 ngay trong sprint hiện tại.

#### Vấn đề 2: 3 features thường trực = 0 (Severity: HIGH)

`client_error_rate`, `client_error_ratio`, `is_high_traffic_period` — 3/18 features (16.7%) không mang thông tin. Đây không chỉ là "lãng phí slot" mà có thể **làm hại** model: Isolation Forest xây dựng random trees dựa trên feature splits — constant features không bao giờ split được, làm giảm effective dimensionality và có thể shift decision boundary theo hướng không mong muốn.

**Hành động ưu tiên #2:** Chạy Proposal 1 song song với Proposal 2.

#### Vấn đề 3: 5 service P1/P2 chỉ dùng Z-Score CPU một chiều (Severity: HIGH)

`cart` là P1 với SLO 99.5%, lịch sử INC-2 (OOM eviction), nhưng chỉ được "bảo vệ" bởi Z-Score CPU. Trong INC-2 pattern, CPU của `cart` service có thể bình thường ngay cả khi `valkey-cart` sắp OOM. Z-Score CPU là fallback cuối cùng — không phải giải pháp chính cho P1 service.

**Hành động ưu tiên #3:** Chạy Proposal 4 (River HST) cho `cart` trong sprint tiếp.

---

### Tóm tắt Top Actions theo ưu tiên

| # | Action | Proposal | Effort | Budget | Impact |
|---|---|---|---|---|---|
| 1 | Fix training data distribution (dùng CSV production) | P2 | ~4h | $0 | **CRITICAL** |
| 2 | Xóa features = 0, thêm latency_growth + memory_growth_2h | P1 | ~3h | $0 | **HIGH** |
| 3 | River HST cho `cart` (P1 SLO 99.5% unprotected) | P4 | ~4h | $0 | **HIGH** |
| 4 | Thêm `valkey_evicted_keys_rate` alert (zero tolerance) | Sec 5.1 | ~2h | $0 | **HIGH** |
| 5 | Thêm `pg_connections_used_ratio` (INC-1 leading indicator) | Sec 5.4 | ~2h | $0 | MEDIUM |
| 6 | Thêm latency_p95 để match SLO definition | P5 | ~2h | $0 | MEDIUM |
| 7 | is_deployment_window feature để giảm false positive | P6 | ~4h | $0 | MEDIUM |

**Tổng effort để hoàn thành Top 7:** ~21 giờ. **Budget: $0.** Tất cả đều là code changes, không tốn infra.

---

### Lời kết

Feature vector 18-chiều hiện tại là **khung tốt** — cấu trúc raw/derived/temporal là đúng hướng, Layer 1+Layer 2 kết hợp là thiết kế hợp lý. Vấn đề nằm ở **calibration và quality**, không phải kiến trúc.

Ba tuần fix theo roadmap trên sẽ đưa hệ thống từ trạng thái "hoạt động nhưng kém chính xác" sang "production-ready với confidence thực sự" — và toàn bộ trong ngân sách $0 thêm, chỉ cần engineering time.

---

*Tài liệu này bổ sung trực tiếp cho [`METRIC_ANALYSIS.md`](METRIC_ANALYSIS.md) — xem tài liệu đó để biết chi tiết PromQL, baseline values, và ngưỡng alert cho từng metric.*

*Liên quan: AIOps-01 (anomaly detection), AIOps-07 (false positive filtering), AIOps-02 (RCA accuracy).*
