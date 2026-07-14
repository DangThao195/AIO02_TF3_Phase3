"""
Guardrail: Fallback & Exception Handler (AIE1)

Wraps LLM calls to catch timeouts and errors so the gRPC server doesn't hang.
Returns a static fallback response.
"""

import logging
import functools
from openai import OpenAIError

logger = logging.getLogger("guardrails.fallback")

def handle_exception(e: Exception) -> str:
    """
    Handle exceptions and return a fallback string.
    """
    logger.error(f"[FALLBACK] Exception in AI processing: {e}", exc_info=True)
    return "Hiện tại không thể tóm tắt đánh giá, vui lòng thử lại sau."

def with_fallback(fn):
    """
    Decorator to wrap functions with fallback error handling.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OpenAIError as e:
            return handle_exception(e)
        except Exception as e:
            return handle_exception(e)
    return wrapper
