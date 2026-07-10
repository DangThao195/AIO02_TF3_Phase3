# Telemetry Dependencies — metrics the AI engine consumes (verified against real system)

> Implements contracts/C1-telemetry-access.md §OUTPUT.1. **CDO: check this before refactoring
> observability.** Rename/drop any row here → the matching detector/alert breaks silently.
> AIO updates this whenever a rule is added. Metric names below were verified from the running
> OTel Demo (grafana dashboards + prometheus config), not assumed.
>
> **✅ Xác minh trên stack LOCAL đang chạy (docker-compose, 2026-07-09):**
> - Engine đọc `http://prometheus:9090` read-only OK.
> - `traces_span_metrics_calls_total` có label `service_name` + `status_code` — **xác nhận
>   giá trị `status_code`: `STATUS_CODE_UNSET` (span OK) / `STATUS_CODE_ERROR` (span lỗi)** —
>   khớp đúng recording_rules.yaml. Không phải "error"/"OK".
> - ⚠️ Seed image `nghiadaulau/techx-corp:1.0-*` build cho **ARM64**; trên máy AMD64 nhiều
>   app service báo `exec format error` (load-generator, ...). Trên EKS thật (node arch phù hợp)
>   không gặp — nhưng nếu CDO chạy node ARM/AMD lẫn lộn, cần build multi-arch (đã ghi ADR).

## Metrics consumed

| Source | Metric / rule | Required labels | Used by |
|---|---|---|---|
| Prometheus | `traces_span_metrics_calls_total` | `service_name`, `status_code` | Burn-rate SLI (C2 layer 1) — recording_rules.yaml |
| Prometheus | `traces_span_metrics_duration_milliseconds_bucket` | `service_name`, `le` (**cần có `le="1000"`**) | p95 latency (dashboard) + latency-ratio SLI (% <1s) |
| Prometheus | `traces_span_metrics_duration_milliseconds_count` | `service_name` | mẫu số cho latency-ratio SLI |
| Prometheus | recording rules `sli:*_error:ratio_rate{5m,30m,1h,6h,3d}` | — | burnrate_alerts.yaml + detector_burnrate.py |
| Prometheus | `ai_gateway_*`, `ai_cost_*`, `ai_guardrail_*`, `ai_breaker_state` (AIO emits) | `outcome`,`model`,`feature`,`reason` | C4/C5 dashboards |
| Prometheus | kafka consumer lag, `*_memory_*`, container CPU (Phase 3 anomaly) | `service_name`/`pod` | ML anomaly (C2 layer 2) |
| OpenSearch | product log indices (pattern TBD after deploy) | `service`, `level`, `@timestamp` | Log mining, Evidence Pack (C3) |
| OpenSearch | `ai-engine-*`, `ai-engine-audit-*` (AIO writes) | — | Engine log + audit (C6) |
| Jaeger | trace query by `service` + `error=true` | — | Exemplar traces (C3) |

## ⚠ Open items for CDO (raise at standup, resolve with ADR)

1. **Scrape interval is 60s** (`prometheus-config.yaml`), but C1 assumes ≤30s. A 5m short
   window then holds only ~5 samples — at the edge of the "≥10 points" guideline for stable
   burn-rate alerting. **Options:** (a) CDO drops scrape to 30s for the checkout job, or
   (b) AIO widens the short window to 10m. Recommend (a) for checkout only (cheap, precise).
2. **`status_code` value**: error spans use `status_code="STATUS_CODE_ERROR"`. If CDO changes
   the spanmetrics connector config, the `sli:*_error` rules must be updated in lockstep.
3. **OpenSearch index pattern** and **latency histogram exact name** get filled in once the
   stack is deployed and AIO scans the live `/api/v1/label/__name__/values`.

## Absent-check (C1 failure mode: silent-failure guard)

The engine runs an hourly `absent()` check on the critical metrics above; if any goes missing
it flips `ai_engine_blind` and emits a warning meta-alert (not silence). PromQL:

```promql
absent(traces_span_metrics_calls_total{service_name="checkout"})
```
