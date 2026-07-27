"""
Retry with Bounded Exponential Backoff for LLM/Bedrock Provider Calls

Implements bounded retry strategy to handle transient failures:
- Exponential backoff: 1s, 2s, 4s, 8s with jitter
- Capped at MAX_RETRIES (default 3) to avoid infinite loops
- Distinguishes transient (retry) vs permanent (fail fast) errors

Ref: MANDATE #25 requirement #2 (bounded retries + backoff with ceiling)
"""

import time
import random
import logging
import asyncio
from typing import Callable, TypeVar, Optional
from dataclasses import dataclass

logger = logging.getLogger("guardrails.retry")

T = TypeVar("T")

# Configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY_MS = 1000
DEFAULT_MAX_DELAY_MS = 8000  # Cap backoff at 8 seconds
JITTER_FACTOR = 0.1  # ±10% jitter


@dataclass
class RetryConfig:
    max_retries: int = DEFAULT_MAX_RETRIES
    initial_delay_ms: int = DEFAULT_INITIAL_DELAY_MS
    max_delay_ms: int = DEFAULT_MAX_DELAY_MS
    jitter_factor: float = JITTER_FACTOR


def _is_transient_error(error: Exception) -> bool:
    """
    Determine if error is transient (retry-worthy) or permanent (fail fast).
    
    Transient: timeout, rate-limit, temporary unavailability
    Permanent: auth error, invalid request, schema error
    """
    error_str = str(error).lower()
    
    # Bedrock transient errors
    if "throttling" in error_str or "rate limit" in error_str:
        return True
    if "timeout" in error_str or "deadline exceeded" in error_str:
        return True
    if "unavailable" in error_str or "temporarily" in error_str:
        return True
    if "connection" in error_str or "network" in error_str:
        return True
    
    # gRPC transient errors
    if "_UNAVAILABLE" in str(type(error).__name__):
        return True
    if "_DEADLINE_EXCEEDED" in str(type(error).__name__):
        return True
    
    return False


def _compute_backoff_ms(attempt: int, config: RetryConfig) -> int:
    """
    Compute exponential backoff with jitter.
    
    Formula: min(max_delay, initial_delay * 2^attempt) + jitter
    """
    base_delay = config.initial_delay_ms * (2 ** attempt)
    capped_delay = min(base_delay, config.max_delay_ms)
    jitter = random.uniform(-config.jitter_factor, config.jitter_factor) * capped_delay
    return int(capped_delay + jitter)


async def retry_with_backoff(
    func: Callable[..., T],
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs
) -> T:
    """
    Retry func with exponential backoff on transient errors.
    
    Args:
        func: Async function to call
        args, kwargs: Arguments to pass to func
        config: RetryConfig (uses defaults if None)
    
    Returns:
        Result of func(*args, **kwargs)
    
    Raises:
        Original exception after MAX_RETRIES attempts
    """
    if config is None:
        config = RetryConfig()
    
    last_error = None
    
    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            
            # Check if error is transient
            if not _is_transient_error(e):
                logger.debug(f"Non-transient error (attempt {attempt}), failing fast: {e}")
                raise
            
            # Last attempt — no more retries
            if attempt == config.max_retries:
                logger.warning(
                    f"[RETRY] Max retries ({config.max_retries}) exhausted: {e}"
                )
                raise
            
            # Compute backoff and sleep
            backoff_ms = _compute_backoff_ms(attempt, config)
            backoff_s = backoff_ms / 1000.0
            logger.warning(
                f"[RETRY] Transient error (attempt {attempt}/{config.max_retries}). "
                f"Backoff {backoff_s:.2f}s: {e}"
            )
            await asyncio.sleep(backoff_s)
    
    # Should not reach here
    raise last_error or Exception("Retry loop completed without result")


def retry_with_backoff_sync(
    func: Callable[..., T],
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs
) -> T:
    """
    Synchronous version of retry_with_backoff.
    
    Args:
        func: Sync function to call
        args, kwargs: Arguments to pass to func
        config: RetryConfig (uses defaults if None)
    
    Returns:
        Result of func(*args, **kwargs)
    
    Raises:
        Original exception after MAX_RETRIES attempts
    """
    if config is None:
        config = RetryConfig()
    
    last_error = None
    
    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            
            # Check if error is transient
            if not _is_transient_error(e):
                logger.debug(f"Non-transient error (attempt {attempt}), failing fast: {e}")
                raise
            
            # Last attempt — no more retries
            if attempt == config.max_retries:
                logger.warning(
                    f"[RETRY] Max retries ({config.max_retries}) exhausted: {e}"
                )
                raise
            
            # Compute backoff and sleep
            backoff_ms = _compute_backoff_ms(attempt, config)
            backoff_s = backoff_ms / 1000.0
            logger.warning(
                f"[RETRY] Transient error (attempt {attempt}/{config.max_retries}). "
                f"Backoff {backoff_s:.2f}s: {e}"
            )
            time.sleep(backoff_s)
    
    # Should not reach here
    raise last_error or Exception("Retry loop completed without result")
