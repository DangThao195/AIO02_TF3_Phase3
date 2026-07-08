# RB-PAY-01 — Checkout error-budget burn (payment path)

**Trigger:** `CheckoutBurnRateCritical` (14.4x on 1h+5m) — checkout SLO ≥99% is burning.
Referenced by the C2 alert's `runbook_link`. Checkout is the revenue flow — highest priority.

**Likely causes (from onboarding + flags):** `paymentFailure` (n% charge fails),
`paymentUnreachable`, `kafkaQueueProblems` (async lag), or a real DB connection-pool
exhaustion (INC-1 history repeats).

## Steps

1. **Ack within 5 minutes** (critical). Open the Evidence Pack link (C3) — it's auto-generated.
2. **Read the alert's `correlated_signals` + `blast_radius`.** If `payment` appears with a
   latency/error anomaly at the same time → payment is the primary suspect.
3. **Check downstream** on the SLO dashboard (`slo-checkout`, blast-radius panel):
   which of checkout|payment|cart|kafka has the error spike?
4. **Contain (do not "fix the flag"):**
   - Payment failing → confirm the gateway/retry budget is engaged; consider scaling payment
     (propose via C6 remediation `scale`, human-approved) if it's saturation, not injected 100% fail.
   - Kafka lag → accounting/fraud are async; checkout success itself may recover once lag drains.
   - Real pool exhaustion → this is a genuine config gap (INC-1): fix pool size at root (not a flag).
5. **Verify** recovery: `sli:checkout_error:ratio_rate5m` falls back below 0.144, then below budget.
6. **Sign** the Evidence Pack root-cause section (C3 §7) before closing.

## Distinguish injected vs real

- **Injected (BTC flag):** contain with fallback/retry/scale; note "likely injected" in the pack
  with behavioural evidence. Never toggle the flag (disqualify, RULES §8).
- **Real config gap:** fix at root (pool size, timeouts, readiness) — that's what scoring rewards.

## Do NOT

- ❌ Toggle `paymentFailure` / `kafkaQueueProblems` or any BTC flag.
- ❌ Approve a remediation `scale` without a rollback plan (C6 refuses it anyway).
