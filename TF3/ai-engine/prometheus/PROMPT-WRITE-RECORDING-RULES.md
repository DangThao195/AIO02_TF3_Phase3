# 🧠 Prompt Chuyên Sâu: Viết Prometheus Recording Rules & Burn-rate Alerts cho hệ thống SLO Monitoring

> **Skills đã tham chiếu:**
> - `prometheus-configuration` — Chuẩn cấu hình, recording rules, validation
> - `slo-architect` — Google SRE Workbook, error budget math, multi-window burn-rate
> - `observability-designer` — Three pillars, Golden Signals, alert fatigue prevention
> - `grafana-dashboards` — RED method, dashboard panels cho SLO
> - `prompt-engineer` — Framework RODES + Chain of Thought

---

## 📌 PHẦN 1: ROLE (Vai trò)

```
Bạn là một Senior SRE Engineer chuyên về:
- Prometheus recording rules & alerting rules
- SLO/SLI engineering theo phương pháp Google SRE Workbook (Chapter 5)
- Multi-window multi-burn-rate alerting
- OpenTelemetry spanmetrics
- Kubernetes observability trên AWS EKS

Bạn đang làm việc trong team AIOps, chịu trách nhiệm viết cấu hình rules
để hệ thống AI engine tự động phát hiện sự cố dựa trên tỷ lệ cạn kiệt Error Budget.
```

---

## 📌 PHẦN 2: OBJECTIVE (Mục tiêu)

```
Viết 2 file YAML cấu hình Prometheus:

1. recording_rules.yaml — Recording Rules tính toán SLI (Service Level Indicator)
2. burnrate_alerts.yaml — Alert Rules cảnh báo khi Error Budget cạn kiệt quá nhanh

Hai file này phục vụ hệ thống Multi-window Multi-burn-rate SLO Alerting
cho 3 service: checkout, frontend, cart trên một e-commerce platform (OTel Demo trên EKS).
```

---

## 📌 PHẦN 3: DETAILS (Chi tiết kỹ thuật đầu vào)

### 3.1. SLO Definitions (Service Level Objectives)

```yaml
slos:
  - service: checkout
    sli_type: request-success-rate
    target: 99%          # error_budget = 1% = 0.01
    criticality: revenue-critical
    windows: [5m, 30m, 1h, 6h]   # 4 cửa sổ cho multi-window

  - service: frontend
    sli_type: request-success-rate
    target: 99.5%        # error_budget = 0.5% = 0.005
    criticality: user-facing
    windows: [5m, 1h]             # 2 cửa sổ

  - service: cart
    sli_type: request-success-rate
    target: 99.5%        # error_budget = 0.5% = 0.005
    criticality: user-facing
    windows: [5m, 1h]             # 2 cửa sổ

  - service: frontend
    sli_type: request-latency-p95
    target: "< 1 second"
    criticality: user-experience
    windows: [5m]                 # 1 cửa sổ
```

### 3.2. Raw Metrics đã xác nhận trên AWS EKS

```
Nguồn: OpenTelemetry Collector → spanmetrics connector → Prometheus

Metric 1: traces_span_metrics_calls_total
  Labels: service_name, span_name, status_code
  Ý nghĩa: Counter — tổng số span (request) của mỗi service
  Giá trị lỗi: status_code="STATUS_CODE_ERROR"

Metric 2: traces_span_metrics_duration_milliseconds_bucket
  Labels: service_name, span_name, le
  Ý nghĩa: Histogram — phân bố latency (đơn vị: milliseconds)

Đã xác nhận bằng lệnh:
  kubectl exec prometheus-pod -- wget -qO- \
    "http://localhost:9090/api/v1/label/__name__/values" | jq .

Kết quả: Cả 2 metrics đều có data.
Hiện trạng rules: CHƯA CÓ (GET /api/v1/rules trả về groups: [])
```

### 3.3. Hạ tầng

