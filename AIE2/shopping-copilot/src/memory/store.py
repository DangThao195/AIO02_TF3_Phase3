"""
memory/store.py — SessionStore và CacheStore cho Shopping Copilot.

Hỗ trợ 2 backend (tự động chọn qua env var VALKEY_URL):
  - [Production] Valkey/Redis  : VALKEY_URL được set → dùng Redis client
                                  Key namespace: copilot:session:*, copilot:cache:*, copilot:raw:*
                                  TTL được quản lý bởi Redis EXPIRE → tự dọn dẹp
  - [Dev Local]  File JSON     : VALKEY_URL không set → ghi vào data/session.json, data/cache.json
                                  Behavior giống hệt như trước

Trên EKS production: set VALKEY_URL=redis://valkey-cart.techx-tf3.svc.cluster.local:6379/1
  (dùng DB=1 để tránh xung đột với Cart service đang dùng DB=0)
"""

import json
import os
import hashlib
import time
import logging
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))

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
# Valkey/Redis connection helper
# ══════════════════════════════════════════════════════════════════

_redis_client = None

def _get_redis():
    """
    Trả về Redis client nếu VALKEY_URL được cấu hình, ngược lại trả None.
    Kết nối lazy (tạo lần đầu khi dùng, tái sử dụng sau đó).
    """
    global _redis_client
    valkey_url = os.environ.get("VALKEY_URL", "")
    if not valkey_url:
        return None

    if _redis_client is None:
        try:
            import redis as redis_lib
            _redis_client = redis_lib.Redis.from_url(
                valkey_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=2,
                retry_on_timeout=True,
            )
            _redis_client.ping()
            logger.info("[STORE] Valkey connected: %s", valkey_url)
        except Exception as e:
            logger.error("[STORE] Valkey connection failed: %s — falling back to file JSON", e)
            _redis_client = None

    return _redis_client


# ══════════════════════════════════════════════════════════════════
# SessionStore
# ══════════════════════════════════════════════════════════════════

