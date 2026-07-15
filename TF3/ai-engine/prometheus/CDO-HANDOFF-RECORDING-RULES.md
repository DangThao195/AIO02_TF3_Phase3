# 📋 [AIO → CDO] Yêu cầu nạp Recording Rules & Alert Rules vào Prometheus

> **Từ:** AIOps (AIO02)
> **Gửi:** CDO01 / CDO02
> **Ngày:** 2026-07-09
> **Ưu tiên:** 🔴 Cao — chặn toàn bộ luồng SLO alerting (C2)
> **Contract tham chiếu:** C1 (Telemetry Access) §OUTPUT.2, C2 (Alerting)

---

## 1. Tóm tắt yêu cầu

AIOps cần CDO **nạp 2 file cấu hình** vào Prometheus đang chạy trên EKS cluster `techx-corp-tf3` (namespace `techx-tf3`):

| # | File | Loại | Mục đích |
|---|---|---|---|
| 1 | `recording_rules.yaml` | Recording Rules | Tính toán tỷ lệ lỗi (SLI) theo 4 cửa sổ thời gian (5m, 30m, 1h, 6h) cho checkout, frontend, cart |
| 2 | `burnrate_alerts.yaml` | Alert Rules | Cảnh báo khi Error Budget bị cạn kiệt quá nhanh (burn-rate) |

**Đường dẫn file trong repo:**
```
TF3/ai-engine/prometheus/
├── recording_rules.yaml      ← File 1: Recording Rules (9 rules)
├── burnrate_alerts.yaml       ← File 2: Alert Rules (5 alerts)
└── telemetry-dependencies.md  ← Tài liệu tham chiếu metric
```

---

## 2. Hiện trạng (đã xác nhận trên AWS)

| Hạng mục | Trạng thái |
|---|---|
| EKS cluster `techx-corp-tf3` | ✅ Đang chạy |
| Prometheus pod `prometheus-5cb8b68848-nm9lf` | ✅ Đang chạy (namespace `techx-tf3`) |
| Metric thô `traces_span_metrics_calls_total` | ✅ Có data (OTel Collector đang gom) |
| Metric thô `traces_span_metrics_duration_milliseconds_bucket` | ✅ Có data |
| Recording Rules (SLI) | ❌ **Chưa có** — Prometheus trả về `groups: []` |
| Alert Rules (Burn-rate) | ❌ **Chưa có** |

**Bằng chứng:** Query `GET /api/v1/rules` trên Prometheus trả về `{"status":"success","data":{"groups":[]}}`.

---

## 3. Hướng dẫn thực hiện cho CDO

### Bước 1: Xác định ConfigMap của Prometheus

```bash
# Tìm ConfigMap chứa cấu hình Prometheus
kubectl get configmap -n techx-tf3 | grep -i prom
```

Thường tên là `prometheus-config`, `prometheus-server`, hoặc tương tự.

### Bước 2: Xem cấu hình hiện tại

```bash
kubectl get configmap <tên-configmap> -n techx-tf3 -o yaml
```

Tìm phần `rule_files:` trong `prometheus.yml`. Nếu chưa có, cần thêm.

### Bước 3: Thêm nội dung Recording Rules

Có **2 cách** tùy theo cấu trúc ConfigMap hiện tại:

#### Cách A: Thêm trực tiếp vào ConfigMap (inline)

```bash
kubectl edit configmap <tên-configmap> -n techx-tf3
```

Thêm nội dung của `recording_rules.yaml` và `burnrate_alerts.yaml` vào ConfigMap dưới key riêng, ví dụ:

```yaml
data:
  prometheus.yml: |
    # ... cấu hình hiện có ...
    rule_files:
      - /etc/prometheus/recording_rules.yaml
      - /etc/prometheus/burnrate_alerts.yaml

  recording_rules.yaml: |
    groups:
      - name: techx_sli
        interval: 30s
        rules:
          - record: sli:checkout_error:ratio_rate5m
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[5m]))
              /
              clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[5m])), 1e-9)
          - record: sli:checkout_error:ratio_rate30m
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[30m]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[30m])), 1e-9)
          - record: sli:checkout_error:ratio_rate1h
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[1h]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[1h])), 1e-9)
          - record: sli:checkout_error:ratio_rate6h
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[6h]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[6h])), 1e-9)

          - record: sli:frontend_error:ratio_rate5m
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="frontend",status_code="STATUS_CODE_ERROR"}[5m]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="frontend"}[5m])), 1e-9)
          - record: sli:frontend_error:ratio_rate1h
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="frontend",status_code="STATUS_CODE_ERROR"}[1h]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="frontend"}[1h])), 1e-9)

          - record: sli:cart_error:ratio_rate5m
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="cart",status_code="STATUS_CODE_ERROR"}[5m]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="cart"}[5m])), 1e-9)
          - record: sli:cart_error:ratio_rate1h
            expr: |
              sum(rate(traces_span_metrics_calls_total{service_name="cart",status_code="STATUS_CODE_ERROR"}[1h]))
              / clamp_min(sum(rate(traces_span_metrics_calls_total{service_name="cart"}[1h])), 1e-9)

          - record: sli:frontend_latency:p95_5m
            expr: |
              histogram_quantile(0.95,
                sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{service_name="frontend"}[5m]))
              ) / 1000

  burnrate_alerts.yaml: |
    groups:
      - name: techx_checkout_burnrate
        rules:
          - alert: CheckoutBurnRateCritical
            expr: |
              sli:checkout_error:ratio_rate1h > 0.144
              and
              sli:checkout_error:ratio_rate5m > 0.144
            for: 2m
            labels:
              severity: critical
              service: checkout
            annotations:
              summary: "Checkout burning error budget 14.4x (1h+5m)"

          - alert: CheckoutBurnRateWarning
            expr: |
              sli:checkout_error:ratio_rate6h > 0.06
              and
              sli:checkout_error:ratio_rate30m > 0.06
            for: 5m
            labels:
              severity: warning
              service: checkout
            annotations:
              summary: "Checkout burning error budget 6x (6h+30m)"

      - name: techx_browse_cart_burnrate
        rules:
          - alert: BrowseBurnRateCritical
            expr: |
              sli:frontend_error:ratio_rate1h > 0.072
              and
              sli:frontend_error:ratio_rate5m > 0.072
            for: 2m
            labels: { severity: critical, service: frontend }
            annotations:
              summary: "Browse burning error budget 14.4x (1h+5m)"

          - alert: CartBurnRateCritical
            expr: |
              sli:cart_error:ratio_rate1h > 0.072
              and
              sli:cart_error:ratio_rate5m > 0.072
            for: 2m
            labels: { severity: critical, service: cart }
            annotations:
              summary: "Cart burning error budget 14.4x (1h+5m)"

      - name: techx_latency
        rules:
          - alert: StorefrontLatencyP95High
            expr: sli:frontend_latency:p95_5m > 1
            for: 5m
            labels: { severity: warning, service: frontend }
            annotations:
              summary: "Storefront p95 latency > 1s (SLO breach)"
```