```
- Cluster:    EKS techx-corp-tf3
- Namespace:  techx-tf3
- Prometheus: Chạy dạng pod, ConfigMap-based config
- Scrape interval: 60s (lưu ý: ảnh hưởng đến cửa sổ ngắn)
- Alertmanager: Đã deploy, chưa có rules
- Grafana: Đã deploy, đang chờ recording rules để hiển thị SLO dashboard
```

### 3.4. Bảng ngưỡng Burn-rate (Google SRE Workbook Chapter 5)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CÔNG THỨC: threshold = burn_rate × error_budget                        │
│                                                                         │
│ SLO 99% (error_budget = 0.01):                                         │
│   Critical: 14.4 × 0.01 = 0.144  (cửa sổ: 1h + 5m)                  │
│   Warning:   6.0 × 0.01 = 0.060  (cửa sổ: 6h + 30m)                 │
│                                                                         │
│ SLO 99.5% (error_budget = 0.005):                                      │
│   Critical: 14.4 × 0.005 = 0.072 (cửa sổ: 1h + 5m)                  │
│                                                                         │
│ BÁN LÝ multi-window:                                                   │
│   Alert CHỈ bắn khi CẢ cửa sổ dài VÀ ngắn cùng vượt ngưỡng          │
│   → Cửa sổ dài: giảm false-negative (bỏ sót sự cố kéo dài)          │
│   → Cửa sổ ngắn: giảm false-positive (bỏ qua spike thoáng qua)      │
│   → Kết hợp AND: cực kỳ ít noise                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📌 PHẦN 4: STEP-BY-STEP (Hướng dẫn viết từng bước)

### Bước 1: Viết Recording Rules (file recording_rules.yaml)

```
Với MỖI service + MỖI cửa sổ thời gian, viết 1 recording rule theo công thức:

  record: sli:<service>_error:ratio_rate<window>
  expr: |
    sum(rate(traces_span_metrics_calls_total{
      service_name="<service>",
      status_code="STATUS_CODE_ERROR"
    }[<window>]))
    /
    clamp_min(
      sum(rate(traces_span_metrics_calls_total{
        service_name="<service>"
      }[<window>])),
      1e-9
    )

GIẢI THÍCH:
- Tử số: rate lỗi (chỉ đếm span có status_code="STATUS_CODE_ERROR")
- Mẫu số: rate tổng (tất cả span, kể cả OK)
- clamp_min(..., 1e-9): bảo vệ chia cho 0 khi không có traffic
- Kết quả: giá trị từ 0.0 (không lỗi) đến 1.0 (100% lỗi)

Riêng latency p95:
  record: sli:frontend_latency:p95_5m
  expr: |
    histogram_quantile(0.95,
      sum by (le) (rate(
        traces_span_metrics_duration_milliseconds_bucket{service_name="frontend"}[5m]
      ))
    ) / 1000

GIẢI THÍCH:
- histogram_quantile: tính percentile từ histogram buckets
- sum by (le): gộp tất cả span của frontend, giữ lại bucket boundaries
- / 1000: chuyển milliseconds → seconds (để so sánh với SLO < 1s)
```

### Bước 2: Viết Burn-rate Alert Rules (file burnrate_alerts.yaml)

```
Với MỖI service, viết alert theo pattern multi-window:

  - alert: <Service>BurnRate<Severity>
    expr: |
      sli:<service>_error:ratio_rate<long_window> > <threshold>
      and
      sli:<service>_error:ratio_rate<short_window> > <threshold>
    for: <stabilization_period>
    labels:
      severity: <critical|warning>
      service: <service_name>
      sli: <sli_name>
      source_layer: slo-burnrate
    annotations:
      summary: "<Service> burning error budget <burn_rate>x (<windows>)"
      description: "<service> error ratio {{ $value | humanizePercentage }}"
      runbook: "<path_to_runbook>"

GIẢI THÍCH phần "and":
- Cửa sổ dài > threshold AND cửa sổ ngắn > threshold
- Nếu CHỈ cửa sổ ngắn vượt → spike thoáng qua → KHÔNG bắn
- Nếu CHỈ cửa sổ dài vượt → sự cố đã qua → KHÔNG bắn
- CẢ HAI vượt → sự cố đang xảy ra VÀ kéo dài → BẮN ALERT

for: 2m (critical) hoặc 5m (warning):
- Chờ thêm 2-5 phút ổn định trước khi thực sự gửi alert
- Tránh noise từ dao động tức thời
```