class SessionStore:
    """
    Lưu trữ lịch sử hội thoại per-session.

    Backend tự động:
      - Valkey  (nếu VALKEY_URL set): key = copilot:session:{session_id}, TTL = 1800s
      - File JSON (nếu không có):     data/session.json

    Mỗi session chứa:
    - messages: list[{role, content, timestamp}]
    - pending_confirmation: {token, action, action_params, expires_at} | {}
    - metadata: {total_turns, total_tool_calls, last_active_ts}
    """

    _KEY_PREFIX = "copilot:session:"

    def __init__(self, filepath: Optional[str] = None):
        self._filepath = filepath or os.path.join(_BASE_DIR, "session.json")
        # File backend: in-memory dict
        self._store: dict[str, dict] = {}
        # Khởi tạo file backend nếu không có Valkey
        if _get_redis() is None:
            self._load()

    # ── Private: Valkey backend ──

    def _vkey(self, session_id: str) -> str:
        return f"{self._KEY_PREFIX}{session_id}"

    def _vget(self, session_id: str) -> Optional[dict]:
        r = _get_redis()
        if r is None:
            return self._store.get(session_id)
        try:
            raw = r.get(self._vkey(session_id))
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("[SESSION] Valkey get error: %s", e)
            return None

    def _vset(self, session_id: str, session: dict) -> None:
        r = _get_redis()
        if r is None:
            self._store[session_id] = session
            self._save()
            return
        try:
            r.setex(
                self._vkey(session_id),
                _SESSION_TTL_SECONDS,
                json.dumps(session, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("[SESSION] Valkey set error: %s", e)

    def _vrefresh_ttl(self, session_id: str) -> None:
        """Gia hạn TTL mỗi khi session được sử dụng."""
        r = _get_redis()
        if r:
            try:
                r.expire(self._vkey(session_id), _SESSION_TTL_SECONDS)
            except Exception:
                pass

    # ── Private: File backend ──

    def _load(self) -> None:
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._store = data
                    logger.info("[SESSION] Loaded %d sessions from %s", len(self._store), self._filepath)
        except Exception as e:
            logger.warning("[SESSION] Load failed — starting fresh: %s", e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            tmp = self._filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._store, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._filepath)
        except Exception as e:
            logger.error("[SESSION] Save failed: %s", e)

    # ── Public API (giống hệt trước) ──

    def get_or_create(self, session_id: str, user_id: str) -> dict:
        """Lấy session hiện có hoặc tạo mới nếu chưa tồn tại / đã hết hạn."""
        session = self._vget(session_id)

        if session is None:
            session = self._create(session_id, user_id)
            self._vset(session_id, session)
            logger.info("[SESSION] Created new session | id=%s | user=%s | backend=%s",
                        session_id, user_id, "valkey" if _get_redis() else "file")
        else:
            # File backend: kiểm tra TTL thủ công (Valkey tự xử lý bằng EXPIRE)
            if _get_redis() is None:
                last_active = session["metadata"].get("last_active_ts", 0)
                if _now_ts() - last_active > _SESSION_TTL_SECONDS:
                    logger.info("[SESSION] Expired session — reset | id=%s", session_id)
                    session = self._create(session_id, user_id)
                    self._vset(session_id, session)
            else:
                self._vrefresh_ttl(session_id)

        return session

    def append_message(self, session_id: str, role: str, content: str,
                       tool_name: Optional[str] = None) -> None:
        """Thêm message vào lịch sử, áp dụng sliding window."""
        session = self._vget(session_id)
        if session is None:
            return

        session["messages"].append({
            "role": role,
            "content": content,
            "timestamp": _now_iso(),
            "tool_name": tool_name,
        })

        # Sliding window
        if len(session["messages"]) > _SESSION_MAX_MESSAGES:
            session["messages"] = session["messages"][-_SESSION_MAX_MESSAGES:]

        session["metadata"]["total_turns"] += 1
        self._vset(session_id, session)

    def touch(self, session_id: str) -> None:
        """Cập nhật last_active_ts."""
        session = self._vget(session_id)
        if session:
            session["metadata"]["last_active_ts"] = _now_ts()
            session["last_active"] = _now_iso()
            self._vset(session_id, session)

    def set_pending(self, session_id: str, token: str, action: str,
                    action_params: Optional[dict]) -> None:
        """Lưu trạng thái đang chờ xác nhận."""
        session = self._vget(session_id)
        if session is None:
            return
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
        session["pending_confirmation"] = {
            "token": token,
            "action": action,
            "action_params": action_params or {},
            "expires_at": expires_at,
        }
        self._vset(session_id, session)
        logger.info("[SESSION] Pending set | id=%s | action=%s", session_id, action)

    def clear_pending(self, session_id: str) -> None:
        """Xóa trạng thái pending sau khi user xác nhận hoặc huỷ."""
        session = self._vget(session_id)
        if session:
            session["pending_confirmation"] = {}
            self._vset(session_id, session)
            logger.info("[SESSION] Pending cleared | id=%s", session_id)

    def dump(self, session_id: str) -> Optional[dict]:
        """Trả về snapshot JSON-serializable của một session (dùng để debug)."""
        return self._vget(session_id)

    def dump_all(self) -> dict:
        """Trả về toàn bộ store (chỉ hỗ trợ đầy đủ với file backend)."""
        return dict(self._store)

    def get_recent_history_str(self, session_id: str, limit: int = 3) -> str:
        """Lấy chuỗi lịch sử hội thoại gần nhất (không chứa system/tool)."""
        try:
            session = self._vget(session_id)
            if not session or not session.get("messages"):
                return "No history."

            recent_msgs = []
            for msg in reversed(session["messages"]):
                if msg.get("role") in ["user", "assistant"]:
                    content = msg.get("content") or ""
                    recent_msgs.insert(0, f"{msg['role'].upper()}: {content}")
                if len(recent_msgs) >= limit:
                    break

            return "\n".join(recent_msgs) if recent_msgs else "No history."
        except Exception as e:
            logger.warning("[SESSION] get_recent_history_str failed: %s", e)
            return "No history."

    # ── Private ──

    def _create(self, session_id: str, user_id: str) -> dict:
        return {
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


# ══════════════════════════════════════════════════════════════════
# CacheStore
# ══════════════════════════════════════════════════════════════════

class CacheStore:
    """
    Cache kết quả tool với TTL và LRU eviction.

    Backend tự động:
      - Valkey  (nếu VALKEY_URL set): key = copilot:cache:{key}, TTL via Redis EXPIRE
                                       key = copilot:raw:{key}  cho raw cache
      - File JSON (nếu không có):     data/cache.json với OrderedDict LRU

    Key: "<tool_name>:<sha256(params)[:16]>"
    Chỉ cache read-only tools; write tools bị NEVER_CACHE.
    """

    _CACHE_PREFIX = "copilot:cache:"
    _RAW_PREFIX   = "copilot:raw:"

    def __init__(self, filepath: Optional[str] = None):
        self._filepath = filepath or os.path.join(_BASE_DIR, "cache.json")
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._stats = {"hits": 0, "misses": 0}
        if _get_redis() is None:
            self._load()

    # ── Private: Valkey backend ──

    def _ckey(self, key: str) -> str:
        return f"{self._CACHE_PREFIX}{key}"

    def _rkey(self, key: str) -> str:
        return f"{self._RAW_PREFIX}{key}"

    def _vget_cache(self, redis_key: str) -> Optional[dict]:
        r = _get_redis()
        if r is None:
            return None
        try:
            raw = r.get(redis_key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug("[CACHE] Valkey get error: %s", e)
            return None

    def _vset_cache(self, redis_key: str, value: dict, ttl: int) -> None:
        r = _get_redis()
        if r is None:
            return
        try:
            r.setex(redis_key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            logger.debug("[CACHE] Valkey set error: %s", e)

    # ── Private: File backend ──

    def _load(self) -> None:
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._store = OrderedDict(data.get("entries", data))
                    self._stats = data.get("stats", {"hits": 0, "misses": 0})
                    logger.info("[CACHE] Loaded %d entries from %s", len(self._store), self._filepath)
        except Exception as e:
            logger.warning("[CACHE] Load failed — starting fresh: %s", e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            tmp = self._filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "entries": dict(self._store),
                    "stats": dict(self._stats),
                }, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._filepath)
        except Exception as e:
            logger.error("[CACHE] Save failed: %s", e)

    # ── Public API (giống hệt trước) ──

    def get(self, tool_name: str, params: dict) -> Optional[str]:
        """Lấy kết quả cache. Returns None nếu miss hoặc tool thuộc NEVER_CACHE."""
        if tool_name in _NEVER_CACHE:
            return None

        key = self._make_key(tool_name, params)

        # Valkey backend
        if _get_redis() is not None:
            entry = self._vget_cache(self._ckey(key))
            if entry is None:
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            logger.debug("[CACHE] HIT (valkey) | key=%s", key)
            return entry.get("result")

        # File backend
        entry = self._store.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        if _now_ts() > entry["expires_at_ts"]:
            del self._store[key]
            self._stats["misses"] += 1
            self._save()
            return None

        self._store.move_to_end(key)
        entry["hit_count"] += 1
        self._stats["hits"] += 1
        return entry["result"]

    def set(self, tool_name: str, params: dict, result: str) -> None:
        """Lưu kết quả vào cache."""
        if tool_name in _NEVER_CACHE:
            return

        key = self._make_key(tool_name, params)
        ttl = _CACHE_TTL_MAP.get(tool_name, _CACHE_DEFAULT_TTL)

        entry = {
            "tool_name": tool_name,
            "params": params,
            "params_hash": self._hash_params(params),
            "result": result,
            "cached_at": _now_iso(),
            "hit_count": 0,
            "source": "grpc",
        }

        # Valkey backend
        if _get_redis() is not None:
            self._vset_cache(self._ckey(key), entry, ttl)
            logger.debug("[CACHE] SET (valkey) | tool=%s | ttl=%ds", tool_name, ttl)
            return

        # File backend
        expires_ts = _now_ts() + ttl
        entry["expires_at_ts"] = expires_ts
        entry["expires_at"] = datetime.fromtimestamp(expires_ts, timezone.utc).isoformat()

        self._store[key] = entry
        self._store.move_to_end(key)

        while len(self._store) > _CACHE_MAX_ENTRIES:
            evicted_key, _ = self._store.popitem(last=False)
            logger.info("[CACHE] LRU evict | key=%s", evicted_key)

        self._save()

    def get_raw(self, cache_key: str) -> Optional[Any]:
        """Get raw cached value (dùng cho LLM parse results)."""
        # Valkey backend
        if _get_redis() is not None:
            entry = self._vget_cache(self._rkey(cache_key))
            return entry.get("value") if entry else None

        # File backend
        entry = self._store.get(cache_key)
        if entry is None:
            return None
        if _now_ts() > entry.get("expires_at_ts", 0):
            del self._store[cache_key]
            self._save()
            return None
        self._store.move_to_end(cache_key)
        entry["hit_count"] = entry.get("hit_count", 0) + 1
        return entry.get("value")

    def set_raw(self, cache_key: str, value: Any, ttl: int = 300) -> None:
        """Set raw cached value (dùng cho LLM parse results)."""
        entry = {
            "cache_key": cache_key,
            "value": value,
            "cached_at": _now_iso(),
            "hit_count": 0,
            "ttl_seconds": ttl,
        }

        # Valkey backend
        if _get_redis() is not None:
            self._vset_cache(self._rkey(cache_key), entry, ttl)
            return

        # File backend
        expires_ts = _now_ts() + ttl
        entry["expires_at_ts"] = expires_ts
        entry["expires_at"] = datetime.fromtimestamp(expires_ts, timezone.utc).isoformat()

        self._store[cache_key] = entry
        self._store.move_to_end(cache_key)

        while len(self._store) > _CACHE_MAX_ENTRIES:
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug("[CACHE] LRU evict raw | key=%s", evicted_key)

        self._save()

    def stats(self) -> dict:
        """Trả về thống kê cache."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = round(self._stats["hits"] / total * 100, 1) if total > 0 else 0
        return {
            **self._stats,
            "total_entries": len(self._store),
            "hit_rate_pct": hit_rate,
            "backend": "valkey" if _get_redis() is not None else "file",
        }

    def dump(self) -> dict:
        """Snapshot toàn bộ cache (dùng để debug)."""
        return {
            "cache_config": {
                "max_entries": _CACHE_MAX_ENTRIES,
                "eviction_policy": "LRU (file) / TTL (valkey)",
                "backend": "valkey" if _get_redis() is not None else "file",
                "enabled_tools": list(_CACHE_TTL_MAP.keys()),
                "never_cache_tools": list(_NEVER_CACHE),
            },
            "entries": {k: {**v, "expires_at_ts": None} for k, v in self._store.items()},
            "stats": self.stats(),
        }

    # ── Private ──

    @staticmethod
    def _hash_params(params: dict) -> str:
        serialized = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _make_key(tool_name: str, params: dict) -> str:
        h = CacheStore._hash_params(params)
        return f"{tool_name}:{h[:16]}"
