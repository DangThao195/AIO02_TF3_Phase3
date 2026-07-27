"""
guardrails/error_injection.py
=============================
Error Injection State Manager – Task 3 (AIE1 Phase 3)

Cho phép AIOps / operator bơm lỗi giả lập qua HTTP endpoint
``POST /inject/error`` để kiểm chứng khả năng tự phục hồi của hệ thống
mà không cần thay đổi code hoặc restart container.

Redis key: ``product_reviews:inject_error``
  - Value: error_type string (e.g. ``"429"``, ``"timeout"``, ``"500"``,
    ``"circuit_breaker"``)
  - Absent / empty → injection inactive.

In-memory fallback ``_mem_inject_error`` được dùng khi Redis không khả dụng.
"""

import logging
import threading
from typing import Optional

from guardrails.cache import redis_client  # shared Redis client

logger = logging.getLogger("guardrails.error_injection")

REDIS_KEY_INJECT = "product_reviews:inject_error"
VALID_ERROR_TYPES = frozenset({"429", "timeout", "500", "circuit_breaker"})

# In-memory fallback (thread-safe)
_lock = threading.Lock()
_mem_inject_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redis_available() -> bool:
    if not redis_client:
        return False
    try:
        redis_client.ping()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_injected_error_type() -> Optional[str]:
    """Return active injected error type, or None if injection is inactive."""
    if _redis_available():
        try:
            val = redis_client.get(REDIS_KEY_INJECT)
            if val:
                return str(val).strip() or None
            return None
        except Exception as exc:
            logger.warning("[ERROR_INJECTION] Redis read failed: %s", exc)

    with _lock:
        return _mem_inject_error


def set_error_injection(error_type: str) -> None:
    """Activate error injection for the given error_type."""
    if error_type not in VALID_ERROR_TYPES:
        raise ValueError(
            f"Invalid error_type '{error_type}'. "
            f"Valid values: {sorted(VALID_ERROR_TYPES)}"
        )
    logger.warning("[ERROR_INJECTION] Activating injection: error_type=%s", error_type)
    if _redis_available():
        try:
            redis_client.set(REDIS_KEY_INJECT, error_type)
        except Exception as exc:
            logger.warning("[ERROR_INJECTION] Redis write failed: %s", exc)

    with _lock:
        global _mem_inject_error
        _mem_inject_error = error_type


def clear_error_injection() -> None:
    """Deactivate error injection (clear state)."""
    logger.info("[ERROR_INJECTION] Clearing injection state.")
    if _redis_available():
        try:
            redis_client.delete(REDIS_KEY_INJECT)
        except Exception as exc:
            logger.warning("[ERROR_INJECTION] Redis delete failed: %s", exc)

    with _lock:
        global _mem_inject_error
        _mem_inject_error = None


def get_injection_status() -> dict:
    """Return a status dict describing current injection state."""
    active_type = get_injected_error_type()
    redis_ok = _redis_available()
    return {
        "active": active_type is not None,
        "error_type": active_type,
        "backend": "redis" if redis_ok else "memory",
        "valid_error_types": sorted(VALID_ERROR_TYPES),
    }
