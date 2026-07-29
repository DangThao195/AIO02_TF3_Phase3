# AIOps Detection Engine — Update v2: Extended Isolation Forest (EIF) Upgrade

> Tài liệu này mô tả toàn bộ hành trình nâng cấp Engine phát hiện bất thường từ v1
> (3-Sigma First-Drift + Topology Symptom Penalty trên nền Isolation Forest gốc) lên
> **v2 (Extended Isolation Forest)**, bao gồm: các vấn đề phát hiện được, cách giải quyết,
> phương pháp đánh giá, dữ liệu test dùng để kiểm chứng, kết quả thực nghiệm, và kết luận
> cuối cùng. Đây là phần tiếp nối trực tiếp của `docs_enhanced_engine.md` (tài liệu v1).

---

## 📋 1. Bối cảnh & Lý do nâng cấp lên v2

Sau khi hoàn thành v1 (3-Sigma First-Drift + Topology Downstream Penalty trên Isolation
Forest gốc), quá trình benchmark thực nghiệm liên tục phát hiện các giới hạn **của chính
mô hình nền (Isolation Forest trục-song song)**, độc lập với 2 lớp cổng hậu kiểm của v1.
Cụ thể, trên bộ dữ liệu test khớp phân phối train (xem mục 4), Old Engine chỉ đạt
**Recall 0.96%** trên 7 kịch bản sự cố thật — gần như không phát hiện được gì. Mục tiêu
của v2 là thay thế thuật toán cô lập nền bằng **Extended Isolation Forest (EIF)** để giải
quyết tận gốc các giới hạn này, đồng thời kiểm chứng thêm 2 câu hỏi kiến trúc quan trọng:
(1) gộp 7 model thành 1 có tốt hơn không, (2) model có thực sự hiểu ngữ cảnh (context-aware)
hay chỉ đơn thuần phát hiện độ lệch thống kê.

---

## 🔍 2. Các bước đã thực hiện (theo trình tự thời gian)

### Bước 1 — Sửa lỗi trong benchmark v1 và Topology Penalty
- Benchmark A/B cũ chỉ đo trên 5 điểm mẫu (`np.linspace`) thay vì toàn bộ dataset → viết lại
  để chạy full-dataset, không sampling.
- Topology Penalty bị lỗi định hướng đồ thị (hợp cả 4 tập hợp ancestors/descendants/
  predecessors/successors) → sửa chỉ dùng `nx.descendants(graph, service)` đúng với
  `services.json` và unit test có sẵn.

### Bước 2 — Phát hiện vấn đề lệch phân phối dữ liệu train/test
- Tập validation cũ (`generate_synthetic_data()`, dùng cho kịch bản SCN-A→SCN-I) có traffic
  **quy mô lớn hơn ~200 lần** so với dữ liệu Prometheus thật dùng để train
  (`*_clean_baseline.csv`): rps thật trung bình 0.33, rps synthetic "Normal" trung bình 70.7.
- Hệ quả: Precision đo được trên tập này chỉ ~4%, gây hiểu lầm nghiêm trọng — không phản
  ánh đúng chất lượng model trên dữ liệu thật.

### Bước 3 — Xây dựng bộ "Realistic Incident Test Case" khớp phân phối train
- Thay vì dùng generator riêng biệt, **splice trực tiếp lên `*_clean_baseline.csv` thật**:
  giữ nguyên 100% các dòng baseline gốc, chỉ ghi đè giá trị đúng cửa sổ xảy ra sự cố, biên
  độ hiệu chỉnh theo percentile thật của chính service đó.
- Mở rộng dần từ 5 → 7 → **9 kịch bản đầy đủ khớp mandate gốc** (SCN-A đến SCN-I trong
  `implementation_plan.md`) + 2 kịch bản bổ sung kiểm tra context-awareness (CTX-1, CTX-2).
  Chi tiết đầy đủ ở mục 4.

### Bước 4 — Chẩn đoán tận gốc 3 giới hạn kiến trúc của Isolation Forest (v1)
Bằng cách in trực tiếp raw score từng tick trên model đã train, xác định 3 cơ chế thất bại:
1. **Dimensionality, không phải magnitude**: tăng 1 feature (`cpu_usage`) gấp 1000 lần, giữ
   nguyên 17 feature khác → score không đổi 1 ly. IF trục-song song cô lập từng chiều độc
   lập, không đủ nhạy với tổ hợp đa chiều nếu mỗi chiều không quá cực đoan.
2. **Feature "delta" chỉ bắt tick đầu tiên**: `rps_delta`, `memory_growth`, `kafka_lag_growth`
   quay về ~0 ngay khi mức bất thường mới ổn định (plateau) — chỉ tick đầu của sự cố dạng
   step-change bị phát hiện, các tick sau bị bỏ sót.
