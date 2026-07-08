# RB-LLM-429 — LLM rate-limit (429) storm

**Trigger:** `ai_gateway_requests_total{outcome="rate_limited"}` rising, or on-call sees
Q&A/summary degraded. Usually the BTC flag `llmRateLimitError` is on (429 ~50% of Q&A calls).

**This is by-design containment, not an outage.** The gateway already handles it.

## Steps (any pillar on-call can run this)

1. **Confirm** via Grafana panel "AI Layer Health": is `outcome=rate_limited` climbing?
2. **Check breaker**: `ai_breaker_state` — is it `2` (open)? If yes, the gateway is already
   fast-failing to fallback (cache or hidden summary). Customers see raw reviews, no red error.
3. **Verify customer impact**: browse/checkout SLO must be UNAFFECTED (AI is best-effort).
   Confirm on the SLO dashboard. If checkout is also hurting → this is NOT just 429, escalate.
4. **Do nothing further** if fallback is serving. Blindly restarting llm or bumping retries
   makes the storm worse. Record it in the incident timeline.
5. **Record**: note in `#tf3-changes` and the Evidence Pack that 429 containment engaged.

## Do NOT

- ❌ Do not toggle `llmRateLimitError` (BTC flag — disqualify, RULES §8).
- ❌ Do not raise `AI_MAX_RETRIES` (retrying into 429 amplifies the storm).
- ❌ Do not disable the breaker.

## Escalate to AIO02 if

- Breaker never opens despite sustained 429 (breaker mis-tuned).
- `ai_cache_hit_ratio` is ~0 during the storm (cache not helping — investigate keys/TTL).
