# Dashboard Plan — Shopping Copilot AI Observability
## TechX TF3 · AIO02 · Ngày: 2026-07-10

> **Mục đích:** Định nghĩa các panel và metric cần thiết cho AWS/Grafana dashboard
> để quan sát hệ thống AI Shopping Copilot trong vận hành thật.
> Stack: OpenTelemetry → Prometheus (metrics) + OpenSearch (logs) + Jaeger (traces) → Grafana.
> Datasource mặc định: `webstore-metrics` (Prometheus `http://prometheus:9090`).

---

## 1. Tổng quan — 4 dashboard, 1 mục đích mỗi cái

| Dashboard | Đối tượng xem | Câu hỏi nó trả lời |
|---|---|---|
| **1. AI Health Overview** | Ops / on-call | Hệ thống AI có đang khỏe không? Có cần wake-up không? |
| **2. Copilot Quality** | AIE team | Agent có đang làm đúng việc không? Task success, hallucination? |
| **3. Guardrail & Safety** | Security / AIE | Có cuộc tấn công nào không? Bao nhiêu bị chặn? False positive? |
| **4. Cost & Performance** | Tech lead / BM | Tiêu bao nhiêu token? Latency có đạt SLO không? Cache có hiệu quả? |

Tất cả đều dùng **time range: last 24h, refresh 1m** làm default.


---

## 2. Dashboard 1 — AI Health Overview

**Mục đích:** Nhìn một cái biết ngay hệ thống AI sống hay chết. On-call dùng cái này.

### Row 1 — Status Bar (top of dashboard)

| Panel | Loại | Metric / Query | Ngưỡng màu |
|---|---|---|---|
| **Agent Status** | Stat | `up{job="shopping-copilot"}` | 🟢 1 = UP / 🔴 0 = DOWN |
| **Error Rate (5m)** | Stat | `rate(copilot_requests_total{status="error"}[5m]) / rate(copilot_requests_total[5m]) * 100` | 🟢 <2% / 🟡 2-5% / 🔴 >5% |
| **P95 Latency** | Stat | `histogram_quantile(0.95, rate(copilot_e2e_latency_ms_bucket[5m]))` | 🟢 <3s / 🟡 3-5s / 🔴 >5s |
| **Active Sessions (1m)** | Stat | `copilot_active_sessions` | Không ngưỡng — informational |
| **Guardrail Block Rate (1h)** | Stat | `rate(guardrail_blocked_total[1h]) / rate(copilot_requests_total[1h]) * 100` | 🟡 nếu spike >20% |

### Row 2 — Request Volume & Error Timeline

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Requests/min** | Time series | `rate(copilot_requests_total[1m]) * 60` | Phân loại theo `status` (ok/error/pending) |
| **Error Rate %** | Time series | `rate(copilot_requests_total{status="error"}[5m]) / rate(copilot_requests_total[5m]) * 100` | Alert line tại 5% |
| **LLM Fallback Events** | Time series | `rate(copilot_fallback_total[5m])` | Đếm lần L6 Fallback Handler kích hoạt |

### Row 3 — Downstream Service Health

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **gRPC Error Rate per Tool** | Bar gauge | `rate(copilot_tool_errors_total[5m])` by `tool_name` | Biết tool nào đang fail |
| **gRPC Latency per Tool** | Heatmap | `histogram_quantile(0.95, rate(copilot_tool_latency_ms_bucket[5m]))` by `tool_name` | |
| **LLM API Errors** | Time series | `rate(copilot_llm_errors_total[5m])` by `error_type` | Timeout / rate-limit / connection |

### Annotations

- **Deployments:** tag từ CI/CD → vertical line trên timeline
- **Incidents:** manual annotation khi có sự cố


---

## 3. Dashboard 2 — Copilot Quality

**Mục đích:** Đo chất lượng AI agent theo chiều A + C của baseline_evaluation.md.
Dữ liệu từ eval script (batch, không real-time) + runtime logs.

### Row 1 — Task Success

| Panel | Loại | Datasource | Query / Nguồn | Ghi chú |
|---|---|---|---|---|
| **Overall Task Success Rate** | Gauge | Prometheus | `copilot_task_success_rate` | 🟢 >80% / 🟡 60-80% / 🔴 <60% |
| **TSR per Intent** | Bar chart | Prometheus | `copilot_task_success_rate` by `intent` | 6 bars: search_nl, rag_qa, cart, compare, cross_sell, currency_ship |
| **TSR Trend (7 days)** | Time series | Prometheus | `copilot_task_success_rate` over time | Phát hiện regression sau deploy |

