# TechX AI Engine (TF3 / AIO02)

AIOps (detection · RCA · remediation) + AIE (gateway · guardrail · cost) for the TechX Corp
platform. Python 3.11+. Deploys as its own `ai-engine` namespace; reads telemetry **read-only**.

> Full design & 3-week roadmap: **[PLAN.md](PLAN.md)** · Contracts: **[../contracts/](../contracts/)**

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Scaffold: config, telemetry clients, schemas (C2/C6), metrics | ✅ done |
| 1 | **AIE core**: gateway (429/breaker/cache/fallback), guardrail, cost meter | ✅ done, 9/9 tests pass |
| 2 | AIOps: burn-rate detector, C2 alert emitter, dashboards | ⏳ next |
| 3 | ML anomaly, RCA Evidence Pack (C3), remediation+audit (C6) | ⏳ |

## Quick start (local, no cluster needed)

```sh
cd ai-engine
pip install -e ".[dev]"
pytest -q                     # Tier-1 unit tests (breaker, cache, gateway, guardrail)
```

## What Phase 1 gives you (C4)

- **AI Gateway** (`aie/gateway.py`) — wraps every llm call in `product-reviews`:
  cache → breaker → timeout-bounded call → **429 is NOT retried blindly** → guardrail → fallback.
  The customer never sees a red error.
- **Faithfulness guardrail** (`aie/guardrail.py`) — verifies the summary against the **real
  reviews from Postgres** (not the text alone). Blocks the `llmInaccurateResponse` fault on
  `L9ECAV7KIM` (sentiment inversion vs real avg ~4.6). **Fail-closed.**
- **Cost meter** (`aie/cost_meter.py`) — request-level token/USD showback, tagged by feature/model.
- **5 metrics** (`common/metrics.py`): `ai_gateway_requests_total`, `ai_gateway_latency_seconds`,
  `ai_cache_hit_ratio`, `ai_guardrail_block_total`, `ai_breaker_state` + cost + engine-health.

## Integration into `product-reviews` (no file-sample edits, no flagd changes)

Wrap the two `client.chat.completions.create` call sites in `product_reviews_server.py`:

```python
from ai_engine.aie.gateway import AIGateway, LLMTimeout, RateLimitError
from ai_engine.aie.guardrail import FaithfulnessGuardrail
from ai_engine.common.config import GatewayConfig

gateway = AIGateway(GatewayConfig(), guardrail=FaithfulnessGuardrail())

def call_llm() -> str:
    # existing llm call, mapped to raise RateLimitError on 429 / LLMTimeout on timeout
    ...

result = gateway.summarize(product_id, reviews, call_llm)
summary = result.text        # None => hide AI block, show raw reviews (fallback)
```

This **reads** the flag path via the existing OpenFeature hooks unchanged (RULES §8 compliant).

## Fallback coverage (audited + tested)

Every failure point degrades gracefully — the customer never sees a red error, on-call is
never left blind. Proven by `tests/test_fallback_upgrades.py`.

| Failure point | Fallback | Where |
|---|---|---|
| LLM 429 | no blind retry → cache → hide summary | gateway (`RateLimitError`) |
| LLM timeout / 5xx | retry ≤2 (backoff+jitter) → cache → hide | gateway |
| **LLM hangs** | **hard deadline abandons the call** (protects p95) | `_call_with_timeout` |
| Circuit open | serve fallback immediately, no call | breaker |
| **Retry storm** | **retry budget denies retries >20%/5m** | `_RetryBudget` |
| Guardrail error | fail-closed → hide summary | `_safe_guardrail` |
| **Model quality drift** | **guardrail-block burst trips the breaker** | gateway step [4] |
| No reviews (DB gone) | fail-closed | guardrail |
| Telemetry blind | `ai_engine_blind=1` + meta-alert, never silent | telemetry (C1) |
| Alert webhook down | dashboard + Alertmanager still show it | alert_emitter (C2) |
| Engine dies | Alertmanager burn-rate rules keep paging | `prometheus/burnrate_alerts.yaml` |

Rows in **bold** are the resilience upgrades added after auditing against production LLM
resilience guidance (circuit-breaker + fallback + retry-budget layering; LLM breakers watch
quality, not just error rate).

## Runbooks

- [runbooks/RB-LLM-429.md](runbooks/RB-LLM-429.md) — 429 storm
- [runbooks/RB-LLM-BADSUMMARY.md](runbooks/RB-LLM-BADSUMMARY.md) — suspected wrong summary
- [runbooks/RB-PAY-01.md](runbooks/RB-PAY-01.md) — checkout burn-rate
