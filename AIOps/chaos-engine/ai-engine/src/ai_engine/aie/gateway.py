"""AI Gateway (C4) — the single control point wrapping every llm call in product-reviews.

Order per request: cache -> breaker -> call (timeout, disciplined retry, 429 special-case)
-> guardrail -> cache+return, else tiered fallback. The customer NEVER sees a red error.

Embedded in-process (ADR-001). `call_llm` is injected so this is testable with a fake LLM
and so it wraps BOTH llm call sites in product_reviews_server.py without touching flagd.
"""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from ..common.config import GatewayConfig
from ..common.metrics import GATEWAY_LATENCY, GATEWAY_REQUESTS
from .breaker import CircuitBreaker
from .cache import SummaryCache, review_version


class _RetryBudget:
    """Enforces C4's "≤20% of calls in 5m may be retries" — a retry storm guard.

    Without this, N failing requests each fire max_retries and amplify an outage. Tracks
    (timestamp, was_retry) in a sliding 5-min window; denies a retry once the ratio is hit.
    """

    def __init__(self, ratio: float, window_s: int = 300, clock: Callable[[], float] = time.monotonic):
        self._ratio = ratio
        self._window = window_s
        self._clock = clock
        self._events: deque[tuple[float, bool]] = deque()

    def _evict(self) -> None:
        cutoff = self._clock() - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def record_call(self) -> None:
        """One logical call entered the retry loop — the denominator."""
        self._events.append((self._clock(), False))

    def record_retry(self) -> None:
        """A retry was actually performed — the numerator."""
        self._events.append((self._clock(), True))

    def can_retry(self) -> bool:
        self._evict()
        total = len(self._events)
        if total < 5:
            return True
        retries = sum(1 for _, r in self._events if r)
        return (retries / total) < self._ratio


class Outcome(str, Enum):
    OK = "ok"
    CACHE_HIT = "cache_hit"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    GUARDRAIL_BLOCK = "guardrail_block"
    BREAKER_OPEN = "breaker_open"


class RateLimitError(Exception):
    """429 from llm. Carries optional Retry-After (seconds)."""

    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__("llm rate limited (429)")


class LLMTimeout(Exception):
    pass


class Guardrail(Protocol):
    def check(self, summary: str, reviews: list) -> object:
        """Verify summary against the real reviews (ground truth). Returns an object with
        `.passed: bool` and `.reason: str`. Fail-closed handled by the gateway wrapper."""
        ...


@dataclass
class GatewayResult:
    text: str | None
    outcome: Outcome
    from_cache: bool = False
    blocked_reason: str | None = None


