"""Circuit breaker (C4). The most important production lesson: do NOT retry blindly into 429.

States: closed -> (N consecutive fails OR 5m error-rate > 50%) -> open (fail fast, serve
fallback for open_seconds) -> half-open (one probe) -> success -> closed.

This is a synchronous, in-process breaker embedded in product-reviews (ADR-001: AIE stays
in-process to keep p95 < 1s). It has no external deps so it is trivially unit-testable.
"""
from __future__ import annotations

import time
from enum import IntEnum

from ..common.metrics import BREAKER_STATE


class State(IntEnum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2


class CircuitBreaker:
    def __init__(self, fail_threshold: int, open_seconds: int, clock=time.monotonic):
        self._fail_threshold = fail_threshold
        self._open_seconds = open_seconds
        self._clock = clock
        self._state = State.CLOSED
        self._consecutive_fails = 0
        self._opened_at = 0.0
        self._publish()

    @property
    def state(self) -> State:

        if self._state is State.OPEN and self._clock() - self._opened_at >= self._open_seconds:
            self._state = State.HALF_OPEN
            self._publish()
        return self._state

    def allow(self) -> bool:
        """True if a real call is allowed. False => caller must serve fallback immediately."""
        return self.state is not State.OPEN

    def record_success(self) -> None:
        self._consecutive_fails = 0
        if self._state is not State.CLOSED:
            self._state = State.CLOSED
            self._publish()

    def record_failure(self) -> None:
        """Count a failure (timeout / 5xx / 429-over-threshold). May trip the breaker open."""
        self._consecutive_fails += 1
        if self._state is State.HALF_OPEN or self._consecutive_fails >= self._fail_threshold:
            self._trip_open()

    def force_open(self) -> None:
        """breaker-force action (C6)."""
        self._trip_open()

    def force_close(self) -> None:
        self._consecutive_fails = 0
        self._state = State.CLOSED
        self._publish()

    def _trip_open(self) -> None:
        self._state = State.OPEN
        self._opened_at = self._clock()
        self._publish()

    def _publish(self) -> None:
        BREAKER_STATE.set(int(self._state))
