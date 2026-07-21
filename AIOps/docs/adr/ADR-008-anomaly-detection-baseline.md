# ADR-008: Lựa Chọn Phương Pháp Phát Hiện Bất Thường Đa Tầng (Anomaly Detection Strategy)

- **Trạng thái**: Accepted
- **Ngày quyết định**: 17/07/2026
- **Tác giả / Ký tên**: Hảo (Leader team AIOps — Task Force 3)
- **Phạm vi tác động**: `anomaly_detector.py`, training pipeline, tất cả 7 service trong cụm `techx-tf3`
- **Thay thế**: ADR-002-anomaly-detection-baseline.md (đổi số để tránh trùng với ADR-002-caching-and-fallback-strategy.md và ADR-007 trong CONSOLIDATED_ADR)

---

## 1. Bối Cảnh (Context)

Hệ thống AIOps Engine cần phát hiện bất thường trên telemetry của 7 service trong cụm EKS. Có ba thách thức cốt lõi cần giải quyết:

1. **Busy vs Broken:** Hệ thống phải phân biệt "tải cao nhưng healthy" với "lỗi thật" — không báo nhầm khi RPS tăng đột biến vào giờ cao điểm.
2. **Masking:** Một đợt spike tải lớn không được che khuất một lỗi nhỏ âm ỉ bên dưới.
3. **Baseline per-service:** Mỗi service có profile tải và resource hoàn toàn khác nhau (ví dụ `frontend` RPS = 4.59 vs `payment` RPS = 0.046). Không thể dùng ngưỡng tuyệt đối chung.

Dữ liệu baseline được thu thập từ cụm EKS thực tế ngày 14/07/2026 (`datametric/*_train.csv`).

---

## 2. Các Phương Án Đã Xem Xét

### Phương án A: Static Threshold Alerting (Ngưỡng Tĩnh)
**Mô tả:** Đặt ngưỡng cứng: ví dụ `error_rate > 0.01` → alert, `latency_p90 > 500ms` → alert.

**Ưu điểm:**
- Đơn giản, dễ implement, dễ giải thích.
- Không cần training data.

**Nhược điểm:**
- Không thích nghi theo tải: `latency_p90 = 200ms` là bình thường lúc tải cao nhưng là bất thường lúc idle.
- Dễ spam cảnh báo giả (Alert Fatigue) khi tải cao hợp lệ.
- Không phát hiện được anomaly âm thầm như memory leak hoặc kafka lag tích tụ chậm.

**Quyết định: Từ chối.** Không đáp ứng yêu cầu "baseline theo từng service, không báo nhầm khi tải cao."

---

### Phương án B: Univariate Z-Score (Mỗi metric một ngưỡng động)
**Mô tả:** Với mỗi metric, tính Z-Score so với baseline rolling 7 ngày: `Z = (x - μ) / σ`. Kích hoạt cảnh báo khi `|Z| > 3.0`.

**Ưu điểm:**
- Ngưỡng động theo từng service, thích nghi với tải cao.
- Không cần training ML phức tạp.
- Dễ giải thích cho SRE.

**Nhược điểm:**
- Univariate: xét từng metric độc lập, bỏ sót tương quan chéo. Ví dụ: `cpu_per_rps` tăng mà `rps` không tăng = anomaly, nhưng Z-Score của riêng từng chỉ số có thể bình thường.
- Không phát hiện được "Masking": spike RPS lớn làm `error_ratio` trông nhỏ → bỏ sót lỗi âm ỉ.
- Giả định phân phối Gaussian — không đúng với traffic thực tế (right-skewed).

**Quyết định: Giữ làm Fallback.** Dùng khi IF model chưa được train hoặc không load được. Không dùng làm primary detector.

---

### Phương án C: Supervised ML (Random Forest, XGBoost với labeled data)
**Mô tả:** Train classifier có giám sát với nhãn Normal/Anomaly từ lịch sử incidents.

**Ưu điểm:**
- Precision/Recall cao nếu có đủ labeled data.
- Có thể học các pattern phức tạp.

**Nhược điểm:**
- Cụm EKS chỉ có data từ 14/07/2026 — không đủ lịch sử lỗi để train.
- Cần labeling thủ công — tốn công và chủ quan.
- Dễ overfit nếu dataset nhỏ.

**Quyết định: Từ chối cho phase hiện tại.** Có thể xem xét lại khi tích lũy đủ labeled incident history (> 6 tháng).

---

### Phương án D: Isolation Forest — Multivariate Unsupervised ✅ **[ĐƯỢC CHỌN]**
**Mô tả:** Train Isolation Forest riêng cho từng service với 18 features đa chiều, bao gồm raw metrics, derived features (chuẩn hóa), và contextual features (temporal).

**Ưu điểm:**
- **Unsupervised:** Không cần labeled data — phù hợp với cluster mới.
- **Multivariate:** Phát hiện anomaly dựa trên tương quan nhiều chiều, bắt được masking qua `error_ratio`.
- **Per-service baseline:** Train model riêng cho từng service → mỗi model học profile bình thường riêng.
- **Không Gaussian assumption:** Isolation Forest dùng random partition trees, hoạt động tốt với phân phối bất kỳ.
- **Tốc độ cao:** O(n log n) inference, phù hợp chu kỳ 30 giây.
- **Baseline tự cập nhật:** CronJob re-train hàng tuần.

