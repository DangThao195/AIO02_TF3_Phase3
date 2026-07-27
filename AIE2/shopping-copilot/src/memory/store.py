"""
memory/store.py — In-memory SessionStore + CacheStore

CacheStore: OrderedDict LRU, max 500 entries, JSON persist with debounce.
SessionStore: In-memory session with background file persistence.
"""

from __future__ import annotations

import atexit
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
_PERSIST_INTERVAL = 30  # seconds
_DEBOUNCE_DELAY = 5  # seconds


# ── Helpers ────────────────────────────────────────────────────────

def _resolve_path(rel_path: str) -> str:
    path = os.path.abspath(rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _register_shutdown(persist_fn):
    atexit.register(persist_fn)


# ── DebounceTimer ──────────────────────────────────────────────────

class _DebounceTimer:
    """Calls a function after `delay` seconds of inactivity."""

    def __init__(self, delay: float, callback):
        self._delay = delay
        self._callback = callback
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def poke(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._callback)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None


# ── CacheStore ────────────────────────────────────────────────────

class CacheStore:
    """
    In-memory LRU cache with debounced JSON persistence.

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
        self._dirty = False
        self._debounce = _DebounceTimer(_DEBOUNCE_DELAY, self._flush)
        _register_shutdown(self.persist)
        self._load()

    # ── CacheManager-compatible interface ─────────────────────────

    def get(self, key: str, db_type: str = "tool") -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.get("expires_at") and time.time() > entry["expires_at"]:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return entry.get("value")

    def set(self, key: str, value: Any, db_type: str = "tool", ttl: int = 600) -> None:
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
            self._dirty = True
        self._debounce.poke()

    def delete(self, key: str, db_type: str = "tool") -> None:
        with self._lock:
            self._store.pop(key, None)
            self._dirty = True
        self._debounce.poke()

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

    def _flush(self):
        """Called by debounce timer — persist only if dirty."""
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
        self.persist()

    def persist(self) -> None:
        try:
            path = _resolve_path(self._persist_path)
            with self._lock:
                data = dict(self._store)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[CacheStore] persist failed: %s", e)


# ── SessionStore ──────────────────────────────────────────────────

class SessionStore:
    """In-memory session store with TTL, sliding window, and background file persistence."""

    def __init__(self, ttl: int = _SESSION_TTL, persist_path: str = _SESSION_FILE):
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl
        self._persist_path = persist_path
        self._lock = threading.Lock()
        self._dirty = False
        self._load()
        _register_shutdown(self.persist)
        self._start_background_persist()

    def _start_background_persist(self):
        """Periodic persist every _PERSIST_INTERVAL seconds."""
        def _loop():
            while True:
                time.sleep(_PERSIST_INTERVAL)
                self._flush()
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def get(self, session_id: str) -> Optional[dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if time.time() - session.get("last_active", 0) > self._ttl:
                del self._sessions[session_id]
                self._dirty = True
                return None
            session["last_active"] = time.time()
            return session

    def create(self, session_id: str, user_id: str) -> dict:
        session = {
            "session_id": session_id,
            "user_id": user_id,
            "messages": [],
            "planner_memory": {},
            "created_at": time.time(),
            "last_active": time.time(),
            "pending_confirmation": {},
        }
        with self._lock:
            self._sessions[session_id] = session
            self._dirty = True
        return session

    def get_or_create(self, session_id: str, user_id: str) -> dict:
        session = self.get(session_id)
        if session is None:
            session = self.create(session_id, user_id)
        return session

    def add_message(self, session_id: str, role: str, content: str, metadata: dict | None = None) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                msg = {"role": role, "content": content}
                if metadata:
                    msg["metadata"] = metadata
                session["messages"].append(msg)
                if len(session["messages"]) > 20:
                    session["messages"] = session["messages"][-20:]
                session["last_active"] = time.time()
                self._dirty = True

    def get_messages(self, session_id: str) -> list[dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                return list(session.get("messages", []))
            return []

    def update_planner_memory(self, session_id: str, memory: dict) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session and memory:
                session["planner_memory"] = dict(memory)
                session["last_active"] = time.time()
                self._dirty = True

    def set_pending(self, session_id: str, token: str, action: str, params: dict) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["pending_confirmation"] = {
                    "token": token, "action": action, "params": params,
                    "expires_at": time.time() + 300,
                }
                self._dirty = True

    def get_pending(self, session_id: str) -> Optional[dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            pending = session.get("pending_confirmation", {})
            if not pending:
                return None
            if time.time() > pending.get("expires_at", 0):
                session["pending_confirmation"] = {}
                self._dirty = True
                return None
            return dict(pending)

    def clear_pending(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["pending_confirmation"] = {}
                self._dirty = True

    def dump(self, session_id: str) -> Optional[dict]:
        with self._lock:
            return self._sessions.get(session_id)

    def get_all_sessions(self, limit: int = 50) -> dict[str, dict]:
        with self._lock:
            now = time.time()
            active = {}
            for sid, s in list(self._sessions.items()):
                if now - s.get("last_active", 0) <= self._ttl:
                    active[sid] = dict(s)
                    if len(active) >= limit:
                        break
            return active

    def _load(self) -> None:
        try:
            path = os.path.abspath(self._persist_path)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        now = time.time()
                        for sid, s in list(data.items()):
                            if isinstance(s, dict) and now - s.get("last_active", 0) <= self._ttl:
                                self._sessions[sid] = s
        except Exception as e:
            logger.warning("[SessionStore] _load failed: %s", e)

    def _flush(self):
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
        self.persist()

    def persist(self) -> None:
        try:
            path = _resolve_path(self._persist_path)
            with self._lock:
                data = dict(self._sessions)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[SessionStore] persist failed: %s", e)


# ── Singletons ─────────────────────────────────────────────────────

_cache_store: Optional[CacheStore] = None
_session_store: Optional[SessionStore] = None
_singleton_lock = threading.Lock()


def get_cache_store() -> CacheStore:
    global _cache_store
    if _cache_store is None:
        with _singleton_lock:
            if _cache_store is None:
                _cache_store = CacheStore()
    return _cache_store


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        with _singleton_lock:
            if _session_store is None:
                _session_store = SessionStore()
    return _session_store
