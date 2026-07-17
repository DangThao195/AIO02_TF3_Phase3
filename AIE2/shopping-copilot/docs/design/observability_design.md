# Observability Metrics

> **Phase 3 — Integration & Production** | *File: `reports/`, FastAPI middleware*

## Metrics & Targets

| Metric | Target | Source | Priority |
|---|---|---|---|
| Cache Hit Rate (Product) | > 80% | Redis INFO / cache stats | P0 |
| Cache Hit Rate (Search) | > 60% | Redis INFO / cache stats | P0 |
| Planner Cache Hit Rate | > 50% | Redis INFO / cache stats | P0 |
| Average Tool Calls / Request | < 4 | `node_durations` | P1 |
| Average DAG Depth | < 4 | `plan.nodes` → max chain | P1 |
| Reflection Rate | < 10% requests | `reflection_result == "replan"` | P1 |
| Replan Success Rate | > 90% | Replan → tool_result OK | P1 |
| Tool Timeout Rate | < 1% | `errors` với source timeout | P1 |
| LLM Timeout Rate | < 0.5% | LLM client metric | P1 |
| P95 End-to-End Latency | < 5s | FastAPI middleware | P0 |
| Redis Memory Usage | < 80% capacity | Redis INFO memory | P1 |
| Rate Limit Hit Rate | monitor | `rate_limiter.stats()` | P2 |
| HallucinationGuard Trigger Rate | monitor | `hallucination_detected` | P2 |
| Semantic Gate Trigger Rate | monitor | `gate_decisions` | P2 |
| Gate False Positive Rate | < 5% | Sample review from `reason` log | P2 |

## Instrumentation Points

### 1. FastAPI Middleware (End-to-End)
```python
@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    latency = (time.time() - start) * 1000
    # record: endpoint, status_code, latency
    # track P50/P95/P99 per endpoint
    return response
```

### 2. Cache Metrics (Redis Store)
```python
class CacheMetrics:
    hits: Counter
    misses: Counter
    size: Gauge    # len(keys) per DB
    memory_usage: Gauge  # INFO memory
```

### 3. Graph Node Metrics
Mỗi node ghi vào `state.node_durations`:
```python
# Tự động từ LangGraph
node_durations: {"intent_parser": 12, "task_graph_builder": 345, ...}
```

### 4. LLM Client Metrics
```python
class LLMMetrics:
    call_count: Counter
    token_usage: Counter     # input + output
    latency: Histogram
    timeout_count: Counter
```

### 5. Guardrail Metrics
```python
# L1 – Rate Limiter
rate_limit_hits: Counter      # per user
rate_limit_blocked: Counter   # per reason

# L3 – Tool Validator
tool_validation_passed: Counter
tool_validation_blocked: Counter

# L4 – Confirmation
confirm_pending: Counter
confirm_approved: Counter
confirm_denied: Counter
confirm_expired: Counter

# HallucinationGuard
hallucination_passed: Counter
hallucination_failed: Counter
fallback_used: Counter

# Gate Layer (Nova Lite)
gate_calls: Counter       # per gate name
gate_decisions: Counter   # YES vs NO per gate
gate_timeouts: Counter
```

## Logging Format

```json
{
  "timestamp": "2026-07-17T10:30:00Z",
  "trace_id": "uuid",
  "session_id": "550e8400-...",
  "user_id": "user_abc",
  "node": "task_graph_builder",
  "duration_ms": 345,
  "tokens": {"input": 450, "output": 120},
  "status": "ok" | "error" | "timeout",
  "error": "optional error detail"
}
```

## Dashboard (gợi ý)

| Panel | Metric | Type |
|---|---|---|
| Request Rate | Requests/sec | Time series |
| Latency P50/P95/P99 | End-to-end latency | Heatmap / quantile |
| Cache Hit Rate | Per cache type | Time series |
| Tool Call Distribution | Per tool | Pie chart |
| Gate Decisions | YES vs NO per gate | Stacked bar |
| Hallucination Rate | Pass vs Fail | Time series |
| Error Rate | Per node/tool | Time series |
| Resource Usage | Redis memory, LLM tokens | Gauge |

## Implementation Notes

- **Phase 3**: Dùng logging + `state.node_durations` + FastAPI middleware
- **Phase 4**: Export OpenTelemetry metrics → Prometheus → Grafana
- Cache stats từ `RedisCacheStore.stats()` method
- Cost tracking: multiply token count × model pricing