#### Cách B: Nếu dùng Helm chart

Nếu Prometheus được deploy bằng Helm (ví dụ: `kube-prometheus-stack`), thêm vào `values.yaml`:

```yaml
additionalPrometheusRulesMap:
  techx-sli-rules:
    groups:
      - name: techx_sli
        # ... copy nội dung recording_rules.yaml ...
      - name: techx_checkout_burnrate
        # ... copy nội dung burnrate_alerts.yaml ...
```

Rồi chạy: `helm upgrade ...`

### Bước 4: Reload Prometheus

Sau khi cập nhật ConfigMap:

```bash
# Cách 1: Gửi SIGHUP để Prometheus reload config (không restart)
kubectl exec prometheus-5cb8b68848-nm9lf -n techx-tf3 -- kill -HUP 1

# Cách 2: Gọi reload endpoint (nếu --web.enable-lifecycle được bật)
kubectl exec prometheus-5cb8b68848-nm9lf -n techx-tf3 -- wget -qO- --post-data '' http://localhost:9090/-/reload

# Cách 3: Restart pod (cuối cùng nếu 2 cách trên không được)
kubectl delete pod prometheus-5cb8b68848-nm9lf -n techx-tf3
```

### Bước 5: Xác nhận đã nạp thành công

```bash
# Kiểm tra rules đã load
kubectl exec prometheus-5cb8b68848-nm9lf -n techx-tf3 -- \
  wget -qO- http://localhost:9090/api/v1/rules

# Kiểm tra SLI có data (chờ ~5 phút sau khi nạp)
kubectl exec prometheus-5cb8b68848-nm9lf -n techx-tf3 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sli:checkout_error:ratio_rate5m"
```

**Kết quả mong đợi:** `result` không rỗng, trả về giá trị số (tỷ lệ lỗi).

---

## 4. ⚠️ Lưu ý quan trọng cho CDO

### 4.1. Vấn đề Scrape Interval

Scrape interval hiện tại là **60s**. Theo guideline Google SRE, cửa sổ ngắn 5m cần **≥10 data points** để ổn định. Với 60s, chỉ có ~5 points.

**Đề xuất:** Giảm scrape interval xuống **30s** cho job `checkout`. Hoặc thông báo cho AIO để mở rộng cửa sổ ngắn lên 10m.

### 4.2. Không đổi tên metric

Các rules phụ thuộc vào:
- `traces_span_metrics_calls_total` — label `service_name`, `status_code`
- `traces_span_metrics_duration_milliseconds_bucket` — label `service_name`, `le`
- `status_code="STATUS_CODE_ERROR"` để đánh dấu lỗi

**Nếu CDO đổi tên hoặc cấu hình lại spanmetrics connector → phải báo AIO trước ≥2 ngày** để cập nhật rules.

### 4.3. Tầm quan trọng

Đây là **lớp dự phòng (failsafe)** — nếu AI engine chết, các alert rules này vẫn chạy trực tiếp trên Prometheus/Alertmanager để page người trực. Không có chúng = **MÙ hoàn toàn** khi engine down.

---

## 5. Checklist xác nhận (CDO điền)

| # | Hạng mục | Trạng thái | Người thực hiện | Ngày |
|---|---|---|---|---|
| 1 | Đã nạp `recording_rules.yaml` vào Prometheus | ☐ | | |
| 2 | Đã nạp `burnrate_alerts.yaml` vào Prometheus | ☐ | | |
| 3 | Prometheus reload thành công (không lỗi config) | ☐ | | |
| 4 | Query `sli:checkout_error:ratio_rate5m` trả về data | ☐ | | |
| 5 | Xác nhận scrape interval (30s hay 60s) | ☐ | | |
| 6 | Thông báo lại AIO khi hoàn tất | ☐ | | |

---

## 6. Liên hệ

Nếu có vấn đề khi nạp rules hoặc cần hỗ trợ debug PromQL:
- **AIO02** — owner file rules, hỗ trợ debug query
- **Tham chiếu:** `TF3/ai-engine/prometheus/telemetry-dependencies.md`