### Row 2 — Grounding & Hallucination

| Panel | Loại | Query | Ngưỡng màu |
|---|---|---|---|
| **Hallucination Rate** | Stat | `copilot_hallucination_rate` | 🟢 0% / 🟡 >0% / 🔴 >5% |
| **Grounding Score** | Gauge | `100 - copilot_hallucination_rate` | 🟢 >95% |
| **"No Info" Correct Rate** | Stat | `copilot_no_info_correct_rate` | 🟢 >90% |
| **PII Leakage Events** | Stat | `increase(copilot_pii_leakage_total[24h])` | 🟢 0 / 🔴 >0 |

### Row 3 — Multi-turn & Agent Behavior

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Multi-turn Retention Rate** | Stat | `copilot_multiturn_retention_rate` | Phần trăm context giữ đúng |
| **Avg Tool Calls / Request** | Time series | `rate(copilot_tool_calls_total[5m]) / rate(copilot_requests_total[5m])` | Cao → LLM đang confused / loop |
| **Max Iterations Hit Rate** | Stat | `rate(copilot_max_iterations_total[1h]) / rate(copilot_requests_total[1h]) * 100` | Tỉ lệ request bị L6 cắt vòng lặp |
| **Tool Selection Distribution** | Pie chart | `increase(copilot_tool_calls_total[24h])` by `tool_name` | Biết tool nào được gọi nhiều nhất |

### Row 4 — Cache Effectiveness

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Cache Hit Rate** | Gauge | `copilot_cache_hit_rate` | 🟢 >60% / 🟡 30-60% / 🔴 <30% |
| **Cache Hit vs Miss** | Time series | `rate(copilot_cache_hits_total[5m])` vs `rate(copilot_cache_misses_total[5m])` | |
| **Cache Size** | Stat | `copilot_cache_entries_total` | Alert nếu gần 500 (LRU eviction nhiều) |


---

## 4. Dashboard 3 — Guardrail & Safety

**Mục đích:** Visibility toàn bộ 6 lớp bảo vệ. Phát hiện tấn công và false positive.

### Row 1 — Security Summary (single glance)

| Panel | Loại | Query | Ngưỡng |
|---|---|---|---|
| **Total Blocks (24h)** | Stat | `increase(guardrail_blocked_total[24h])` | Informational |
| **Attack Block Rate** | Gauge | `rate(guardrail_blocked_total{is_attack="true"}[1h]) / rate(guardrail_requests_total[1h]) * 100` | 🟡 nếu giảm đột ngột (bypass mới) |
| **False Positive Rate** | Stat | `rate(guardrail_blocked_total{is_attack="false"}[1h]) / rate(copilot_requests_total[1h]) * 100` | 🟡 >2% / 🔴 >5% |
| **DENIED Actions (24h)** | Stat | `increase(guardrail_blocked_total{layer="L4",reason="DENIED"}[24h])` | Ai đang cố PlaceOrder/EmptyCart? |

### Row 2 — Blocks per Layer (breakdown)

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Block Volume per Layer** | Bar chart | `increase(guardrail_blocked_total[24h])` by `layer` | L1, L2_regex, L2_bedrock, L3, L4 |
| **Block Rate Timeline** | Time series | `rate(guardrail_blocked_total[5m])` by `layer` | Phát hiện spike bất thường |
| **Attack Types Distribution** | Pie chart | `increase(guardrail_blocked_total[24h])` by `reason` | SYSTEM_OVERRIDE, JAILBREAK, PII_EXTRACTION... |

### Row 3 — Layer Detail

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **L1: Rate Limit Hits** | Time series | `rate(guardrail_blocked_total{layer="L1"}[5m])` by `user_id` | Top 5 user bị rate-limit nhiều nhất |
| **L2 Regex: Block by Category** | Bar | `increase(guardrail_blocked_total{layer="L2_regex"}[24h])` by `reason` | 7 category |
| **L2 Bedrock: Block Count** | Stat | `increase(guardrail_blocked_total{layer="L2_bedrock"}[24h])` | Tấn công semantic vượt qua Regex |
| **L3: Tool Violation Types** | Bar | `increase(guardrail_blocked_total{layer="L3"}[24h])` by `reason` | UNKNOWN_TOOL / CROSS_USER / PARAM_INVALID |
| **L4: Confirmation Gate** | Table | `increase(guardrail_blocked_total{layer="L4"}[24h])` by `reason` | DENIED vs PENDING count |