3. **"Boiling-frog" với sự cố ramp dần**: `latency_deviation` (tỷ lệ so với rolling median
   1h) bị chính sự cố "kéo" theo khi ramp diễn ra chậm hơn cửa sổ rolling — baseline tham
   chiếu trôi cùng tốc độ với sự cố nên không bao giờ lệch đủ để bị flag.

### Bước 5 — Sửa 2 bug feature engineering phát hiện trong quá trình chẩn đoán
1. **`latency_deviation` nổ số vô nghĩa**: floor cố định `1e-5` khiến tỷ lệ nổ lên tới
   **861,663** khi `rolling_median_1h ≈ 0` (rất phổ biến ở service traffic thưa). Sửa: floor
   scale theo p95 latency của chính service, clip ratio về `[0, 50]`.
2. **Train/serve skew**: `anomaly_detector.py` (runtime production) có một bản sao CÔNG THỨC
   RIÊNG, lệch với `train_anomaly_model_local.py` (script training). Đã hợp nhất về DUY NHẤT
   một hàm `feature_engineering()` dùng chung cho training, benchmark, và runtime.
3. **`is_high_traffic_period` dùng ngưỡng tuyệt đối cứng `rps > 100`**: với 5/7 service thật
   (checkout, payment, product-reviews, recommendation, shipping), RPS không bao giờ chạm
   100 → feature này LUÔN = 0, model không có tín hiệu "cao điểm của chính service này". Sửa
   thành ngưỡng tương đối theo median RPS của chính chuỗi đang xét.
   *(Lưu ý: fix này không đơn độc giải quyết được vấn đề ngữ cảnh — xem mục 6.3.)*

### Bước 6 — Triển khai Extended Isolation Forest (EIF)
- Package `eif` gốc (PyPI) build lỗi trên môi trường Cython/numpy 2.x hiện tại → **tự cài
  đặt thuần NumPy** (`eif_model.py`), tránh phụ thuộc native-compile không ổn định trong
  production.
- Khác biệt cốt lõi: mỗi node split bằng **siêu phẳng ngẫu nhiên đa chiều**
  `(x - p) · n < 0` (kết hợp nhiều feature cùng lúc) thay vì chỉ 1 feature như IF gốc.
- API tương thích hoàn toàn với `sklearn.IsolationForest` (`fit`, `predict`,
  `decision_function`) — có thể dùng thay thế trực tiếp trong mọi pipeline hiện có.
- Verify nhanh: tăng 1 feature gấp 1000 lần → EIF phát hiện bất thường ngay ở x2 (IF gốc thì
  x1000 vẫn không đổi).

### Bước 7 — Retrain & benchmark EIF vs IF (per-service)
- Train 7 model EIF trên **100% dữ liệu `*_clean_baseline.csv`**, cùng feature set
  (`config.MODEL_FEATURE_COLUMNS`), cùng `contamination=0.03` với IF — chỉ khác thuật toán.
- `scripts/train_eif_models_v2.py`, model lưu tại `models_v2/` (không đụng `models/` của v1).

### Bước 8 — Kiểm tra câu hỏi kiến trúc: gộp 7 service thành 1 model
- `scripts/train_merged_models.py`: gộp toàn bộ 7 service thành 1 tập train (14,106 dòng),
  thêm 7 cột one-hot `svc_{service}` để model phân biệt. **Feature engineering vẫn tính
  RIÊNG theo từng service TRƯỚC KHI gộp** (bắt buộc, vì rolling window phải đúng ngữ cảnh
  time-series của 1 service, không được tính lẫn qua ranh giới service).
- Train 1 IF gộp + 1 EIF gộp, cùng hyperparameter với bản riêng-service.

### Bước 9 — Kiểm tra câu hỏi context-awareness
- Xây 2 kịch bản CTX-1 (RPS+CPU tăng tỷ lệ thuận, giả lập giờ cao điểm, Ground Truth=Normal)
  và CTX-2 (CPU tăng vô cớ không liên quan traffic, Ground Truth=Incident).
- **Phát hiện quan trọng**: premise ban đầu của CTX-1 sai — kiểm tra lại thấy
  `corr(rps, cpu_usage)` thật của service `recommendation` gần như bằng 0 (`-0.049`), nghĩa
  là CPU không hề tăng theo RPS trong thực tế của service này. Đã tự sửa lại bằng cách kiểm
  tra trên **dữ liệu top-5% RPS THẬT** (không chỉnh sửa gì) thay vì giả lập tương quan không
  có thật.
