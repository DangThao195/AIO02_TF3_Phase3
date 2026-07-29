"""
memory/longterm_memory.py — Long-term Memory Store cho MANDATE #23

Lưu trữ thông tin người dùng bền vững qua các phiên (cross-session):
- User Preferences (sở thích, yêu cầu đặc biệt)
- User Facts (thông tin cá nhân đã chia sẻ)
- Purchase History (sản phẩm đã mua/quan tâm)
- Conversation Patterns (các chủ đề thường hỏi)

Key Format: copilot:user:{user_id}:memory
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))

logger = logging.getLogger("memory.longterm")

# ── Config ──
_LONGTERM_TTL = 30 * 24 * 3600  # 30 ngày (dữ liệu bền vững hơn session)
_MAX_FACTS_PER_USER = 50
_MAX_PREFERENCES_PER_USER = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════
# Redis connection helper (shared)
# ══════════════════════════════════════════════════════════════════

_redis_client = None


def _get_redis():
    """Trả về Redis client nếu VALKEY_URL được cấu hình."""
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
            logger.info("[LONGTERM] Valkey connected: %s", valkey_url)
        except Exception as e:
            strict = os.environ.get("STRICT_VALKEY", "true").lower() in ("true", "1", "yes")
            if strict:
                logger.error("[LONGTERM] CRITICAL: Valkey connection failed: %s | Strict Production Mode: No local file fallback!", e)
                raise RuntimeError(f"[LONGTERM] Strict Valkey connection failed ({valkey_url}): {e}")
            else:
                logger.warning("[LONGTERM] Valkey connection failed: %s — falling back to file JSON", e)
                _redis_client = None

    return _redis_client


# ══════════════════════════════════════════════════════════════════
# LongTermMemoryStore
# ══════════════════════════════════════════════════════════════════


class LongTermMemoryStore:
    """
    Lưu trữ thông tin người dùng bền vững xuyên phiên.

    Structure per user:
    {
        "user_id": str,
        "created_at": str,
        "updated_at": str,
        "preferences": [
            {"type": "budget", "value": "under 100 USD", "confidence": 0.8, "updated_at": str},
            {"type": "category", "value": "telescopes", "confidence": 0.9, "updated_at": str},
        ],
        "facts": [
            {"fact": "lives in Vietnam", "confidence": 0.7, "extracted_at": str},
            {"fact": "interested in astronomy", "confidence": 0.9, "extracted_at": str},
        ],
        "purchase_history": [
            {"product_id": "OLJCESPC7Z", "product_name": "...", "timestamp": str},
        ],
        "interaction_summary": {
            "total_sessions": int,
            "total_messages": int,
            "common_topics": ["telescopes", "binoculars"],
            "last_interaction": str,
        }
    }

    Backend tự động:
      - Valkey (nếu VALKEY_URL set): key = copilot:user:{user_id}:memory
      - File JSON (nếu không có): data/longterm_memory.json
    """

    _KEY_PREFIX = "copilot:user:"
    _KEY_SUFFIX = ":memory"

    def __init__(self, filepath: Optional[str] = None):
        self._filepath = filepath or os.path.join(_BASE_DIR, "longterm_memory.json")
        self._store: Dict[str, Dict[str, Any]] = {}

        if _get_redis() is None:
            self._load()

    # ── Private: Key generation ──

    def _make_key(self, user_id: str) -> str:
        return f"{self._KEY_PREFIX}{user_id}{self._KEY_SUFFIX}"

    # ── Private: Valkey backend ──

    def _vget(self, user_id: str) -> Optional[Dict[str, Any]]:
        r = _get_redis()
        if r is None:
            return self._store.get(user_id)

        try:
            raw = r.get(self._make_key(user_id))
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug("[LONGTERM] Valkey get error: %s", e)
            return None

    def _vset(self, user_id: str, memory: Dict[str, Any]) -> None:
        r = _get_redis()
        if r is None:
            self._store[user_id] = memory
            self._save()
            return

        try:
            r.setex(
                self._make_key(user_id),
                _LONGTERM_TTL,
                json.dumps(memory, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("[LONGTERM] Valkey set error: %s", e)

    # ── Private: File backend ──

    def _load(self) -> None:
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._store = data
                    logger.info(
                        "[LONGTERM] Loaded %d user memories from %s",
                        len(self._store),
                        self._filepath,
                    )
        except Exception as e:
            logger.warning("[LONGTERM] Load failed — starting fresh: %s", e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            tmp = self._filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._store, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._filepath)
        except Exception as e:
            logger.error("[LONGTERM] Save failed: %s", e)

    # ── Public API ──

    def get_or_create(self, user_id: str) -> Dict[str, Any]:
        """Lấy hoặc tạo mới long-term memory cho user."""
        memory = self._vget(user_id)

        if memory is None:
            memory = self._create_empty(user_id)
            self._vset(user_id, memory)
            logger.info("[LONGTERM] Created new memory | user=%s", user_id)

        return memory

    def add_preference(
        self, user_id: str, pref_type: str, value: str, confidence: float = 0.8
    ) -> None:
        """
        Thêm hoặc cập nhật một preference.

        Args:
            user_id: User ID
            pref_type: Loại preference (budget, category, brand, color, etc.)
            value: Giá trị preference
            confidence: Độ tin cậy (0.0 - 1.0)
        """
        memory = self.get_or_create(user_id)

        # Check if preference exists → update
        existing = None
        for pref in memory["preferences"]:
            if pref["type"] == pref_type and pref["value"] == value:
                existing = pref
                break

        if existing:
            existing["confidence"] = max(existing["confidence"], confidence)
            existing["updated_at"] = _now_iso()
        else:
            memory["preferences"].append(
                {
                    "type": pref_type,
                    "value": value,
                    "confidence": confidence,
                    "updated_at": _now_iso(),
                }
            )

        # Limit size
        if len(memory["preferences"]) > _MAX_PREFERENCES_PER_USER:
            # Sort by confidence, keep top N
            memory["preferences"].sort(key=lambda x: x["confidence"], reverse=True)
            memory["preferences"] = memory["preferences"][:_MAX_PREFERENCES_PER_USER]

        memory["updated_at"] = _now_iso()
        self._vset(user_id, memory)
        logger.info(
            "[LONGTERM] Added preference | user=%s | %s=%s (conf=%.2f)",
            user_id,
            pref_type,
            value,
            confidence,
        )

    def add_fact(self, user_id: str, fact: str, confidence: float = 0.7) -> None:
        """
        Thêm một fact về user.

        Args:
            user_id: User ID
            fact: Thông tin thực tế (e.g., "lives in Hanoi", "has 2 kids")
            confidence: Độ tin cậy
        """
        memory = self.get_or_create(user_id)

        # Check duplicate
        for existing_fact in memory["facts"]:
            if existing_fact["fact"].lower() == fact.lower():
                existing_fact["confidence"] = max(
                    existing_fact["confidence"], confidence
                )
                existing_fact["extracted_at"] = _now_iso()
                memory["updated_at"] = _now_iso()
                self._vset(user_id, memory)
                return

        memory["facts"].append(
            {
                "fact": fact,
                "confidence": confidence,
                "extracted_at": _now_iso(),
            }
        )

        # Limit size
        if len(memory["facts"]) > _MAX_FACTS_PER_USER:
            memory["facts"].sort(key=lambda x: x["confidence"], reverse=True)
            memory["facts"] = memory["facts"][:_MAX_FACTS_PER_USER]

        memory["updated_at"] = _now_iso()
        self._vset(user_id, memory)
        logger.info(
            "[LONGTERM] Added fact | user=%s | fact=%s (conf=%.2f)",
            user_id,
            fact[:50],
            confidence,
        )

    def add_purchase(self, user_id: str, product_id: str, product_name: str) -> None:
        """Ghi nhận lịch sử mua hàng."""
        memory = self.get_or_create(user_id)

        memory["purchase_history"].append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "timestamp": _now_iso(),
            }
        )

        # Keep only last 20 purchases
        if len(memory["purchase_history"]) > 20:
            memory["purchase_history"] = memory["purchase_history"][-20:]

        memory["updated_at"] = _now_iso()
        self._vset(user_id, memory)
        logger.info(
            "[LONGTERM] Added purchase | user=%s | product=%s", user_id, product_id
        )

    def update_interaction_summary(
        self, user_id: str, topics: Optional[List[str]] = None
    ) -> None:
        """Cập nhật thống kê tương tác."""
        memory = self.get_or_create(user_id)

        summary = memory["interaction_summary"]
        summary["total_sessions"] += 1
        summary["total_messages"] += 1
        summary["last_interaction"] = _now_iso()

        if topics:
            # Update common topics
            for topic in topics:
                if topic not in summary["common_topics"]:
                    summary["common_topics"].append(topic)
            # Keep top 10
            if len(summary["common_topics"]) > 10:
                summary["common_topics"] = summary["common_topics"][:10]

        memory["updated_at"] = _now_iso()
        self._vset(user_id, memory)

    def get_context_summary(self, user_id: str) -> str:
        """
        Tạo chuỗi tóm tắt long-term memory để inject vào System Prompt.

        Returns:
            Formatted string suitable for LLM context
        """
        memory = self._vget(user_id)
        if not memory:
            return ""

        lines = []

        # Preferences
        if memory["preferences"]:
            prefs = [f"{p['type']}={p['value']}" for p in memory["preferences"][:5]]
            lines.append(f"User Preferences: {', '.join(prefs)}")

        # Facts
        if memory["facts"]:
            facts = [f["fact"] for f in memory["facts"][:3]]
            lines.append(f"User Facts: {'; '.join(facts)}")

        # Purchase history
        if memory["purchase_history"]:
            recent = memory["purchase_history"][-3:]
            products = [p["product_name"] for p in recent]
            lines.append(f"Recent Purchases: {', '.join(products)}")

        # Interaction summary
        summary = memory["interaction_summary"]
        if summary["common_topics"]:
            topics = ", ".join(summary["common_topics"][:5])
            lines.append(f"Common Topics: {topics}")

        if not lines:
            return ""

        return "[User Memory]\n" + "\n".join(lines)

    def dump(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Trả về snapshot JSON-serializable của user memory (debug)."""
        return self._vget(user_id)

    def dump_all(self) -> Dict[str, Dict[str, Any]]:
        """Trả về toàn bộ store (chỉ hỗ trợ đầy đủ với file backend)."""
        return dict(self._store)

    def stats(self) -> Dict[str, Any]:
        """Thống kê tổng quan."""
        return {
            "total_users": len(self._store),
            "backend": "valkey" if _get_redis() is not None else "file",
            "ttl_days": _LONGTERM_TTL // (24 * 3600),
        }

    # ── Private ──

    def _create_empty(self, user_id: str) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "preferences": [],
            "facts": [],
            "purchase_history": [],
            "interaction_summary": {
                "total_sessions": 0,
                "total_messages": 0,
                "common_topics": [],
                "last_interaction": _now_iso(),
            },
        }


# ══════════════════════════════════════════════════════════════════
# Singleton instance
# ══════════════════════════════════════════════════════════════════

_longterm_store = None


def get_longterm_memory_store() -> LongTermMemoryStore:
    """Singleton accessor cho LongTermMemoryStore."""
    global _longterm_store
    if _longterm_store is None:
        _longterm_store = LongTermMemoryStore()
    return _longterm_store
