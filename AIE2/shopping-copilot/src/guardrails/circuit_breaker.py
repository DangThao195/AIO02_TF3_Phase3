"""
Circuit Breaker for LLM/Bedrock Provider Failures

Implements the circuit-breaker pattern to prevent hammering a failing provider:
- CLOSED: normal operation, requests go through
- OPEN: provider failing, requests fail fast with fallback
- HALF_OPEN: test if provider recovered; one request allowed
- Auto-recovery when provider is healthy again

Ref: MANDATE #25 requirement #3 (circuit-breaker stops hammering on sustained failure)
"""

import time
import threading
import logging
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("guardrails.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: int = 60  # Seconds in OPEN before trying HALF_OPEN
    success_threshold: int = 2  # Successes in HALF_OPEN to close


class CircuitBreaker:
    """
    Thread-safe circuit breaker for Bedrock/LLM provider.
    
    Usage:
        breaker = CircuitBreaker(config)
        try:
            breaker.call(lambda: bedrock_model.invoke(...))
        except CircuitBreakerOpen:
            # Fallback: use cache, heuristics, or abstain
    """

    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._lock = threading.RLock()
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._last_state_change = time.time()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._state == CircuitState.OPEN

    def _should_attempt_half_open(self) -> bool:
        """Check if it's time to transition from OPEN → HALF_OPEN."""
        return (
            self._state == CircuitState.OPEN
            and self._last_failure_time is not None
            and time.time() - self._last_failure_time >= self.config.recovery_timeout
        )

    def call(self, func, *args, **kwargs):
        """
        Execute func under circuit breaker protection.
        
        Raises:
            CircuitBreakerOpen: if breaker is open
        
        Returns:
            Result of func(*args, **kwargs)
        """
        with self._lock:
            # Transition OPEN → HALF_OPEN if recovery timeout exceeded
            if self._should_attempt_half_open():
                logger.info(f"[CIRCUIT_BREAKER:{self.name}] Transitioning OPEN → HALF_OPEN (recovery timeout reached)")
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

            # If open, fail fast without calling func
            if self._state == CircuitState.OPEN:
                logger.warning(f"[CIRCUIT_BREAKER:{self.name}] Circuit is OPEN — rejecting request")
                raise CircuitBreakerOpen(f"Circuit breaker {self.name} is OPEN")

        # Call func (outside lock to avoid deadlock)
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(f"[CIRCUIT_BREAKER:{self.name}] HALF_OPEN success #{self._success_count}")
                
                if self._success_count >= self.config.success_threshold:
                    logger.info(f"[CIRCUIT_BREAKER:{self.name}] Transitioning HALF_OPEN → CLOSED (provider recovered)")
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._last_state_change = time.time()
            else:
                # CLOSED: reset failure count
                self._failure_count = 0

    def _on_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            logger.warning(f"[CIRCUIT_BREAKER:{self.name}] Failure #{self._failure_count}")

            if self._state == CircuitState.HALF_OPEN:
                # Failure in HALF_OPEN → back to OPEN
                logger.warning(f"[CIRCUIT_BREAKER:{self.name}] Failure in HALF_OPEN — back to OPEN")
                self._state = CircuitState.OPEN
                self._success_count = 0
                self._last_state_change = time.time()
            elif self._failure_count >= self.config.failure_threshold and self._state == CircuitState.CLOSED:
                # CLOSED → OPEN when threshold reached
                logger.error(f"[CIRCUIT_BREAKER:{self.name}] Failure threshold reached — opening circuit")
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    pass
