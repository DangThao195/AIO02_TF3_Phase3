# RB-LLM-BADSUMMARY — suspected misleading AI summary

**Trigger:** `ai_guardrail_block_total` spikes, or a human reports a wrong summary.
This maps to the BTC flag `llmInaccurateResponse` (wrong summary for product `L9ECAV7KIM`).

**SLO is HARD here:** "no misleading summary shown to the customer." Content safety > feature.

## Steps

1. **Check the guardrail**: is `ai_guardrail_block_total{reason="sentiment_mismatch"}` rising?
   If yes → the guardrail is **catching it**; the customer is seeing raw reviews, not the lie.
   Working as intended. Record and move on.
2. **If guardrail did NOT block but customers see a wrong summary** (guardrail miss):
   - Immediately hide the summary using **TF's own flag** `disableAISummary`
     (a flag WE added — allowed, RULES §8). Do NOT touch `llmInaccurateResponse`.
   - This stops customer exposure within seconds.
3. **Escalate AIO02** to tune the guardrail (add the missed claim/sentiment rule, extend
   the golden set with the failing case, re-run eval).
4. **Verify**: after the guardrail fix, the golden-set case for `L9ECAV7KIM` blocks again
   and truthful summaries still PASS (0 false-block).

## Do NOT

- ❌ Do not toggle `llmInaccurateResponse` (BTC flag — disqualify).
- ❌ Do not disable the guardrail to "make blocks go away" — that shows the lie to customers.

## Verify commands

```
# guardrail is blocking the inaccurate case
sum(rate(ai_guardrail_block_total{reason="sentiment_mismatch"}[5m])) > 0
```