### Row 4 — Token Security

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Invalid Token Attempts** | Time series | `rate(copilot_token_invalid_total[5m])` | Tấn công replay / giả mạo token |
| **Expired Token Attempts** | Stat (24h) | `increase(copilot_token_expired_total[24h])` | User chậm confirm hoặc replay cũ |
| **PII Redacted Events** | Time series | `rate(copilot_pii_redacted_total[5m])` by `pii_type` | EMAIL / PHONE / CC / API_KEY... |

### Row 5 — Logs (OpenSearch)

| Panel | Loại | Datasource | Filter |
|---|---|---|---|
| **Recent Blocked Requests** | Logs | OpenSearch | `level:WARNING AND logger:guardrails` |
| **DENIED Action Log** | Logs | OpenSearch | `logger:guardrails.confirmation AND status:DENIED` |
| **PII Redaction Log** | Logs | OpenSearch | `logger:guardrails.output_filter` |


---

## 5. Dashboard 4 — Cost & Performance

**Mục đích:** Kiểm soát chi phí LLM, đảm bảo latency không phá SLO, tối ưu cache.

### Row 1 — Latency SLO

SLO liên quan từ `SLO.md`: storefront p95 < 1s. Copilot là feature bổ sung —
target nội bộ đặt **p95 < 5s** (agent cần gọi tool, LLM inference).

| Panel | Loại | Query | Ngưỡng |
|---|---|---|---|
| **P50 E2E Latency** | Stat | `histogram_quantile(0.50, rate(copilot_e2e_latency_ms_bucket[5m]))` | 🟢 <1500ms |
| **P95 E2E Latency** | Gauge | `histogram_quantile(0.95, rate(copilot_e2e_latency_ms_bucket[5m]))` | 🟢 <5000ms / 🟡 5-8s / 🔴 >8s |
| **P99 E2E Latency** | Stat | `histogram_quantile(0.99, rate(copilot_e2e_latency_ms_bucket[5m]))` | Baseline chỉ ghi nhận |
| **Latency Heatmap** | Heatmap | `rate(copilot_e2e_latency_ms_bucket[5m])` | Phân phối latency theo thời gian |

### Row 2 — Latency Breakdown

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **LLM Latency (TTFT)** | Time series | `histogram_quantile(0.95, rate(copilot_llm_latency_ms_bucket[5m]))` | Groq API |
| **gRPC Tool Latency** | Time series | `histogram_quantile(0.95, rate(copilot_tool_latency_ms_bucket[5m]))` by `tool_name` | EKS round-trip |
| **Input Filter Latency** | Stat | `histogram_quantile(0.95, rate(copilot_input_filter_ms_bucket[5m]))` | Target: <5ms |
| **Cache Path vs Full Path** | Time series | Latency khi `cache_hit=true` vs `cache_hit=false` | Minh họa giá trị cache |

### Row 3 — Token & Cost

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Avg Tokens / Request** | Stat | `rate(copilot_tokens_total[5m]) / rate(copilot_requests_total[5m])` | Prompt + completion |
| **Total Tokens (24h)** | Stat | `increase(copilot_tokens_total[24h])` | Budget tracking |
| **Tokens Trend** | Time series | `rate(copilot_tokens_total[5m])` by `token_type` (prompt/completion) | Phát hiện prompt bloat |
| **Est. Cost Today (USD)** | Stat | `increase(copilot_tokens_total[24h]) * 0.0000003` | Dựa trên Groq price ~$0.30/1M tokens |
| **Daily Token Budget** | Bar gauge | `increase(copilot_tokens_per_user[24h])` top 10 | User nào tiêu nhiều nhất |

> **Groq pricing tham khảo (2026-07):** qwen/qwen3.6-27b ≈ $0.29/1M input tokens, $0.69/1M output tokens.
> Cập nhật constant trong query khi giá thay đổi.

### Row 4 — Rate Limiter & Budget

| Panel | Loại | Query | Ghi chú |
|---|---|---|---|
| **Users Hit Daily Token Limit** | Stat (24h) | `increase(guardrail_blocked_total{layer="L1",reason="TOKEN_BUDGET"}[24h])` | Cần nâng limit? |
| **Users Hit Minute Rate Limit** | Time series | `rate(guardrail_blocked_total{layer="L1",reason="RATE_MINUTE"}[5m])` | Spike → bot activity |
| **Token Usage Distribution** | Histogram | `copilot_tokens_per_user` buckets | Phần lớn dùng bao nhiêu? |