- Phát hiện gốc rễ: **61/61 False Positive của Old Engine trên toàn bộ clean baseline của
  `recommendation` đều rơi đúng vào các tick RPS cao thật** — xác nhận trực tiếp mối lo của
  người dùng: traffic cao điểm hợp lệ bị báo động nhầm. Sửa `is_high_traffic_period` (bước 5)
  không giải quyết được vấn đề này (FP không đổi sau khi sửa) vì Isolation-Forest-family
  coi tất cả feature bình đẳng — 1 cờ ngữ cảnh không đủ sức lấn át 17 chiều còn lại.

### Bước 10 — Benchmark toàn diện 4 kiến trúc trên đủ 9 kịch bản mandate
- `scripts/benchmark_full_mandate_all4.py`: so sánh **IF riêng / IF gộp / EIF riêng / EIF gộp**
  trên đủ 9 kịch bản SCN-A→SCN-I, full dataset, không sampling.
- Đối chiếu thêm với tập synthetic cũ (`scripts/benchmark_synthetic_4way.py`) để xác nhận
  EIF chỉ thắng khi phân phối test khớp phân phối train.

---

## 🧪 3. Phương pháp đánh giá (Evaluation Methodology)

**Nguyên tắc công bằng bắt buộc** (áp dụng xuyên suốt mọi benchmark trong v2):
1. **Full dataset, không sampling** — mọi phép đo chạy trên 100% dữ liệu mỗi file.
2. **Cùng tiêu chí đánh giá với Old Engine** — công thức Precision/Recall/F1/FPR giữ nguyên
   từ `train_anomaly_model_local.py::train_and_evaluate()`, bao gồm cách xử lý đặc biệt cho
   kịch bản FP-resistance (SCN-A, SCN-G: không có nhãn Anomaly thật, chỉ đo FPR).
3. **Cùng feature set, cùng hyperparameter** giữa mọi kiến trúc so sánh — chỉ khác biến số
   đang kiểm chứng (thuật toán cô lập, hoặc gộp/tách service).
4. **Reproducibility** — mọi nguồn ngẫu nhiên seed từ `config.BENCHMARK_RANDOM_SEED = 42`.

---

## 📁 4. Dữ liệu đánh giá (`datametric/realistic_test_cases/`)

Toàn bộ 13 file test case (12 kịch bản + 1 file symptom phụ của SCN-F) được lưu tại
**`aiops-engine update/datametric/realistic_test_cases/`**, sinh bằng
`scripts/generate_realistic_incident_testsets.py`,
`scripts/generate_mandate_scenarios_full.py`, và
`scripts/generate_context_awareness_testsets.py`.

**Phương pháp chung**: splice trực tiếp lên `*_clean_baseline.csv` THẬT — giữ nguyên 100%
các dòng baseline gốc (đảm bảo khớp phân phối train), chỉ ghi đè giá trị đúng cửa sổ xảy ra
sự cố, biên độ hiệu chỉnh theo percentile thật của chính service (không áp đặt số tùy ý).

| File | Service | Mandate | Ground Truth | Mô tả |
| :--- | :--- | :---: | :---: | :--- |
| `SCN-A_frontend_node_drain_fp_resistance.csv` | frontend | SCN-A | Normal | Spike nhiễu 1-tick, kiểm tra kháng báo động giả |
| `SCN-B_product-reviews_ai_spam_dos.csv` | product-reviews | SCN-B | Incident (8 ticks) | RPS flood + error_rate tăng (AI Spam DoS) |
| `SCN-C_payment_slow_ram_leak.csv` | payment | SCN-C | Incident (24 ticks) | Memory ramp tuyến tính ~2h (Slow RAM Leak) |
| `SCN-D_recommendation_http_4xx_scan.csv` | recommendation | SCN-D | Incident (10 ticks) | client_error_rate tăng vọt (bot quét 4xx) |
| `SCN-E_product-catalog_network_packet_loss.csv` | product-catalog | SCN-E | Incident (10 ticks) | client_error + latency dao động ngắt quãng |
| `SCN-F_product-catalog_ROOT_CAUSE_cascading_failure.csv` | product-catalog | SCN-F (root) | Incident (8 ticks) | Root cause thật của Cascading Failure |
| `SCN-F_checkout_SYMPTOM_cascading_failure.csv` | checkout | SCN-F (symptom) | Incident (8 ticks) | Triệu chứng lan truyền (checkout phụ thuộc product-catalog theo `services.json`) |
| `SCN-G_frontend_thundering_herd.csv` | frontend | SCN-G | Normal | RPS+latency tăng theo ĐÚNG tương quan thật (corr=0.83) — traffic thật, không phải sự cố |
| `SCN-H_shipping_gradual_slo_erosion.csv` | shipping | SCN-H | Incident (24 ticks) | Ramp tuyến tính latency+error (Gradual SLO Erosion) |
| `SCN-I_recommendation_cpu_steal.csv` | recommendation | SCN-I | Incident (12 ticks) | CPU/Memory ramp (Resource Exhaustion / CPU Steal) |
| `EXTRA-01_checkout_sustained_incident_generic.csv` | checkout | (bổ sung) | Incident (6 ticks) | Sustained latency+error incident tổng quát |
| `CTX-1_recommendation_peak_hour_context_normal.csv` | recommendation | (bổ sung) | Normal | Kiểm tra context-awareness (RPS+CPU proportional) |
| `CTX-2_recommendation_disproportionate_cpu_context_incident.csv` | recommendation | (bổ sung) | Incident (12 ticks) | CPU tăng vô cớ không liên quan traffic |

