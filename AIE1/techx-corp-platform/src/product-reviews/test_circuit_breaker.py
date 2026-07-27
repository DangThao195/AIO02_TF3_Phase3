import time
import pytest
from guardrails.circuit_breaker import (
    CircuitBreaker,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_HALF_OPEN,
)


def test_circuit_breaker_initial_state():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=2.0, use_redis=False)
    assert cb.allow_request() is True
    state, failures, _ = cb.get_state()
    assert state == STATE_CLOSED
    assert failures == 0


def test_circuit_breaker_trip_to_open():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=2.0, use_redis=False)

    # 2 failures -> still CLOSED
    cb.record_failure()
    cb.record_failure()
    assert cb.allow_request() is True

    # 3rd failure -> trips to OPEN
    cb.record_failure()
    assert cb.allow_request() is False

    state, failures, _ = cb.get_state()
    assert state == STATE_OPEN
    assert failures == 3


def test_circuit_breaker_cooldown_to_half_open_and_recovery():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.3, use_redis=False)

    # Trip to OPEN
    cb.record_failure()
    cb.record_failure()
    assert cb.allow_request() is False

    # Wait cooldown
    time.sleep(0.35)

    # Transition to HALF-OPEN allows probe request
    assert cb.allow_request() is True
    state, _, _ = cb.get_state()
    assert state == STATE_HALF_OPEN

    # Successful probe resets to CLOSED
    cb.record_success()
    assert cb.allow_request() is True
    state, failures, _ = cb.get_state()
    assert state == STATE_CLOSED
    assert failures == 0


def test_circuit_breaker_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.3, use_redis=False)

    cb.record_failure()
    cb.record_failure()
    time.sleep(0.35)

    assert cb.allow_request() is True  # Transition to HALF-OPEN

    # Probe fails -> immediately OPEN again
    cb.record_failure()
    assert cb.allow_request() is False
    state, _, _ = cb.get_state()
    assert state == STATE_OPEN