---

## 6. Metric Instrumentation — Cần emit từ code

Tất cả metric dưới đây phải được emit từ `shopping-copilot` qua OTel SDK
(`opentelemetry-api`) → collector → Prometheus.

### 6.1 Counter (tăng dần, không giảm)

```python
# Cài thêm: opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp
from opentelemetry import metrics

meter = metrics.get_meter("shopping-copilot")

# Request counters
requests_counter       = meter.create_counter("copilot_requests_total",         description="Total agent requests by status")
tool_calls_counter     = meter.create_counter("copilot_tool_calls_total",        description="Tool calls by tool_name")
tool_errors_counter    = meter.create_counter("copilot_tool_errors_total",       description="Tool errors by tool_name")
llm_errors_counter     = meter.create_counter("copilot_llm_errors_total",        description="LLM errors by error_type")
fallback_counter       = meter.create_counter("copilot_fallback_total",          description="L6 Fallback activations")
max_iter_counter       = meter.create_counter("copilot_max_iterations_total",    description="Max iterations exceeded")

# Token tracking
tokens_counter         = meter.create_counter("copilot_tokens_total",            description="LLM tokens by token_type")
tokens_per_user        = meter.create_counter("copilot_tokens_per_user",         description="Tokens per user_id")

# Cache
cache_hits_counter     = meter.create_counter("copilot_cache_hits_total")
cache_misses_counter   = meter.create_counter("copilot_cache_misses_total")

# Guardrail
blocked_counter        = meter.create_counter("guardrail_blocked_total",         description="Blocked requests by layer and reason")
pii_redacted_counter   = meter.create_counter("copilot_pii_redacted_total",      description="PII redacted by pii_type")
token_invalid_counter  = meter.create_counter("copilot_token_invalid_total")
token_expired_counter  = meter.create_counter("copilot_token_expired_total")
pii_leakage_counter    = meter.create_counter("copilot_pii_leakage_total")       # PII KHÔNG bị catch
```

### 6.2 Histogram (phân phối latency)

```python
e2e_latency_hist       = meter.create_histogram("copilot_e2e_latency_ms",        unit="ms")
llm_latency_hist       = meter.create_histogram("copilot_llm_latency_ms",        unit="ms")
tool_latency_hist      = meter.create_histogram("copilot_tool_latency_ms",       unit="ms")
input_filter_hist      = meter.create_histogram("copilot_input_filter_ms",       unit="ms")
```

### 6.3 Gauge (giá trị hiện tại)

```python
active_sessions_gauge  = meter.create_observable_gauge("copilot_active_sessions", callbacks=[get_active_sessions])
cache_entries_gauge    = meter.create_observable_gauge("copilot_cache_entries_total", callbacks=[get_cache_size])
```

### 6.4 Gauge từ eval script (batch, không real-time)

Emit sau mỗi lần chạy eval (có thể dùng `pushgateway` hoặc log JSON → OTel collector):

```python
# Emit sau eval_task_success.py, eval_grounding.py
task_success_gauge     = meter.create_observable_gauge("copilot_task_success_rate")       # by intent
hallucination_gauge    = meter.create_observable_gauge("copilot_hallucination_rate")
grounding_gauge        = meter.create_observable_gauge("copilot_grounding_score")
no_info_gauge          = meter.create_observable_gauge("copilot_no_info_correct_rate")
multiturn_gauge        = meter.create_observable_gauge("copilot_multiturn_retention_rate")
```

### 6.5 Labels chuẩn cho mỗi metric

```python
# Attributes mẫu khi record
requests_counter.add(1, attributes={
    "status": "ok",          # ok | error | pending
    "intent": "search_nl",   # 6 intent types
    "user_id": user_id,      # cho rate limit tracking
})

blocked_counter.add(1, attributes={
    "layer": "L2_regex",     # L1 | L2_regex | L2_bedrock | L3 | L4
    "reason": "JAILBREAK",   # SYSTEM_OVERRIDE | JAILBREAK | ...
    "is_attack": "true",     # true = attack case, false = legitimate bị chặn nhầm
})

tool_latency_hist.record(latency_ms, attributes={
    "tool_name": "search_products_tool",
    "cache_hit": "false",
})
```


---

## 7. Alert Rules

