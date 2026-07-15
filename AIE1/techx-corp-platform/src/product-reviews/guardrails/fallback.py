"""
Guardrail: Fallback & Exception Handler (AIE1)

Thứ tự xử lý lỗi:
  1. Gọi LLM lần đầu.
  2. Nếu gặp lỗi tạm thời (429, 5xx, connection) → retry với Exponential
     Backoff + Full Jitter tối đa 3 lần (theo LLM_RETRY_BACKOFF.md).
  3. Chỉ khi toàn bộ lần retry đều thất bại → kích hoạt Fallback tĩnh,
     trả thông báo thân thiện, không để gRPC server treo.

Tham khảo: docs/analysis/LLM_RETRY_BACKOFF.md
"""

import logging
import functools

from openai import (
    OpenAIError,
    RateLimitError,
    InternalServerError,
    APIConnectionError,
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
)
try:
    from botocore.exceptions import ClientError, BotoCoreError
except ImportError:  # pragma: no cover
    ClientError = None
    BotoCoreError = None

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_random_exponential,
        retry_if_exception,
        before_sleep_log,
        RetryError,
    )
    _TENACITY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TENACITY_AVAILABLE = False

logger = logging.getLogger("guardrails.fallback")

# ─── Cấu hình Retry (theo LLM_RETRY_BACKOFF.md) ───────────────────────────────
MAX_RETRIES  = 3     # tổng số lần thử lại
BASE_DELAY   = 1.0   # giây — thời gian chờ ban đầu
MAX_DELAY    = 8.0   # giây — thời gian chờ tối đa


# ─── Phân loại lỗi: chỉ retry lỗi tạm thời ───────────────────────────────────

# Các exception NON-RETRYABLE (400 bad request, 401/403 auth) → fallback ngay
_NON_RETRYABLE = (BadRequestError, AuthenticationError, PermissionDeniedError)


def _is_transient(exc: BaseException) -> bool:
    """
    Trả True nếu lỗi mang tính tạm thời, có thể retry.

    RETRY  : RateLimitError (429), InternalServerError (500/502/503/504),
             APIConnectionError (network glitch).
    NO RETRY: BadRequestError (400), AuthenticationError (401),
              PermissionDeniedError (403) — retry sẽ không có ý nghĩa.
    """
    if isinstance(exc, _NON_RETRYABLE):
        return False
    if ClientError is not None and isinstance(exc, ClientError):
        error_code = str(exc.response.get("Error", {}).get("Code", "")).lower()
        if error_code in {"validationexception", "accessdeniedexception", "unrecognizedclientexception"}:
            return False
        if error_code in {
            "throttlingexception",
            "toomanyrequestsexception",
            "internalserverexception",
            "serviceunavailableexception",
            "modeltimeoutexception",
        }:
            return True
        return True
    if BotoCoreError is not None and isinstance(exc, BotoCoreError):
        return True
    if isinstance(exc, (RateLimitError, InternalServerError, APIConnectionError)):
        return True
    # Với các OpenAIError khác (status không rõ) → retry thận trọng
    if isinstance(exc, OpenAIError):
        return True
    return False


# ─── Retry decorator (tenacity) ───────────────────────────────────────────────

def _build_retry_decorator():
    """Tạo tenacity retry decorator theo spec LLM_RETRY_BACKOFF.md."""
    if not _TENACITY_AVAILABLE:
        logger.warning(
            "[FALLBACK] tenacity is not installed — retry is disabled. "
            "Falling back directly. Install with: pip install tenacity"
        )
        return None

    return retry(
        reraise=True,
        stop=stop_after_attempt(MAX_RETRIES),
        # wait_random_exponential = Full Jitter: random(0, min(max, base * 2^n))
        wait=wait_random_exponential(multiplier=BASE_DELAY, max=MAX_DELAY),
        retry=retry_if_exception(_is_transient),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


_retry_decorator = _build_retry_decorator()


# ─── Công khai ────────────────────────────────────────────────────────────────

def handle_exception(e: Exception) -> str:
    """
    Fallback cuối: ghi log và trả thông báo tĩnh thân thiện.
    Được gọi sau khi toàn bộ retry đều thất bại.
    """
    logger.error("[FALLBACK] Triggered after retries exhausted: %s", e, exc_info=True)
    return "The AI is busy right now. Please try again later."


def with_fallback(fn):
    """
    Decorator: Retry → Fallback.

    Bọc hàm gọi LLM với hai tầng bảo vệ:
      - Tầng 1: Retry tự động (Exponential Backoff + Jitter) cho lỗi tạm thời.
      - Tầng 2: Fallback tĩnh khi retry kiệt sức hoặc gặp lỗi không thể retry.

    Dùng pháp:
        @with_fallback
        def call_llm(...):
            ...
    """
    # Bọc thêm retry nếu tenacity có sẵn
    retryable_fn = _retry_decorator(fn) if _retry_decorator else fn

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return retryable_fn(*args, **kwargs)
        except _NON_RETRYABLE as e:
            # Lỗi không retryable (400/401/403) → fallback ngay, không cần log retry
            logger.error("[FALLBACK] Non-retryable error, skipping retry: %s", e)
            return handle_exception(e)
        except Exception as e:
            # Hết retry hoặc lỗi bất ngờ → fallback
            return handle_exception(e)

    return wrapper

