"""
memory/store.py — SessionStore và CacheStore cho Shopping Copilot.

Hai class in-memory (dict) với TTL và LRU eviction.
Schema JSON đã được mô tả trong memory/session.json và memory/cache.json.

Trên EKS production: thay thế bằng Valkey (Redis-compatible) client.
"""

import json
import hashlib
import time
import logging
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

logger = logging.getLogger("memory.store")

# ── Config ──
_SESSION_TTL_SECONDS = 1800       # 30 phút không hoạt động → xóa session
_SESSION_MAX_MESSAGES = 20        # Sliding window tối đa 20 messages

_CACHE_MAX_ENTRIES = 500
_CACHE_TTL_MAP = {
    "search_products_tool":     300,   # 5 phút
    "get_product_reviews_tool": 300,   # 5 phút
    "get_recommendations_tool": 300,   # 5 phút
    "convert_currency_tool":     60,   # 1 phút
}
_CACHE_DEFAULT_TTL = 300
_NEVER_CACHE = {"add_to_cart_tool", "get_cart_tool", "get_shipping_quote_tool"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.time()


# ══════════════════════════════════════════════════════════════════
# SessionStore
# ══════════════════════════════════════════════════════════════════

class SessionStore:
    """
    Lưu trữ lịch sử hội thoại per-session trong bộ nhớ (dict).

    Mỗi session chứa:
    - messages: list[{role, content, timestamp}]
    - pending_confirmation: {token, action, action_params, expires_at} | {}
    - metadata: {total_turns, total_tool_calls, last_active_ts}
    """

    def __init__(self):
        self._store: dict[str, dict] = {}

    # ── Public API ──

    def get_or_create(self, session_id: str, user_id: str) -> dict:
        """Lấy session hiện có hoặc tạo mới nếu chưa tồn tại / đã hết hạn."""
        session = self._store.get(session_id)

        if session is None:
            session = self._create(session_id, user_id)
            logger.info("[SESSION] Created new session | id=%s | user=%s", session_id, user_id)
        else:
            # Kiểm tra TTL
            last_active = session["metadata"].get("last_active_ts", 0)
            if _now_ts() - last_active > _SESSION_TTL_SECONDS:
                logger.info("[SESSION] Expired session — reset | id=%s", session_id)
                session = self._create(session_id, user_id)

        return session

    def append_message(self, session_id: str, role: str, content: str,
                       tool_name: Optional[str] = None) -> None:
        """Thêm message vào lịch sử, áp dụng sliding window."""
        session = self._store.get(session_id)
        if session is None:
            return

        session["messages"].append({
            "role": role,
            "content": content,
            "timestamp": _now_iso(),
            "tool_name": tool_name,
        })

        # Sliding window: giữ tối đa _SESSION_MAX_MESSAGES messages gần nhất
        if len(session["messages"]) > _SESSION_MAX_MESSAGES:
            session["messages"] = session["messages"][-_SESSION_MAX_MESSAGES:]

        session["metadata"]["total_turns"] += 1

    def touch(self, session_id: str) -> None:
        """Cập nhật last_active_ts."""
        session = self._store.get(session_id)
        if session:
            session["metadata"]["last_active_ts"] = _now_ts()
            session["last_active"] = _now_iso()

    def set_pending(self, session_id: str, token: str, action: str,
                    action_params: Optional[dict]) -> None:
        """Lưu trạng thái đang chờ xác nhận."""
        session = self._store.get(session_id)
        if session is None:
            return
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
        session["pending_confirmation"] = {
            "token": token,
            "action": action,
            "action_params": action_params or {},
            "expires_at": expires_at,
        }
        logger.info("[SESSION] Pending set | id=%s | action=%s", session_id, action)

    def clear_pending(self, session_id: str) -> None:
        """Xóa trạng thái pending sau khi user xác nhận hoặc huỷ."""
        session = self._store.get(session_id)
        if session:
            session["pending_confirmation"] = {}
            logger.info("[SESSION] Pending cleared | id=%s", session_id)

    def dump(self, session_id: str) -> Optional[dict]:
        """Trả về snapshot JSON-serializable của một session (dùng để debug)."""
        return self._store.get(session_id)

    def dump_all(self) -> dict:
        """Trả về toàn bộ store (dùng để debug / export)."""
        return dict(self._store)

    # ── Private ──

    def _create(self, session_id: str, user_id: str) -> dict:
        session = {
            "user_id": user_id,
            "session_id": session_id,
            "created_at": _now_iso(),
            "last_active": _now_iso(),
            "ttl_seconds": _SESSION_TTL_SECONDS,
            "messages": [],
            "context_window": {
                "max_messages": _SESSION_MAX_MESSAGES,
                "strategy": "sliding_window",
            },
            "pending_confirmation": {},
            "metadata": {
                "total_turns": 0,
                "total_tool_calls": 0,
                "last_active_ts": _now_ts(),
            },
        }
        self._store[session_id] = session
        return session


# ══════════════════════════════════════════════════════════════════
# CacheStore
# ══════════════════════════════════════════════════════════════════

class CacheStore:
    """
    Cache kết quả tool với TTL và LRU eviction.

    Key: "<tool_name>:<sha256(params)[:16]>"
    Chỉ cache read-only tools; write tools bị NEVER_CACHE.
    """

    def __init__(self):
        # OrderedDict để implement LRU (di chuyển entry lên đầu khi hit)
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._stats = {"hits": 0, "misses": 0}

    # ── Public API ──

    def get(self, tool_name: str, params: dict) -> Optional[str]:
        """
        Lấy kết quả cache.
        Returns None nếu miss hoặc tool thuộc NEVER_CACHE.
        """
        if tool_name in _NEVER_CACHE:
            return None

        key = self._make_key(tool_name, params)
        entry = self._store.get(key)

        if entry is None:
            self._stats["misses"] += 1
            return None

        # Kiểm tra TTL
        if _now_ts() > entry["expires_at_ts"]:
            del self._store[key]
            self._stats["misses"] += 1
            logger.debug("[CACHE] TTL expired | key=%s", key)
            return None

        # LRU: di chuyển lên cuối (most-recently-used)
        self._store.move_to_end(key)
        entry["hit_count"] += 1
        self._stats["hits"] += 1
        logger.debug("[CACHE] HIT | key=%s | hits=%d", key, entry["hit_count"])
        return entry["result"]

    def set(self, tool_name: str, params: dict, result: str) -> None:
        """Lưu kết quả vào cache."""
        if tool_name in _NEVER_CACHE:
            return

        key = self._make_key(tool_name, params)
        ttl = _CACHE_TTL_MAP.get(tool_name, _CACHE_DEFAULT_TTL)
        expires_ts = _now_ts() + ttl

        self._store[key] = {
            "tool_name": tool_name,
            "params": params,
            "params_hash": self._hash_params(params),
            "result": result,
            "cached_at": _now_iso(),
            "expires_at_ts": expires_ts,
            "expires_at": datetime.fromtimestamp(expires_ts, timezone.utc).isoformat(),
            "hit_count": 0,
            "source": "grpc",
        }
        self._store.move_to_end(key)

        # LRU eviction khi vượt giới hạn
        while len(self._store) > _CACHE_MAX_ENTRIES:
            evicted_key, _ = self._store.popitem(last=False)
            logger.info("[CACHE] LRU evict | key=%s", evicted_key)

        logger.debug("[CACHE] SET | tool=%s | ttl=%ds", tool_name, ttl)

    def stats(self) -> dict:
        """Trả về thống kê cache."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = round(self._stats["hits"] / total * 100, 1) if total > 0 else 0
        return {
            **self._stats,
            "total_entries": len(self._store),
            "hit_rate_pct": hit_rate,
        }

    def dump(self) -> dict:
        """Snapshot toàn bộ cache (dùng để debug)."""
        return {
            "cache_config": {
                "max_entries": _CACHE_MAX_ENTRIES,
                "eviction_policy": "LRU",
                "enabled_tools": list(_CACHE_TTL_MAP.keys()),
                "never_cache_tools": list(_NEVER_CACHE),
            },
            "entries": {k: {**v, "expires_at_ts": None} for k, v in self._store.items()},
            "stats": self.stats(),
        }

    def get_raw(self, cache_key: str) -> Optional[Any]:
        """
        Get raw cached value by cache key (raw string key, not tool_name/params).
        Used for generic caching (e.g., LLM parse results).
        """
        entry = self._store.get(cache_key)
        if entry is None:
            return None
        
        # Check TTL
        if _now_ts() > entry.get("expires_at_ts", 0):
            del self._store[cache_key]
            return None
        
        # LRU: move to end
        self._store.move_to_end(cache_key)
        entry["hit_count"] = entry.get("hit_count", 0) + 1
        return entry.get("value")

    def set_raw(self, cache_key: str, value: Any, ttl: int = 300) -> None:
        """
        Set raw cached value by cache key with TTL.
        Used for generic caching (e.g., LLM parse results).
        
        Args:
            cache_key: Arbitrary cache key string
            value: Value to cache (typically dict or str)
            ttl: Time-to-live in seconds (default 300s = 5 min)
        """
        expires_ts = _now_ts() + ttl
        self._store[cache_key] = {
            "cache_key": cache_key,
            "value": value,
            "cached_at": _now_iso(),
            "expires_at_ts": expires_ts,
            "expires_at": datetime.fromtimestamp(expires_ts, timezone.utc).isoformat(),
            "hit_count": 0,
            "ttl_seconds": ttl,
        }
        self._store.move_to_end(cache_key)
        
        # LRU eviction
        while len(self._store) > _CACHE_MAX_ENTRIES:
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug("[CACHE] LRU evict raw | key=%s", evicted_key)

    # ── Private ──

    @staticmethod
    def _hash_params(params: dict) -> str:
        serialized = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _make_key(tool_name: str, params: dict) -> str:
        h = CacheStore._hash_params(params)
        return f"{tool_name}:{h[:16]}"
