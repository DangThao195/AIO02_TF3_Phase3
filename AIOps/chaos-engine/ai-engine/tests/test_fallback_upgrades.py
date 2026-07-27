"""Fallback audit + upgrade proof.

Part 1 proves the fallbacks that already existed still hold.
Part 2 proves the 4 upgrades from the resilience research:
  A) hard timeout around call_llm (protect p95 when llm hangs)
  C) quality-drift breaker (guardrail-block burst trips the breaker)
  D) retry-budget enforcement (retry storm guard)
  (B) tiered fallback / cache-then-hide is already covered in test_aie_phase1.
"""
from __future__ import annotations

import time

import pytest

from ai_engine.aie.gateway import AIGateway, LLMTimeout, Outcome, RateLimitError, _RetryBudget
from ai_engine.aie.guardrail import FaithfulnessGuardrail
from ai_engine.common.config import GatewayConfig

REVIEWS = [
    {"description": "lifesaver, works perfectly, no residue", "score": "5.0"},
    {"description": "great value, effective", "score": "4.5"},
    {"description": "gentle and versatile", "score": "4.0"},
    {"description": "recommend, clear views", "score": "4.5"},
    {"description": "keeps equipment pristine", "score": "5.0"},
]
INACCURATE = "Customers disappointed, sticky residue, scratches, damaged equipment, poor value."


def _cfg(**kw):
    return GatewayConfig(**kw)


# ─────────────────────── PART 1: existing fallbacks still hold ───────────────────────
def test_fallback_serves_cache_when_call_fails_after_success():
    gw = AIGateway(_cfg(max_retries=0), guardrail=None, sleep=lambda s: None)
    gw.summarize("P", REVIEWS, lambda: "good faithful summary about a cleaning kit")  # warms cache
    # now the llm fails, but the same product+reviews serve from cache (fallback)
    res = gw.summarize("P", REVIEWS, lambda: (_ for _ in ()).throw(LLMTimeout()))
    assert res.from_cache is True
    assert res.text is not None


def test_fallback_hides_block_when_no_cache_and_call_fails():
    gw = AIGateway(_cfg(max_retries=0), guardrail=None, sleep=lambda s: None)
    res = gw.summarize("NEW", REVIEWS, lambda: (_ for _ in ()).throw(LLMTimeout()))
    assert res.text is None                 # hide AI block, raw reviews shown — no red error


def test_429_fails_fast_without_sleeping_on_request_path():
    # Bug #2 regression: 429 must not sleep-then-return (that added latency for nothing).
    slept = {"n": 0}
    gw = AIGateway(_cfg(max_retries=2), guardrail=None, sleep=lambda s: slept.__setitem__("n", slept["n"] + 1))
    res = gw.summarize("R", REVIEWS, lambda: (_ for _ in ()).throw(RateLimitError(retry_after=30)))
    assert res.outcome is Outcome.RATE_LIMITED
    assert slept["n"] == 0                   # never slept on the customer's request path


# ─────────────────────── PART 2A: hard timeout protects p95 ───────────────────────
def test_hard_timeout_abandons_a_hung_llm_call():
    # call_llm sleeps far beyond the 800ms budget; the gateway must NOT block that long.
    def hung():
        time.sleep(5)
        return "too late"

    gw = AIGateway(_cfg(per_call_timeout_ms=100, max_retries=0), guardrail=None)
    started = time.monotonic()
    res = gw.summarize("HANG", REVIEWS, hung)
    elapsed = time.monotonic() - started
    assert res.outcome is Outcome.TIMEOUT
    assert res.text is None
    assert elapsed < 1.0                    # returned on time despite the 5s hang


# ─────────────────────── PART 2C: quality-drift breaker ───────────────────────
def test_guardrail_block_burst_trips_breaker():
    # Real guardrail blocks the inaccurate summary; enough blocks in a row open the breaker,
    # so we stop hammering a model that produces unfaithful output.
    gw = AIGateway(_cfg(breaker_fail_threshold=3, max_retries=0), guardrail=FaithfulnessGuardrail())
    for i in range(3):
        r = gw.summarize(f"L9ECAV7KIM-{i}", REVIEWS, lambda: INACCURATE)
        assert r.outcome is Outcome.GUARDRAIL_BLOCK
    # 4th request: breaker is now open -> served as fallback WITHOUT calling the model
    called = {"n": 0}

    def should_not_run():
        called["n"] += 1
        return INACCURATE

    r = gw.summarize("OTHER", REVIEWS, should_not_run)
    assert r.outcome is Outcome.BREAKER_OPEN
    assert called["n"] == 0


# ─────────────────────── PART 2D: retry budget ───────────────────────
def test_retry_budget_denies_retry_after_ratio_exceeded():
    t = [0.0]
    budget = _RetryBudget(ratio=0.20, window_s=300, clock=lambda: t[0])
    # 10 events, 8 of them retries -> ratio 0.8 >> 0.20 -> further retries denied
    for _ in range(2):
        budget.record_call()
    for _ in range(8):
        budget.record_retry()
    assert budget.can_retry() is False


def test_retry_budget_allows_when_few_samples():
    budget = _RetryBudget(ratio=0.20)
    budget.record_retry()
    assert budget.can_retry() is True       # <5 samples: don't rate-limit prematurely


def test_retry_budget_not_tripped_by_normal_first_attempts():
    # Bug #1 regression: many successful first-attempt calls must NOT starve the budget.
    # 10 calls, 0 retries -> ratio 0 -> retries still allowed.
    budget = _RetryBudget(ratio=0.20)
    for _ in range(10):
        budget.record_call()
    assert budget.can_retry() is True