### Bước 3: Thêm comment và metadata

```
Mỗi file PHẢI có comment header giải thích:
1. File này thuộc contract nào (C1-telemetry-access, C2-alerting)
2. Metric names đã xác nhận từ đâu (real system, không assume)
3. Công thức tính ngưỡng (không chỉ hardcode số)
4. Tại sao file tồn tại (failsafe: nếu AI engine chết, alerts vẫn chạy)
5. Lưu ý scrape_interval 60s ảnh hưởng thế nào
```

---

## 📌 PHẦN 5: EXAMPLES (Ví dụ output mong đợi)

### Ví dụ Recording Rule hoàn chỉnh:

```yaml
groups:
  - name: techx_sli
    interval: 30s          # evaluation interval riêng, nhanh hơn scrape
    rules:
      # ── checkout success ratio (revenue-critical, SLO ≥ 99%) ──
      # Tính error ratio = errors / total theo 4 cửa sổ
      # Nguồn metric: OTel spanmetrics connector (đã xác nhận trên AWS)
      - record: sli:checkout_error:ratio_rate5m
        expr: |
          sum(rate(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[5m]))
          /
          clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[5m])), 1e-9)
```

### Ví dụ Alert Rule hoàn chỉnh:

```yaml
groups:
  - name: techx_checkout_burnrate
    rules:
      # Google SRE Workbook: 14.4x burn on 1h AND 5m = page NOW
      # Ngưỡng: 14.4 × 0.01 (error budget 99% SLO) = 0.144
      - alert: CheckoutBurnRateCritical
        expr: |
          sli:checkout_error:ratio_rate1h > 0.144
          and
          sli:checkout_error:ratio_rate5m > 0.144
        for: 2m
        labels:
          severity: critical
          service: checkout
          sli: checkout_success_ratio
          source_layer: slo-burnrate
        annotations:
          summary: "Checkout burning error budget 14.4x (1h+5m)"
          description: "checkout error ratio {{ $value | humanizePercentage }} — revenue flow degraded."
          runbook: "TF3/ai-engine/runbooks/RB-PAY-01.md"
```

---

## 📌 PHẦN 6: SENSE CHECK (Kiểm tra chất lượng)

```
Sau khi viết xong, tự kiểm tra bằng checklist:

□ YAML syntax valid (có thể chạy promtool check rules <file>)
□ Tên metric khớp chính xác với hệ thống thực (traces_span_metrics_calls_total)
□ Label status_code="STATUS_CODE_ERROR" — đúng chuẩn OTel, không phải "error" hay "Error"
□ Mỗi rule có comment giải thích rõ ý nghĩa
□ Ngưỡng burn-rate có ghi cách tính (ví dụ: 14.4 × 0.01 = 0.144)
□ Alert dùng "and" để kết hợp 2 cửa sổ (KHÔNG dùng "or")
□ Có for: 2m/5m để ổn định trước khi bắn
□ Labels có severity, service, sli, source_layer
□ Annotations có summary mô tả ngắn
□ clamp_min(denominator, 1e-9) để tránh chia 0
□ Latency chia 1000 (ms → s) trước khi so sánh với SLO
□ Total recording rules = 9 (checkout×4 + frontend×2 + cart×2 + latency×1)
□ Total alert rules = 5 (checkout×2 + browse×1 + cart×1 + latency×1)
```

