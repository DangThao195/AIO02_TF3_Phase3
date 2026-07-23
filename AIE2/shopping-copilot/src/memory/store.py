"""
memory/store.py — In-memory SessionStore + CacheStore

CacheStore: OrderedDict LRU, max 500 entries, JSON persist.
Thêm interface get(key, db_type) và set(key, value, db_type, ttl) để
compatible với CacheManager.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger("memory.store")

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "../../data/cache.json")
_SESSION_FILE = os.path.join(os.path.dirname(__file__), "../../data/session.json")
_MAX_CACHE_ENTRIES = 500
_SESSION_TTL = 1800  # 30 minutes


# ── CacheStore ────────────────────────────────────────────────────

class CacheStore:
    """
    In-memory LRU cache with optional JSON persistence.
    Implements get(key, db_type) and set(key, value, db_type, ttl) for
    compatibility with CacheManager.
    """

    def __init__(self, max_size: int = _MAX_CACHE_ENTRIES, persist_path: str = _CACHE_FILE):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size
        self._persist_path = persist_path
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()
        self._load()

    # ── CacheManager-compatible interface ─────────────────────────

    def get(self, key: str, db_type: str = "tool") -> Optional[Any]:
        """Get value by key (db_type ignored for in-memory store)."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.get("expires_at") and time.time() > entry["expires_at"]:
                del self._store[key]
                self._misses += 1
                return None
            # LRU: move to end
            self._store.move_to_end(key)
            self._hits += 1
            return entry.get("value")

    def set(self, key: str, value: Any, db_type: str = "tool", ttl: int = 600) -> None:
        """Set key with TTL (db_type ignored for in-memory store)."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = {
                "value": value,
                "expires_at": time.time() + ttl if ttl > 0 else None,
                "created_at": time.time(),
            }
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def delete(self, key: str, db_type: str = "tool") -> None:
        with self._lock:
            self._store.pop(key, None)

    # ── Legacy interface ──────────────────────────────────────────

    def get_cached(self, key: str) -> Optional[Any]:
        return self.get(key)

    def set_cached(self, key: str, value: Any, ttl: int = 600) -> None:
        self.set(key, value, ttl=ttl)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_entries": len(self._store),
            "hit_rate_pct": round(self._hits / total * 100, 1) if total else 0,
        }

    def dump(self) -> dict:
        return {k: v.get("value") for k, v in self._store.items()}

    def _load(self) -> None:
        try:
            path = os.path.abspath(self._persist_path)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    now = time.time()
                    for k, v in data.items():
                        if isinstance(v, dict) and v.get("expires_at", now + 1) > now:
                            self._store[k] = v
        except Exception as e:
            logger.warning("[CacheStore] _load failed: %s", e)

    def persist(self) -> None:
        try:
            path = os.path.abspath(self._persist_path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dict(self._store), f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[CacheStore] persist failed: %s", e)


# ── SessionStore ──────────────────────────────────────────────────

class SessionStore:
    """In-memory session store with TTL and sliding window (20 messages)."""

    def __init__(self, ttl: int = _SESSION_TTL, persist_path: str = _SESSION_FILE):
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl
        self._persist_path = persist_path
        self._lock = threading.Lock()
        self._load()

    def get(self, session_id: str) -> Optional[dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if time.time() - session.get("last_active", 0) > self._ttl:
                del self._sessions[session_id]
                return None
            session["last_active"] = time.time()
            return session

    def create(self, session_id: str, user_id: str) -> dict:
        session = {
            "session_id": session_id,
            "user_id": user_id,
            "messages": [],
            "created_at": time.time(),
            "last_active": time.time(),
            "pending_confirmation": {},
        }
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get_or_create(self, session_id: str, user_id: str) -> dict:
        session = self.get(session_id)
        if session is None:
            session = self.create(session_id, user_id)
        return session

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["messages"].append({"role": role, "content": content})
                if len(session["messages"]) > 20:
                    session["messages"] = session["messages"][-20:]
                session["last_active"] = time.time()

    def set_pending(self, session_id: str, token: str, action: str, params: dict) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["pending_confirmation"] = {
                    "token": token, "action": action, "params": params,
                    "expires_at": time.time() + 300,
                }

    def clear_pending(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["pending_confirmation"] = {}

    def dump(self, session_id: str) -> Optional[dict]:
        with self._lock:
            return self._sessions.get(session_id)

    def _load(self) -> None:
        try:
            path = os.path.abspath(self._persist_path)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._sessions = json.load(f)
        except Exception as e:
            logger.warning("[SessionStore] _load failed: %s", e)

    def persist(self) -> None:
        try:
            path = os.path.abspath(self._persist_path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._sessions, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[SessionStore] persist failed: %s", e)