class AIGateway:
    """Wraps a single logical "summarize/answer" operation with full resilience + guardrail."""

    def __init__(
        self,
        cfg: GatewayConfig,
        guardrail: Guardrail | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._cfg = cfg
        self._guardrail = guardrail
        self._clock = clock
        self._sleep = sleep
        self._cache = SummaryCache(cfg.cache_ttl_seconds)
        self._breaker = CircuitBreaker(cfg.breaker_fail_threshold, cfg.breaker_open_seconds, clock)
        self._retry_budget = _RetryBudget(cfg.retry_budget_ratio, clock=clock)

        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ai-gw")
        self._max_concurrency = 16
        self._active_requests = 0
        self._counter_lock = threading.Lock()

    def summarize(
        self,
        product_id: str,
        reviews: list,
        call_llm: Callable[[], str],
    ) -> GatewayResult:
        """`call_llm` performs the actual (timeout-bounded) llm request and returns text,
        or raises RateLimitError / LLMTimeout / Exception."""
        version = review_version(reviews)

        # 1. Kiểm tra cache trước (không tính vào concurrency limit vì đọc cache cực nhanh)
        cached = self._cache.get(product_id, version)
        if cached is not None:
            GATEWAY_REQUESTS.labels(outcome=Outcome.CACHE_HIT.value).inc()
            return GatewayResult(text=cached, outcome=Outcome.CACHE_HIT, from_cache=True)

        # 2. Kiểm tra giới hạn Concurrency (Throttling)
        with self._counter_lock:
            if self._active_requests >= self._max_concurrency:
                GATEWAY_REQUESTS.labels(outcome=Outcome.RATE_LIMITED.value).inc()
                return self._fallback(product_id, version, Outcome.RATE_LIMITED)
            self._active_requests += 1

        try:
            start = self._clock()
            if not self._breaker.allow():
                return self._fallback(product_id, version, Outcome.BREAKER_OPEN)

            text, outcome = self._call_with_retry(call_llm)
            GATEWAY_LATENCY.observe(self._clock() - start)
            if text is None:
                return self._fallback(product_id, version, outcome)

            if self._guardrail is not None:
                passed, reason = self._safe_guardrail(text, reviews)
                if not passed:
                    GATEWAY_REQUESTS.labels(outcome=Outcome.GUARDRAIL_BLOCK.value).inc()
                    self._breaker.record_failure()
                    return GatewayResult(
                        text=None, outcome=Outcome.GUARDRAIL_BLOCK, blocked_reason=reason
                    )

            self._breaker.record_success()
            self._cache.set(product_id, version, text)
            GATEWAY_REQUESTS.labels(outcome=Outcome.OK.value).inc()
            return GatewayResult(text=text, outcome=Outcome.OK)
        finally:
            with self._counter_lock:
                self._active_requests -= 1


    def _call_with_retry(self, call_llm: Callable[[], str]) -> tuple[str | None, Outcome]:
        attempts = self._cfg.max_retries + 1


        self._retry_budget.record_call()
        for attempt in range(attempts):
            is_retry = attempt > 0

            if is_retry:
                if not self._retry_budget.can_retry():
                    GATEWAY_REQUESTS.labels(outcome=Outcome.ERROR.value).inc()
                    return None, Outcome.ERROR
                self._retry_budget.record_retry()
            try:
                text = self._call_with_timeout(call_llm)


                return text, Outcome.OK
            except RateLimitError:


                self._breaker.record_failure()
                GATEWAY_REQUESTS.labels(outcome=Outcome.RATE_LIMITED.value).inc()
                return None, Outcome.RATE_LIMITED
            except LLMTimeout:
                self._breaker.record_failure()
                if attempt == attempts - 1:
                    GATEWAY_REQUESTS.labels(outcome=Outcome.TIMEOUT.value).inc()
                    return None, Outcome.TIMEOUT
                self._backoff(attempt)
            except Exception:
                self._breaker.record_failure()
                if attempt == attempts - 1:
                    GATEWAY_REQUESTS.labels(outcome=Outcome.ERROR.value).inc()
                    return None, Outcome.ERROR
                self._backoff(attempt)
        return None, Outcome.ERROR

    def _call_with_timeout(self, call_llm: Callable[[], str]) -> str:
        """Hard deadline around call_llm (gap A) so a hung llm cannot exceed the latency budget.

        Submits to a BOUNDED, shared executor and waits per_call_timeout_ms. Bounding the pool
        (bug #3 fix) means hung calls cannot spawn unbounded abandoned threads under load — once
        the pool is saturated, new submissions fail fast to fallback instead of exhausting
        product-reviews' own thread pool. A real client-side httpx timeout should still be set;
        this is the belt-and-suspenders ceiling.
        """
        timeout_s = self._cfg.per_call_timeout_ms / 1000
        try:
            future = self._executor.submit(call_llm)
        except RuntimeError:
            raise LLMTimeout() from None
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeout:
            future.cancel()
            raise LLMTimeout() from None

    def _backoff(self, attempt: int) -> None:
        base = 0.2 * (2 ** attempt)
        self._sleep(base + random.uniform(0, 0.1))

    def _safe_guardrail(self, text: str, reviews: list) -> tuple[bool, str]:
        try:
            verdict = self._guardrail.check(text, reviews)
            return verdict.passed, verdict.reason
        except Exception:
            return False, "model_error"

    def _fallback(self, product_id: str, version: str, outcome: Outcome) -> GatewayResult:
        cached = self._cache.get(product_id, version)
        if cached is not None:
            return GatewayResult(text=cached, outcome=outcome, from_cache=True)
        return GatewayResult(text=None, outcome=outcome)


    def flush_cache(self) -> None:
        self._cache.flush()

    def force_breaker_open(self) -> None:
        self._breaker.force_open()
