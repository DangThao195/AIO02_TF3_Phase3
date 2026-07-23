"""
memory/cache_manager.py — CacheManager 2-layer

Layer 1 (primary): Redis
Layer 2 (fallback): In-memory CacheStore
Circuit breaker: CLOSED → OPEN (2 fails) → HALF-OPEN (30s) → CLOSED
"""

from __future__ import annotations

import hashlib
import json
import asyncio
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("memory.cache_manager")

# TTLs (seconds)
TTL = {
    "planner":   300,   # 5 min
    "search":    600,   # 10 min
    "product":   1800,  # 30 min
    "currency":  3600,  # 60 min
    "shipping":  1800,  # 30 min
    "recommend": 900,   # 15 min
    "session":   1800,  # 30 min
}

_CB_FAIL_THRESHOLD = 2
_CB_HALF_OPEN_TIMEOUT = 30.0


class CacheManager:
    """2-layer cache: Redis primary + in-memory fallback with circuit breaker."""

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._redis: Any = None
        self._local: Any = None

        # Circuit breaker state
        self._lock: Any = None
        self._init_lock()
        self._cb_state = "CLOSED"   # CLOSED | OPEN | HALF_OPEN
        self._cb_failures = 0
        self._cb_last_fail = 0.0

    def _init_lock(self):
        self._lock = asyncio.Lock()

        self._init_local()
        if self._redis_url:
            self._init_redis()

    def _init_local(self) -> None:
        try:
            from src.memory.store import CacheStore
            self._local = CacheStore()
        except Exception as e:
            logger.warning("[cache_manager] CacheStore init failed: %s", e)

    def _init_redis(self) -> None:
        try:
            from src.memory.redis_store import RedisCacheStore
            self._redis = RedisCacheStore(self._redis_url)
            logger.info("[cache_manager] Redis connected: %s", self._redis_url)
        except Exception as e:
            logger.warning("[cache_manager] Redis init failed: %s", e)

    async def _redis_healthy(self) -> bool:
        if not self._redis:
            return False

        now = time.time()

        async with self._lock:
            if self._cb_state == "OPEN":
                if now - self._cb_last_fail > _CB_HALF_OPEN_TIMEOUT:
                    self._cb_state = "HALF_OPEN"
                else:
                    return False

        try:
            ok = await self._redis.ping()
            if ok:
                async with self._lock:
                    self._cb_state = "CLOSED"
                    self._cb_failures = 0
                return True
            raise RuntimeError("ping failed")
        except Exception:
            async with self._lock:
                self._cb_failures += 1
                self._cb_last_fail = now
                if self._cb_failures >= _CB_FAIL_THRESHOLD:
                    self._cb_state = "OPEN"
            return False

    async def get(self, key: str, db_type: str = "tool") -> Optional[Any]:
        # Try Redis first
        if await self._redis_healthy():
            try:
                val = await self._redis.get(key, db_type)
                if val is not None:
                    return val
            except Exception as e:
                logger.debug("[cache_manager] redis get error: %s", e)

        # Fallback local
        if self._local:
            return self._local.get(key, db_type)
        return None

    async def set(self, key: str, value: Any, db_type: str = "tool",
                  ttl: Optional[int] = None) -> None:
        effective_ttl = ttl or TTL.get(db_type, 600)

        # Always write local first (backup)
        if self._local:
            self._local.set(key, value, db_type, effective_ttl)

        # Then try Redis
        if await self._redis_healthy():
            try:
                await self._redis.set(key, value, db_type, effective_ttl)
            except Exception as e:
                logger.debug("[cache_manager] redis set error: %s", e)

    async def delete(self, key: str, db_type: str = "tool") -> None:
        if self._local:
            self._local.delete(key, db_type)
        if await self._redis_healthy():
            try:
                await self._redis.delete(key, db_type)
            except Exception:
                pass

    # ── Cache key helpers ─────────────────────────────────────────

    @staticmethod
    def search_key(query: str, lang: str = "vi",
                   price_range: str = "", category: str = "") -> str:
        raw = f"{lang}:{query}:{price_range}:{category}"
        return "search:" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def planner_key(query: str) -> str:
        return "planner:" + hashlib.sha256(query.encode()).hexdigest()[:16]

    @staticmethod
    def product_key(product_id: str) -> str:
        return f"product:{product_id}"

    @staticmethod
    def currency_key(from_c: str, to_c: str) -> str:
        return f"currency:{from_c}:{to_c}"

    @staticmethod
    def shipping_key(address: str, total: str = "") -> str:
        raw = f"{address}:{total}"
        return "shipping:" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def recommend_key(product_id: str, limit: int = 5) -> str:
        return f"recommend:{product_id}:{limit}"

    @staticmethod
    def session_key(session_id: str) -> str:
        return f"session:{session_id}"


# Singleton
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
