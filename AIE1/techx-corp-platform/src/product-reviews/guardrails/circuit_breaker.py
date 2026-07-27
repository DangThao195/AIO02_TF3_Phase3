import time
import logging
import threading
from typing import Tuple
from guardrails.cache import redis_client

logger = logging.getLogger("guardrails.circuit_breaker")

STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF-OPEN"

KEY_CB_STATE = "product_reviews:cb:state"
KEY_CB_FAILURES = "product_reviews:cb:failures"
KEY_CB_OPENED_AT = "product_reviews:cb:opened_at"


class CircuitBreaker:
    """
    Self-healing Circuit Breaker managing states (CLOSED, OPEN, HALF-OPEN).
    Backed by Redis with thread-safe in-memory fallback.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0, use_redis: bool = True):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.use_redis = use_redis
        self._lock = threading.Lock()

        # In-memory fallback state
        self._mem_state = STATE_CLOSED
        self._mem_failures = 0
        self._mem_opened_at = 0.0
        self._mem_probing = False

        self._last_redis_check = 0.0
        self._redis_healthy = False

    def _is_redis_available(self) -> bool:
        if not self.use_redis or not redis_client:
            return False
        now = time.time()
        if now - self._last_redis_check < 2.0:
            return self._redis_healthy

        self._last_redis_check = now
        try:
            redis_client.ping()
            self._redis_healthy = True
            return True
        except Exception:
            self._redis_healthy = False
            return False

    def get_state(self) -> Tuple[str, int, float]:
        """Returns (state, consecutive_failures, opened_at)."""
        if self._is_redis_available():
            try:
                state = redis_client.get(KEY_CB_STATE) or STATE_CLOSED
                failures = int(redis_client.get(KEY_CB_FAILURES) or 0)
                opened_at = float(redis_client.get(KEY_CB_OPENED_AT) or 0.0)
                return state, failures, opened_at
            except Exception:
                pass

        with self._lock:
            return self._mem_state, self._mem_failures, self._mem_opened_at

    def allow_request(self) -> bool:
        """
        Determines whether a gRPC LLM request should be allowed or blocked.
        Returns True if request allowed, False if blocked (circuit OPEN).
        """
        now = time.time()
        if self._is_redis_available():
            try:
                state = redis_client.get(KEY_CB_STATE) or STATE_CLOSED
                failures = int(redis_client.get(KEY_CB_FAILURES) or 0)
                opened_at = float(redis_client.get(KEY_CB_OPENED_AT) or 0.0)

                if state == STATE_CLOSED:
                    return True

                if state == STATE_OPEN:
                    if now - opened_at >= self.cooldown_seconds:
                        redis_client.set(KEY_CB_STATE, STATE_HALF_OPEN)
                        logger.info("[CIRCUIT_BREAKER] Cooldown elapsed. Transitioned OPEN -> HALF-OPEN")
                        return True
                    logger.warning(
                        "[CIRCUIT_BREAKER] Blocked request. Circuit is OPEN (failures=%d, cool_down_remaining=%.1fs)",
                        failures,
                        self.cooldown_seconds - (now - opened_at),
                    )
                    return False

                if state == STATE_HALF_OPEN:
                    return True
            except Exception as e:
                logger.warning("[CIRCUIT_BREAKER] Redis error in allow_request: %s", e)

        # In-memory fallback
        with self._lock:
            if self._mem_state == STATE_CLOSED:
                return True

            if self._mem_state == STATE_OPEN:
                if now - self._mem_opened_at >= self.cooldown_seconds:
                    self._mem_state = STATE_HALF_OPEN
                    self._mem_probing = True
                    logger.info("[CIRCUIT_BREAKER] Cooldown elapsed (Memory). Transitioned OPEN -> HALF-OPEN")
                    return True
                logger.warning(
                    "[CIRCUIT_BREAKER] Blocked request (Memory). Circuit is OPEN (failures=%d, cool_down_remaining=%.1fs)",
                    self._mem_failures,
                    self.cooldown_seconds - (now - self._mem_opened_at),
                )
                return False

            if self._mem_state == STATE_HALF_OPEN:
                return True

        return True

    def record_success(self) -> None:
        """Resets failures and sets state to CLOSED."""
        if self._is_redis_available():
            try:
                redis_client.set(KEY_CB_STATE, STATE_CLOSED)
                redis_client.set(KEY_CB_FAILURES, "0")
                redis_client.set(KEY_CB_OPENED_AT, "0.0")
                logger.info("[CIRCUIT_BREAKER] Request SUCCESS. Reset state -> CLOSED")
            except Exception as e:
                logger.warning("[CIRCUIT_BREAKER] Redis record_success error: %s", e)

        with self._lock:
            self._mem_state = STATE_CLOSED
            self._mem_failures = 0
            self._mem_opened_at = 0.0
            self._mem_probing = False

    def record_failure(self) -> None:
        """Increments failure counter and transitions to OPEN if threshold reached."""
        now = time.time()
        if self._is_redis_available():
            try:
                state = redis_client.get(KEY_CB_STATE) or STATE_CLOSED
                failures = int(redis_client.get(KEY_CB_FAILURES) or 0) + 1
                redis_client.set(KEY_CB_FAILURES, str(failures))

                if failures >= self.failure_threshold or state == STATE_HALF_OPEN:
                    redis_client.set(KEY_CB_STATE, STATE_OPEN)
                    redis_client.set(KEY_CB_OPENED_AT, str(now))
                    logger.warning(
                        "[CIRCUIT_BREAKER] Failure threshold reached (%d/%d). Transitioned -> OPEN for %.0fs",
                        failures,
                        self.failure_threshold,
                        self.cooldown_seconds,
                    )
            except Exception as e:
                logger.warning("[CIRCUIT_BREAKER] Redis record_failure error: %s", e)

        with self._lock:
            self._mem_failures += 1
            if self._mem_failures >= self.failure_threshold or self._mem_state == STATE_HALF_OPEN:
                self._mem_state = STATE_OPEN
                self._mem_opened_at = now
                self._mem_probing = False
                logger.warning(
                    "[CIRCUIT_BREAKER] Failure threshold reached (Memory %d/%d). Transitioned -> OPEN",
                    self._mem_failures,
                    self.failure_threshold,
                )

    def reset(self) -> None:
        """Force resets circuit breaker to CLOSED."""
        if self._is_redis_available():
            try:
                redis_client.delete(KEY_CB_STATE, KEY_CB_FAILURES, KEY_CB_OPENED_AT)
            except Exception:
                pass
        self.record_success()


# Global CircuitBreaker singleton
circuit_breaker = CircuitBreaker()