**Script benchmark chính thức, cuối cùng**: `scripts/benchmark_full_mandate_all4.py` —
chạy cả 4 kiến trúc (IF riêng / IF gộp / EIF riêng / EIF gộp) trên đủ 9 kịch bản SCN-A→SCN-I.

Để đối chiếu, `scripts/benchmark_synthetic_4way.py` chạy lại cùng 4 kiến trúc trên tập
synthetic cũ (`generate_synthetic_data()`, quy mô traffic lệch ~200x) — dùng để minh chứng
kết luận ở mục 6.2, không dùng làm benchmark chính thức.

---

## 📊 5. Kết quả thực nghiệm

### 5.1 EIF vs IF (per-service), trên bộ Realistic Test Case đầu tiên (5 kịch bản)

| Kịch bản | Old (IF) Recall | EIF Recall |
| :--- | :---: | :---: |
| Cascading (root cause) | 12.5% (1/8) | **100%** (8/8) |
| Cascading (symptom) | 0% (0/8) | **100%** (8/8) |
| Gradual SLO Erosion | 0% (0/24) | **100%** (24/24) |
| Resource Exhaustion | 0% (0/12) | **100%** (12/12) |
| **Aggregate (n=10,083)** | P=2.19% R=12.07% F1=3.71% | **P=15.72% R=100.00% F1=27.17%** |
| FPR (không đổi) | 3.09% | 3.08% |

### 5.2 Đủ 4 kiến trúc trên đủ 9 kịch bản mandate SCN-A→SCN-I (n=16,132 ticks incident)

| Engine | Precision | Recall | F1 | FPR |
| :--- | :---: | :---: | :---: | :---: |
| IF tách-service (Old, 7 model) | 0.20% | 0.96% | 0.34% | 3.05% |
| IF gộp (1 model) | 2.07% | 10.58% | 3.46% | 3.22% |
| **EIF tách-service (7 model)** | **17.16%** | **100.00%** | **29.30%** | 3.11% |
| EIF gộp (1 model) | 15.62% | **100.00%** | 27.01% | 3.48% |

Chi tiết theo từng kịch bản (EIF tách-service): SCN-B/C/D/E/F(x2)/H/I đều đạt **Recall 100%**.

### 5.3 Kiểm chứng trên tập synthetic cũ (đối chiếu, không dùng làm benchmark chính)

| Engine | Precision | Recall | **FPR** |
| :--- | :---: | :---: | :---: |
| IF tách-service | 6.95% | 78.97% | **34.26%** |
| EIF tách-service | 3.24% | 100.00% | **96.76%** ⚠️ |
| IF gộp | 3.31% | 99.60% | 94.19% ⚠️ |
| EIF gộp | 3.24% | 100.00% | 96.76% ⚠️ |

Trên tập lệch phân phối train ~200 lần, **EIF thể hiện tệ hơn IF** (FPR 97% vs 34%) — xem
giải thích ở mục 6.2.

### 5.4 Kiểm tra Context-Awareness (CTX-1, real top-5% RPS ticks của `recommendation`)

| | Trước sửa `is_high_traffic_period` | Sau khi sửa |
| :--- | :---: | :---: |
| Old báo động nhầm trên RPS cao thật (top 5%, n=99) | 61/99 | 61/99 |
| EIF báo động nhầm trên RPS cao thật (top 5%, n=99) | 54/99 | 54/99 |

Việc sửa ngưỡng tuyệt đối → tương đối **không cải thiện** FP trên traffic cao điểm thật.

---

## 💡 6. Nhận xét & Kết luận

