"""Phase 1 unit tests (Tier-1, laptop-only). Prove the resilience + guardrail logic
without a cluster. These are the C4 acceptance behaviours in miniature.

Run: cd ai-engine && pip install -e . && pytest -q
"""
from __future__ import annotations

import pytest

from ai_engine.aie.breaker import CircuitBreaker, State
from ai_engine.aie.gateway import AIGateway, LLMTimeout, Outcome, RateLimitError
from ai_engine.aie.guardrail import FaithfulnessGuardrail
from ai_engine.common.config import GatewayConfig


# ── fixtures: the REAL L9ECAV7KIM data from init.sql (avg ~4.6, all positive) ──
REAL_REVIEWS = [
    {"username": "clean_optics", "description": "This kit is a lifesaver. The brush and wipes work perfectly without leaving any residue.", "score": "5.0"},
    {"username": "photog_pro", "description": "Essential for any photographer. It safely removes dust and fingerprints.", "score": "4.5"},
    {"username": "daily_cleaner", "description": "Very effective and gentle. A versatile cleaning kit.", "score": "4.0"},
    {"username": "tech_maintenance", "description": "Great value for money. Keeps my equipment pristine.", "score": "5.0"},
    {"username": "sharp_view", "description": "Works as advertised, views much clearer. Definitely recommend.", "score": "4.5"},
]
ACCURATE = ("This lens cleaning kit is highly praised as versatile and essential, effective "
            "at removing dust and fingerprints without residue, providing great value.")
INACCURATE = ("Customers are largely disappointed, citing ineffectiveness. The fluid leaves a "
              "sticky residue and the brush causes scratches, damaged equipment, poor value.")


def _cfg(**kw) -> GatewayConfig:
    return GatewayConfig(**kw)


# ─────────────────────────── circuit breaker ───────────────────────────
def test_breaker_opens_after_threshold_and_recovers():
    t = [0.0]
    br = CircuitBreaker(fail_threshold=3, open_seconds=60, clock=lambda: t[0])
    for _ in range(3):
        br.record_failure()
    assert br.state is State.OPEN
    assert br.allow() is False
    t[0] = 61                      # cooldown elapsed
    assert br.state is State.HALF_OPEN
    assert br.allow() is True
    br.record_success()
    assert br.state is State.CLOSED


# ─────────────────────────── gateway: 429 handling ───────────────────────────
def test_429_is_not_retried_blindly_and_falls_back():
    calls = {"n": 0}

    def call_llm():
        calls["n"] += 1
        raise RateLimitError(retry_after=None)

    gw = AIGateway(_cfg(max_retries=2), guardrail=None, sleep=lambda s: None)
    res = gw.summarize("P1", REAL_REVIEWS, call_llm)
    assert res.outcome is Outcome.RATE_LIMITED
    assert res.text is None                 # fallback: hide AI block, raw reviews still shown
    assert calls["n"] == 1                  # NOT retried into the 429 storm


def test_timeout_retries_then_falls_back():
    calls = {"n": 0}

    def call_llm():
        calls["n"] += 1
        raise LLMTimeout()

    gw = AIGateway(_cfg(max_retries=2), guardrail=None, sleep=lambda s: None)
    res = gw.summarize("P2", REAL_REVIEWS, call_llm)
    assert res.outcome is Outcome.TIMEOUT
    assert calls["n"] == 3                  # 1 + 2 retries


def test_cache_hit_avoids_second_call():
    calls = {"n": 0}

    def call_llm():
        calls["n"] += 1
        return ACCURATE

    gw = AIGateway(_cfg(), guardrail=None)
    first = gw.summarize("P3", REAL_REVIEWS, call_llm)
    second = gw.summarize("P3", REAL_REVIEWS, call_llm)
    assert first.outcome is Outcome.OK
    assert second.outcome is Outcome.CACHE_HIT
    assert calls["n"] == 1                  # second served from cache


def test_breaker_open_serves_fallback_without_calling():
    def boom():
        raise LLMTimeout()

    gw = AIGateway(_cfg(max_retries=0, breaker_fail_threshold=1), guardrail=None,
                   sleep=lambda s: None)
    gw.summarize("P4", REAL_REVIEWS, boom)          # trips breaker open
    called = {"n": 0}

    def should_not_run():
        called["n"] += 1
        return ACCURATE

    res = gw.summarize("P4b", REAL_REVIEWS, should_not_run)
    assert res.outcome is Outcome.BREAKER_OPEN
    assert called["n"] == 0                 # breaker short-circuited the call


# ─────────────────────────── guardrail: llmInaccurateResponse ───────────────────────────
def test_guardrail_blocks_inaccurate_summary():
    gr = FaithfulnessGuardrail()
    v = gr.check(INACCURATE, REAL_REVIEWS)
    assert v.passed is False
    assert "sentiment_mismatch" in v.reason or "claim_unsupported" in v.reason


def test_guardrail_passes_accurate_summary():
    gr = FaithfulnessGuardrail()
    v = gr.check(ACCURATE, REAL_REVIEWS)
    assert v.passed is True                 # 0 false-block on the truthful summary


def test_guardrail_fails_closed_without_reviews():
    gr = FaithfulnessGuardrail()
    assert gr.check(ACCURATE, []).passed is False   # no ground truth => cannot vouch


def test_gateway_hides_summary_when_guardrail_blocks():
    gw = AIGateway(_cfg(), guardrail=FaithfulnessGuardrail())
    res = gw.summarize("L9ECAV7KIM", REAL_REVIEWS, lambda: INACCURATE)
    assert res.outcome is Outcome.GUARDRAIL_BLOCK
    assert res.text is None                 # customer never sees the misleading summary
