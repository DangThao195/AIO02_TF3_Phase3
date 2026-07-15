# 🤝 Handoff cho CDO — Nạp SLO Recording Rules + Burn-rate Alerts vào Prometheus

> **Bối cảnh:** AIOps (chúng tôi) đã VIẾT XONG rules (C1 §OUTPUT.2). Hiện `GET /api/v1/rules`
> trả `groups: []` → **rules chưa được CDO nạp vào Prometheus**. File này hướng dẫn CDO nạp.
> **Ranh giới (C1):** AIO viết rule → **CDO review + merge** vào cấu hình Prometheus.

## Việc cần CDO làm (tóm tắt 1 dòng)
Nạp **38 recording rules + 7 alert rules** vào Prometheus trên EKS `techx-corp-tf3` / ns `techx-tf3`,
reload, xác nhận `/api/v1/rules` không còn rỗng.

> **Cập nhật (chuẩn sloth/pyrra — MWMB 4 cặp):** rules đủ **4 cặp burn-rate** cho checkout
> (page nhanh 14.4× / page vừa 6× / ticket vừa 3× / ticket chậm 1×), cần cửa sổ 5m,30m,1h,2h,6h,1d,3d.
> Thêm **latency-ratio SLI** (% <1s), **error-budget-remaining** (freeze policy). 5 group:
> `techx_sli` + `techx_slo` (recording) + 3 group alert.
> **PHỤ THUỘC:**
> - Latency-ratio cần histogram bucket **`le="1000"`** (ms). Thiếu → báo AIO.
> - Cửa sổ **1d/3d** chỉ có data khi Prometheus chạy đủ 1-3 ngày → **retention ≥ 3 ngày** (C1).
>   Cặp 3-4 (ticket) sẽ rỗng cho tới khi tích đủ lịch sử — bình thường, không phải lỗi.

---

## Bước 0 — Xác định Prometheus deploy kiểu nào (QUAN TRỌNG, quyết định cách nạp)

```sh
# Có Prometheus Operator (kube-prometheus-stack)?
kubectl get prometheus -A 2>/dev/null
kubectl get crd prometheusrules.monitoring.coreos.com 2>/dev/null
```

- **CÓ output** → dùng **CÁCH A (PrometheusRule CRD)** — sạch nhất, không sửa ConfigMap tay.
- **KHÔNG có CRD** (Prometheus thuần, ConfigMap-based) → dùng **CÁCH B (ConfigMap)**.

---

## CÁCH A — kube-prometheus-stack (khuyến nghị, nếu có CRD)

Operator tự nạp `PrometheusRule` qua label selector. **Không cần sửa ConfigMap, không reload tay.**

```sh
# 1. Kiểm tra Prometheus lọc rule theo label nào:
kubectl get prometheus -n techx-tf3 -o jsonpath='{.items[0].spec.ruleSelector}'; echo
#    ví dụ trả: {"matchLabels":{"release":"prometheus"}}

# 2. Sửa label `release:` trong file CRD cho KHỚP (mặc định để "prometheus"):
#    File: prometheusrule-techx-slo.yaml  →  metadata.labels.release: <đúng-tên>

# 3. Apply:
kubectl apply -f prometheusrule-techx-slo.yaml

# 4. Operator nạp trong ~30s. Xác nhận CRD đã vào:
kubectl get prometheusrule techx-slo-rules -n techx-tf3
```

---

## CÁCH B — Prometheus thuần (ConfigMap-based)

```sh
# 1. Lấy tên ConfigMap chứa config (thường prometheus-server hoặc prometheus-config):
kubectl get cm -n techx-tf3 | grep -i prometheus

# 2. Copy 2 file rule vào 1 ConfigMap rule riêng (đừng nhét vào file config chính):
kubectl create configmap techx-slo-rules -n techx-tf3 \
  --from-file=recording_rules.yaml \
  --from-file=burnrate_alerts.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Mount ConfigMap vào pod Prometheus (nếu chưa) + thêm vào prometheus.yml:
#      rule_files:
#        - /etc/prometheus/rules/*.yaml
#    (sửa Deployment/ConfigMap tuỳ chart — đây là phần CDO nắm rõ hạ tầng)

# 4. Reload Prometheus (không cần restart):
POD=$(kubectl get pod -n techx-tf3 -l app.kubernetes.io/name=prometheus -o name | head -1)
kubectl exec -n techx-tf3 $POD -- kill -HUP 1
#    hoặc nếu bật web.enable-lifecycle:
#    kubectl exec -n techx-tf3 $POD -- wget -qO- --post-data='' http://localhost:9090/-/reload
```

---

## Bước cuối — VERIFY (cả 2 cách đều chạy)

```sh
POD=$(kubectl get pod -n techx-tf3 -l app.kubernetes.io/name=prometheus -o name | head -1)

# 1. Rules đã nạp? (kỳ vọng: groups KHÔNG rỗng, có techx_sli + burnrate groups)
kubectl exec -n techx-tf3 $POD -- wget -qO- http://localhost:9090/api/v1/rules \
  | grep -o '"name":"[^"]*"' | head

# 2. Recording rule ra số? (kỳ vọng: value 0.0–1.0)
kubectl exec -n techx-tf3 $POD -- wget -qO- \
  "http://localhost:9090/api/v1/query?query=sli:checkout_error:ratio_rate5m"

# 3. Alert rule đã load? (kỳ vọng: thấy CheckoutBurnRateCritical, state inactive khi khoẻ)
kubectl exec -n techx-tf3 $POD -- wget -qO- http://localhost:9090/api/v1/alerts
```

**Definition of Done (C1):**
- [ ] `/api/v1/rules` có **18 recording + 5 alert rules** (2 group `techx_sli` + `techx_slo`).
- [ ] `sli:checkout_error:ratio_rate5m` query ra giá trị số.
- [ ] `slo:checkout:error_budget_remaining` query ra số (≈1.0 khi khoẻ) — cho freeze policy.
- [ ] `sli:frontend_latency:ratio_under1s_5m` ra số **> 0** → xác nhận bucket `le="1000"` tồn tại.
      Nếu = 0 hoặc rỗng dù có traffic → thiếu bucket đó, báo AIO đổi boundary.
- [ ] Grafana SLO dashboard (uid `slo-checkout`) hiển thị được (import [../grafana/slo-checkout-dashboard.json]).
- [ ] ADR ký tên xác nhận CDO đã merge (C1 khởi tạo).

---

## Lưu ý (AIO ↔ CDO)
- **Scrape 60s** (đã xác nhận): cửa sổ 5m chỉ có ~5 điểm — sát ngưỡng burn-rate ổn định.
  Đề xuất CDO **giảm scrape checkout xuống 30s** HOẶC AIO nới short-window lên 10m. Chốt bằng ADR.
- **Đừng rename** `traces_span_metrics_*` hay label `status_code` — rule sẽ chết im lặng.
  Trước khi refactor observability, check [telemetry-dependencies.md].
- File nguồn: recording_rules.yaml + burnrate_alerts.yaml (đọc được, có comment giải thích).
- Bản gộp sẵn để apply nhanh (Cách A): **prometheusrule-techx-slo.yaml**.