### 6.1 EIF vượt trội IF khi phân phối test khớp phân phối train — kết luận vững nhất
Trên mọi kịch bản mandate (9/9), mọi kiến trúc (riêng/gộp), EIF đạt **Recall 100%** so với
0.96%-10.58% của IF, trong khi FPR nền gần như không đổi (~3.1-3.5%). Nguyên nhân kỹ thuật:
EIF cô lập bằng siêu phẳng ngẫu nhiên đa chiều, khắc phục trực tiếp 3 giới hạn đã chẩn đoán
ở IF (dimensionality, delta-feature-chỉ-bắt-tick-đầu, boiling-frog).

### 6.2 Nhưng EIF không phải "thuật toán tốt hơn tuyệt đối" — nó nhạy với lệch phân phối hơn IF
Trên tập synthetic cũ (lệch phân phối train ~200 lần), EIF có FPR tệ hơn IF (97% vs 34%).
Lý do: EIF nhạy với lệch **đa chiều** hơn IF — khi CHÍNH phần "Normal" của test set cũng lệch
đa chiều so với training, độ nhạy đó quay lại gây hại. IF (trục-song song) "vô tình" bền hơn
trong tình huống này vì mỗi split chỉ nhìn 1 chiều, lệch cực đoan trên 1 chiều bị giới hạn
đóng góp vào score. **Bài học: chọn thuật toán không quan trọng bằng việc đảm bảo dữ liệu
test khớp phân phối train** — đây là lý do quyết định chuyển sang bộ Realistic Test Case
(mục 4) là đúng đắn.

### 6.3 Gộp 7 service thành 1 model: không giải quyết được vấn đề ngữ cảnh, và không có lợi ích rõ ràng
- Trên bài test context-awareness (CTX-1/traffic cao điểm thật), model gộp có FPR **cao hơn**
  model riêng-service (145 vs 79 FP trên CTX-1 gốc trước khi chuẩn hoá dataset cuối) — gộp
  làm loãng ranh giới "bình thường" giữa 7 service có quy mô khác nhau hoàn toàn.
- Trên benchmark mandate đầy đủ, EIF gộp (F1=27.01%) nhỉnh hơn IF gộp nhưng **kém hơn EIF
  tách-service** (F1=29.30%). Gộp chỉ có lợi ích duy nhất là vận hành đơn giản hơn (1 file
  model), không mang lại cải thiện chất lượng phát hiện rõ ràng.

### 6.4 Vấn đề "context-awareness" (CPU tăng vì đông khách hay vì sự cố?) chưa được giải quyết triệt để
Cả IF và EIF, dù gộp hay tách, đều **không phân biệt được** "độ lệch có lý do chính đáng"
với "độ lệch bất thường thật" — vì cả 2 thuật toán coi tất cả feature bình đẳng khi tìm điểm
hiếm trong không gian nhiều chiều. Thêm 1 feature ngữ cảnh (`is_high_traffic_period`,
`cpu_per_rps`) là điều kiện CẦN nhưng KHÔNG ĐỦ — model không tự "ưu tiên" feature đó hơn các
chiều khác. Để giải quyết triệt để, cần đổi paradigm mô hình hoá:
- **Residual-based**: train model regression dự đoán giá trị kỳ vọng của metric (latency,
  cpu...) cho trước rps + giờ trong ngày, rồi chỉ báo động khi PHẦN DƯ (residual) bất
  thường — chưa được triển khai trong v2, đề xuất cho v3.
- Hoặc **conditional model theo traffic-bucket**: train riêng theo từng dải RPS (low/medium/
  high) của cùng 1 service.

### 6.5 Khuyến nghị triển khai
**EIF tách-theo-service** (`models_v2/`) là lựa chọn cân bằng nhất trong 4 kiến trúc đã kiểm
chứng: Recall 100% trên toàn bộ 9 kịch bản mandate, F1 cao nhất (29.30%), FPR thấp nhất
trong nhóm EIF (3.11%), và tránh được rủi ro loãng ranh giới khi gộp service. Hạn chế cần
lưu ý trước khi triển khai production: (a) chưa giải quyết được vấn đề context-awareness khi
traffic tăng có lý do chính đáng (mục 6.4), (b) chưa kiểm chứng trên dữ liệu sự cố thật quy
mô lớn (chỉ có 13 điểm real-incident trong toàn bộ repo — xem `docs_enhanced_engine.md` mục
3.2), (c) chi phí tính toán của EIF cao hơn IF (siêu phẳng ngẫu nhiên đòi hỏi nhiều phép
nhân ma trận hơn so với so sánh 1 giá trị/node của IF trục-song song) — cần benchmark thêm
về độ trễ inference nếu triển khai real-time.