**Nhược điểm:**
- Cần đủ normal data để train (≥ 7 ngày).
- Khó giải thích tại sao một điểm cụ thể bị đánh dấu anomaly (black-box một phần).
- `contamination=0.03` cần tune — nếu sai sẽ ảnh hưởng precision.

**Quyết định: Chấp nhận làm Primary Detector.**

---

## 3. Quyết Định Kiến Trúc (Decision)

### 3.1. Kiến Trúc Hai Lớp

```
Lớp 1 (Reactive):   SLO Burn Rate Monitor
                     → Kích hoạt khi error budget đang cháy
                     → Ngưỡng: BurnRate ≥ 14.4× (5m AND 1h)

Lớp 2 (Proactive):  Isolation Forest (18 features, per-service)
                     → Kích hoạt khi SLO còn xanh nhưng metrics lệch
                     → Phát hiện sớm trước khi SLO bị vi phạm

Fallback:           Z-Score Univariate
                     → Kích hoạt khi model IF không load được
```

### 3.2. Lý Do Chọn K = 14.4 Cho SLO Burn Rate

SLO target = 99.9% (error budget = 0.1%). Burn Rate = 1.0 → tiêu hết budget trong 30 ngày.

Với K = 14.4:
```
t_cạn_kiệt = (30 ngày × 24h × 60 phút) / 14.4 ≈ 50 phút
```

Ngưỡng 14.4 được khuyến nghị bởi Google SRE Workbook cho "Page-worthy alert" — lỗi đe dọa toàn bộ error budget trong < 1 giờ. Thấp hơn (ví dụ K = 6) → quá nhiều alert. Cao hơn (K = 20) → phát hiện quá muộn.

### 3.3. Lý Do Chọn 18 Features

| Nhóm | Features | Lý do |
|---|---|---|
| Raw (7) | rps, cpu, memory, latency_p90, error_rate, client_error_rate, kafka_lag | Golden Signals + Saturation + Queue |
| Derived (7) | error_ratio, client_error_ratio, latency_deviation, rps_delta, cpu_per_rps, memory_growth, kafka_lag_growth | Chuẩn hóa → chống masking; delta → phát hiện trend |
| Contextual (4) | hour_of_day, day_of_week, is_business_hours, is_high_traffic_period | Giúp model phân biệt "bình thường theo giờ" |

`error_ratio = error_rate / (rps + ε)` là feature quan trọng nhất cho anti-masking: khi RPS tăng 7× nhưng lỗi tăng theo, ratio vẫn bất thường và model phát hiện được.

### 3.4. Hyperparameters Isolation Forest

```python
IsolationForest(
    n_estimators=200,      # Đủ nhiều cây để stable
    contamination=0.03,    # Giả định 3% data training là anomaly nhẹ
    max_features=0.8,      # Random subspace để tránh overfitting
    random_state=42        # Reproducibility
)
```

---

## 4. Hệ Quả (Consequences)

### Tích cực
- Baseline per-service: không báo nhầm khi `frontend` RPS = 20 req/s (bình thường giờ cao điểm) hay `checkout` RPS = 0.25 req/s (bình thường).
- Anti-masking qua `error_ratio`: spike tải không che được lỗi nhẹ âm ỉ.
- MTTD giảm từ 10–50 phút (Alertmanager truyền thống) xuống 30–35 giây (chu kỳ quét đầu tiên).
- Tự cập nhật baseline qua CronJob re-train hàng tuần.

### Nhược điểm & Rủi Ro
- **Data quality dependency:** Baseline hiện tại thu thập khi cluster idle (14/07/2026). Nếu hệ thống chưa có đủ traffic pattern đa dạng, model có thể flag "tải cao healthy" là anomaly cho đến khi re-train với data phong phú hơn.
- **Explainability gap:** IF không trả về lý do cụ thể tại sao một điểm bị flag. Đã giải quyết bằng LLM diagnostic layer ở Phase 4.
- **contamination tuning:** Giá trị 0.03 cần validate với data thực tế. Sẽ điều chỉnh sau khi có đủ labeled incidents từ bộ kịch bản test.

---

## 5. Phương Án Thay Thế Trong Tương Lai

Khi tích lũy đủ labeled incident history (> 6 tháng, > 50 incidents):
- Nâng cấp lên supervised model (XGBoost hoặc LSTM time-series)
- Thêm feature `error_ratio_1h` để bổ sung temporal context cho error signal

---

*Tài liệu phân tích metrics chi tiết: [Baseline_metric.md](../Baseline_metric.md)*

---

## Lịch sử phiên bản

| Phiên bản | Ngày | Thay đổi |
|---|---|---|
| v1.0 | 17/07/2026 | Khởi tạo — ADR-002-anomaly-detection-baseline |
| v1.1 | 20/07/2026 | Đổi thành ADR-008, bổ sung "Alternatives Considered", cập nhật baseline từ datametric thực tế |
