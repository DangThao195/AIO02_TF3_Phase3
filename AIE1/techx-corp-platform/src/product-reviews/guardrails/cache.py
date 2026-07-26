import os
import hashlib
import json
import logging
from typing import Dict, Any, Optional
import redis

logger = logging.getLogger("guardrails.cache")

# Env configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_USE_TLS = os.environ.get("REDIS_USE_TLS", "false").lower() == "true"
REDIS_AUTH_TOKEN = os.environ.get("REDIS_AUTH_TOKEN") or os.environ.get("REDIS_PASSWORD")
LLM_CACHE_TTL_SECONDS = int(os.environ.get("LLM_CACHE_TTL_SECONDS", 86400))

# Connection URL / Init
# Use rediss:// for secure TLS connection if specified
try:
    if REDIS_USE_TLS:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_AUTH_TOKEN,
            ssl=True,
            ssl_cert_reqs="required",
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
            decode_responses=True
        )
    else:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_AUTH_TOKEN,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
            decode_responses=True
        )
except Exception as e:
    logger.error(f"Failed to initialize Redis client: {e}")
    redis_client = None


def is_fallback_override_active() -> bool:
    """Kiểm tra Redis key product_reviews:fallback_override ("true" / "1" / "false" / "0")."""
    global redis_client
    if not redis_client:
        return False
    try:
        val = redis_client.get("product_reviews:fallback_override")
        if val and str(val).strip().lower() in ("true", "1", "yes", "on"):
            logger.warning("[FALLBACK_OVERRIDE] Active via Redis key product_reviews:fallback_override")
            return True
    except Exception as e:
        logger.warning(f"[FALLBACK_OVERRIDE] Redis read failed: {e}")
    return False



def generate_cache_key(product_id: str, review_version: str, model_id: str, question: str) -> str:
    """Sinh cache key dưới dạng SHA256 để đảm bảo độ dài cố định và tránh ký tự đặc biệt."""
    normalized_q = " ".join(question.lower().strip().split())
    raw_key = f"{product_id}:{review_version}:{model_id}:{normalized_q}"
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def get_cached_response(cache_key: str) -> Optional[Dict[str, Any]]:
    """Đọc câu trả lời từ Redis với cơ chế Fail-Open."""
    if not redis_client:
        return None
    try:
        data = redis_client.get(cache_key)
        if data:
            logger.info(f"[CACHE] Hit! Key: {cache_key}")
            return json.loads(data)
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning(f"[CACHE] Redis unavailable for read, bypassing cache (Fail-Open): {e}")
    except Exception as e:
        logger.error(f"[CACHE] Error reading from Redis: {e}")
    return None


def set_cached_response(cache_key: str, cache_data: Dict[str, Any], ttl: int = LLM_CACHE_TTL_SECONDS) -> bool:
    """Ghi câu trả lời vào Redis với cơ chế Fail-Open."""
    if not redis_client:
        return False
    try:
        redis_client.setex(cache_key, ttl, json.dumps(cache_data))
        logger.info(f"[CACHE] Save success! Key: {cache_key}, TTL: {ttl}s")
        return True
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logger.warning(f"[CACHE] Redis unavailable for write, skipping cache save (Fail-Open): {e}")
    except Exception as e:
        logger.error(f"[CACHE] Error writing to Redis: {e}")
    return False


def should_cache(response_text: str, approved: bool) -> bool:
    """Xác định xem kết quả có nên được cache không (Cache Policy)."""
    # 1. Chỉ cache nếu kết quả được phê duyệt bởi Fidelity Judge
    if not approved:
        return False
        
    # 2. Không cache các thông điệp lỗi hoặc fallback mặc định
    ignored_responses = {
        "The AI is busy right now. Please try again later.",
        "The summary cannot be verified. Please try again later.",
        "This question is out of scope. I only answer questions related to the product.",
        "No information in reviews."
    }
    if response_text in ignored_responses:
        return False
        
    return True


def acquire_lock(lock_key: str, expire: int = 10) -> bool:
    """Nhận khóa phân tán (Distributed Lock) bằng SET NX để chống Cache Stampede."""
    if not redis_client:
        return False
    try:
        # lock tối đa expire giây để tránh deadlock
        return bool(redis_client.set(lock_key, "1", nx=True, ex=expire))
    except Exception as e:
        logger.warning(f"[CACHE] Failed to acquire lock due to Redis error: {e}")
        return False


def release_lock(lock_key: str) -> None:
    """Giải phóng khóa phân tán."""
    if not redis_client:
        return
    try:
        redis_client.delete(lock_key)
    except Exception as e:
        logger.warning(f"[CACHE] Failed to release lock due to Redis error: {e}")
