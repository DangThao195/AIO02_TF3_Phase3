"""
memory/redis_store.py — RedisCacheStore

3 logical DB mapping:
  planner → DB0 (noeviction, 256MB)
  tool    → DB1 (allkeys-lru, 2GB)
  session → DB2 (volatile-ttl, 512MB)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("memory.redis_store")

_DB_MAP = {
    "planner": 0,
    "tool": 1,
    "session": 2,
}


class RedisCacheStore:
    """Redis-backed cache store with logical DB isolation."""

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._clients: dict[int, Any] = {}

    def _get_client(self, db: int) -> Any:
        if db not in self._clients:
            try:
                import redis.asyncio as aioredis
                self._clients[db] = aioredis.from_url(
                    self._redis_url, db=db,
                    encoding="utf-8", decode_responses=True,
                )
            except ImportError:
                raise RuntimeError("redis package not installed: pip install redis")
        return self._clients[db]

    def _db(self, db_type: str) -> int:
        return _DB_MAP.get(db_type, 1)

    async def get(self, key: str, db_type: str = "tool") -> Optional[Any]:
        try:
            client = self._get_client(self._db(db_type))
            raw = await client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.debug("[redis_store] get error key=%s: %s", key, e)
            return None

    async def set(self, key: str, value: Any, db_type: str = "tool", ttl: int = 600) -> None:
        try:
            client = self._get_client(self._db(db_type))
            serialized = json.dumps(value, ensure_ascii=False, default=str)
            if ttl > 0:
                await client.setex(key, ttl, serialized)
            else:
                await client.set(key, serialized)
        except Exception as e:
            logger.debug("[redis_store] set error key=%s: %s", key, e)

    async def delete(self, key: str, db_type: str = "tool") -> None:
        try:
            client = self._get_client(self._db(db_type))
            await client.delete(key)
        except Exception as e:
            logger.debug("[redis_store] delete error key=%s: %s", key, e)

    async def ping(self) -> bool:
        try:
            client = self._get_client(0)
            await client.ping()
            return True
        except Exception:
            return False

    async def invalidate_product(self, product_id: str) -> None:
        """Invalidate product cache + related search/recommend keys."""
        try:
            tool_client = self._get_client(1)
            await tool_client.delete(f"product:{product_id}")
            # Pattern delete for search and recommend
            async for key in tool_client.scan_iter(f"search:*"):
                await tool_client.delete(key)
            async for key in tool_client.scan_iter(f"recommend:{product_id}:*"):
                await tool_client.delete(key)
        except Exception as e:
            logger.warning("[redis_store] invalidate_product error: %s", e)