Định nghĩa alert trong Grafana Alerting (hoặc Prometheus Alertmanager), gắn vào các panel ở trên.

| Alert Name | Condition | Severity | Hành động |
|---|---|---|---|
| `CopilotDown` | `up{job="shopping-copilot"} == 0` for 2m | 🔴 Critical | Page on-call |
| `CopilotHighErrorRate` | Error rate > 10% for 5m | 🔴 Critical | Page on-call |
| `CopilotHighLatencyP95` | P95 > 8000ms for 5m | 🟡 Warning | Notify team |
| `CopilotGuardrailBypass` | L2 block rate drops >50% vs 1h avg | 🔴 Critical | Investigate ngay |
| `CopilotHighFalsePositive` | FPR > 5% for 15m | 🟡 Warning | Review patterns |
| `CopilotHallucination` | `copilot_hallucination_rate > 0` | 🟡 Warning | Manual review |
| `CopilotPIILeakage` | `increase(copilot_pii_leakage_total[5m]) > 0` | 🔴 Critical | Immediate review |
| `CopilotTokenBudgetBurn` | Daily tokens > 80% of target | 🟡 Warning | Cost review |
| `CopilotMaxIterationsHigh` | Max iterations rate > 5% for 10m | 🟡 Warning | LLM loop issue |
| `CopilotCacheHitLow` | Cache hit rate < 30% for 30m | ⚪ Info | Performance review |

---

## 8. Cách triển khai dashboard

### 8.1 Grafana Provisioning (khuyến nghị)

Tạo file JSON cho mỗi dashboard, đặt vào:
```
techx-corp-chart/grafana/provisioning/dashboards/
  ├── copilot-ai-health.json
  ├── copilot-quality.json
  ├── copilot-guardrail.json
  └── copilot-cost-perf.json
```

Dashboard được load tự động khi Grafana pod khởi động — không cần import tay.

### 8.2 Thứ tự triển khai

```
Bước 1: Thêm OTel instrumentation vào copilot_agent.py và guardrails/*.py
         → emit Counter + Histogram khi chạy

Bước 2: Verify metric xuất hiện trong Prometheus
         curl http://localhost:9090/api/v1/label/__name__/values | grep copilot

Bước 3: Build Dashboard 1 (AI Health) trước — dùng để verify Bước 1

Bước 4: Build Dashboard 3 (Guardrail) — metric guardrail đã có sẵn từ logger

Bước 5: Build Dashboard 4 (Cost & Perf) — cần histogram latency

Bước 6: Sau khi có eval script chạy được, build Dashboard 2 (Quality)
         — metric quality từ eval batch, không real-time
```

### 8.3 Datasource mapping

| Datasource | UID trong Grafana | Dùng cho |
|---|---|---|
| Prometheus | `webstore-metrics` | Tất cả Counter, Histogram, Gauge real-time |
| OpenSearch | `opensearch` | Logs panel (raw log search) |
| Jaeger | `webstore-traces` | Trace links từ exemplar |

---

## 9. Metric → Dashboard Mapping (tóm tắt)

| Metric | Dashboard 1 | Dashboard 2 | Dashboard 3 | Dashboard 4 |
|---|:---:|:---:|:---:|:---:|
| `copilot_requests_total` | ✅ | | | ✅ |
| `copilot_e2e_latency_ms` | ✅ | | | ✅ |
| `copilot_fallback_total` | ✅ | | | |
| `copilot_task_success_rate` | | ✅ | | |
| `copilot_hallucination_rate` | | ✅ | | |
| `copilot_pii_leakage_total` | | ✅ | ✅ | |
| `copilot_cache_hit/miss` | | ✅ | | ✅ |
| `copilot_tool_calls_total` | ✅ | ✅ | | |
| `copilot_tool_latency_ms` | ✅ | | | ✅ |
| `copilot_llm_latency_ms` | ✅ | | | ✅ |
| `guardrail_blocked_total` | ✅ | | ✅ | |
| `copilot_pii_redacted_total` | | | ✅ | |
| `copilot_token_invalid_total` | | | ✅ | |
| `copilot_tokens_total` | | | | ✅ |
| `copilot_max_iterations_total` | | ✅ | | |

---

*Metric chưa có giá trị thực → điền sau lần chạy baseline đầu tiên (`baseline_evaluation.md`).*
*Dashboard JSON file sẽ được thêm vào `techx-corp-chart/grafana/provisioning/dashboards/` sau khi instrumentation xong.*