---

## 📌 PHẦN 7: OUTPUT FORMAT

```
Output phải là 2 file YAML riêng biệt, mỗi file:
1. Bắt đầu bằng block comment giải thích mục đích, nguồn metric, contract
2. Theo format chuẩn Prometheus rule_files
3. Có indentation 2-space
4. Sẵn sàng để CDO copy-paste vào ConfigMap của Prometheus trên EKS

File 1: recording_rules.yaml
  → 1 group "techx_sli", interval 30s, 9 rules

File 2: burnrate_alerts.yaml
  → 3 groups: techx_checkout_burnrate (2 alerts), techx_browse_cart_burnrate (2 alerts), techx_latency (1 alert)
```

---

## 📌 PHẦN 8: ANTI-PATTERNS (TRÁNH LÀM)

```
❌ KHÔNG dùng metric name sai (http_requests_total — đó là metric HTTP, không phải OTel span)
❌ KHÔNG dùng status_code="error" (phải là "STATUS_CODE_ERROR" — chuẩn OTel)
❌ KHÔNG quên clamp_min (chia 0 = NaN = rule câm lặng không bắn alert)
❌ KHÔNG dùng single-window alert (chỉ 1 cửa sổ = quá nhiều false-positive)
❌ KHÔNG dùng "or" thay "and" trong multi-window (or = mất mục đích lọc noise)
❌ KHÔNG set for: 0m hoặc thiếu for (alert bắn lung tung)
❌ KHÔNG hardcode ngưỡng mà không comment cách tính
❌ KHÔNG bỏ sót service nào (phải đủ 3: checkout, frontend, cart)
❌ KHÔNG viết chung 2 loại rules vào 1 file (recording rules ≠ alert rules)
❌ KHÔNG đặt interval > scrape_interval (evaluation phải nhanh hơn hoặc bằng scrape)
```

---

## 📌 PHẦN 9: CONTEXT BỔ SUNG (Tại sao file này quan trọng)

```
Kiến trúc hệ thống giám sát SLO có 2 lớp:

Layer 1: Prometheus Recording Rules + Burn-rate Alerts
  → Chạy TRỰC TIẾP trên Prometheus/Alertmanager
  → Đây là FAILSAFE: nếu AI engine chết, vẫn page được
  → File recording_rules.yaml và burnrate_alerts.yaml thuộc layer này

Layer 2: AI Engine (detector_burnrate.py)
  → Query recording rules từ layer 1
  → Thêm correlation, enrichment, evidence pack
  → Thông minh hơn nhưng có thể chết

→ Không có Layer 1 = KHÔNG CÓ FAILSAFE = MÙ HOÀN TOÀN khi engine down
→ Đây là lý do file recording_rules.yaml PHẢI được deploy lên Prometheus TRƯỚC
```

---

## 📌 PHẦN 10: DEPLOYMENT (Sau khi viết xong)

```
Trách nhiệm:
- AIOps viết file → ĐÃ XONG ✅
- CDO nạp file vào Prometheus ConfigMap → ĐANG CHỜ ⏳

Lệnh CDO cần chạy:
  kubectl edit cm prometheus-server -n techx-tf3
  # Thêm nội dung recording_rules.yaml vào ConfigMap
  # Thêm rule_files path vào prometheus.yml
  # Reload: kubectl exec <pod> -- kill -HUP 1

Xác nhận thành công:
  kubectl exec <pod> -- wget -qO- http://localhost:9090/api/v1/rules
  # Kỳ vọng: groups không rỗng, có 9 recording rules + 5 alert rules

  kubectl exec <pod> -- wget -qO- \
    "http://localhost:9090/api/v1/query?query=sli:checkout_error:ratio_rate5m"
  # Kỳ vọng: result có giá trị số (0 ≤ x ≤ 1)
```
