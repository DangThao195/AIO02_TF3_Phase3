"""
memory/genai_cache.py — GenAI Response Cache Layer cho MANDATE #23

Cache toàn bộ LLM response ở tầng Post-Guardrail với 3 tầng lookup:

  Tier 1 — Rule-based Exact Match (0ms):
      Normalize text → SHA256 hash → O(1) Valkey GET
      Tận dụng rule-base để chuẩn hóa các câu đồng nghĩa sang canonical form
      trước khi hash, giúp exact match phủ được phần lớn request lặp lại.

  Tier 2 — Titan Semantic Similarity (~30ms):
      Khi Tier 1 miss → gọi Amazon Titan Text Embeddings V2 để embed query
      Cosine similarity ≥ threshold (mặc định 0.88) → Semantic Cache HIT
      Schema version guard: reject hit nếu cached entry có schema_version cũ.

  Tier 3 — LLM Call (Pass-through):
      Khi cả 2 tier đều miss → gọi LLM → lưu response + embedding vào cache.

Key Format: copilot:genai:{user_id}:{request_hash}
Emb Index : copilot:genai:emb:{user_id}  (Redis Hash: cache_key -> emb_meta JSON)
"""

import json
import os
import hashlib
import time
import math
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from collections import OrderedDict

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))

logger = logging.getLogger("memory.genai_cache")

# ── Config ──
_GENAI_CACHE_TTL = 600  # 10 phút mặc định
_GENAI_CACHE_MAX_ENTRIES = 1000  # LRU limit cho file backend
_SEMANTIC_SIMILARITY_THRESHOLD = float(
    os.environ.get("SEMANTIC_CACHE_THRESHOLD", "0.88")
)
# Schema version: bump khi product catalog thay đổi → auto-invalidate stale semantic hits
_CACHE_SCHEMA_VERSION: int = int(os.environ.get("CACHE_SCHEMA_VERSION", "1"))
# Enable/disable Titan semantic cache (default enabled)
_TITAN_SEMANTIC_ENABLED = os.environ.get("TITAN_SEMANTIC_CACHE", "true").lower() in (
    "true",
    "1",
    "yes",
)
# Titan model ID
_TITAN_EMBED_MODEL = "amazon.titan-embed-text-v2:0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.time()


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Tính cosine similarity giữa 2 vector embedding (pure Python, không cần numpy)."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot / (mag1 * mag2)


# ══════════════════════════════════════════════════════════════════
# Valkey/Redis connection helper (shared)
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
            logger.info("[GENAI_CACHE] Valkey connected: %s", valkey_url)
        except Exception as e:
            strict = os.environ.get("STRICT_VALKEY", "true").lower() in (
                "true",
                "1",
                "yes",
            )
            if strict:
                logger.error(
                    "[GENAI_CACHE] CRITICAL: Valkey connection failed: %s | "
                    "Strict Production Mode: No local file fallback!",
                    e,
                )
                raise RuntimeError(
                    f"[GENAI_CACHE] Strict Valkey connection failed ({valkey_url}): {e}"
                )
            else:
                logger.warning(
                    "[GENAI_CACHE] Valkey connection failed: %s — falling back to file JSON",
                    e,
                )
                _redis_client = None

    return _redis_client


# ══════════════════════════════════════════════════════════════════
# TitanEmbeddingEngine — Amazon Titan Text Embeddings V2
# ══════════════════════════════════════════════════════════════════


class TitanEmbeddingEngine:
    """
    Singleton wrapper cho Amazon Titan Text Embeddings V2.

    Model: amazon.titan-embed-text-v2:0
    Dimensions: 1024
    Cost: ~$0.00002 / 1K tokens ($0.0000003 / prompt)
    Max tokens: 8,192

    Dùng để tạo embedding vector cho semantic cache lookup.
    """

    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3

            region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
            self._client = boto3.client("bedrock-runtime", region_name=region)
            logger.info(
                "[TITAN_EMBED] Bedrock runtime client initialized | region=%s | model=%s",
                region,
                _TITAN_EMBED_MODEL,
            )
        except Exception as e:
            logger.error("[TITAN_EMBED] Failed to init Bedrock client: %s", e)
            self._client = None
        return self._client

    def embed(self, text: str) -> Optional[List[float]]:
        """
        Tạo embedding vector 1024 chiều cho text.

        Args:
            text: Query text cần embed

        Returns:
            List[float] (1024 chiều) hoặc None nếu lỗi
        """
        if not _TITAN_SEMANTIC_ENABLED:
            return None

        client = self._get_client()
        if client is None:
            return None

        try:
            # Titan Embed V2: normalize=True để vector nằm trong unit sphere
            body = json.dumps(
                {
                    "inputText": text[:2048],  # Titan V2 max input
                    "dimensions": 1024,
                    "normalize": True,
                }
            )
            response = client.invoke_model(
                modelId=_TITAN_EMBED_MODEL,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            embedding = result.get("embedding", [])
            logger.debug(
                "[TITAN_EMBED] Embedded | text_len=%d | dims=%d",
                len(text),
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.warning(
                "[TITAN_EMBED] Embed failed (will skip semantic cache): %s", e
            )
            return None


_titan_engine = TitanEmbeddingEngine()


# ══════════════════════════════════════════════════════════════════
# GenAICacheStore
# ══════════════════════════════════════════════════════════════════


class GenAICacheStore:
    """
    Cache toàn bộ GenAI Response với 3 tầng lookup:

    Tier 1 — Rule-based Exact Match (0ms):
        Normalize text → SHA256 → O(1) Valkey GET

    Tier 2 — Titan Semantic Similarity (~30ms):
        Titan embed → cosine sim ≥ threshold → schema version check → HIT

    Tier 3 — LLM Pass-through (cache MISS):
        Response + embedding được lưu vào Valkey cho lần sau.

    Valkey Keys:
        copilot:genai:{user_id}:{hash}    — Response payload
        copilot:genai:emb:{user_id}       — Redis Hash: cache_key → emb_meta
        copilot:genai:entity:{type}:{id}  — Redis Set: cache_keys to invalidate
    """

    _KEY_PREFIX = "copilot:genai:"
    _EMB_INDEX_PREFIX = "copilot:genai:emb:"
    _ENTITY_INDEX_PREFIX = "copilot:genai:entity:"

    def __init__(self, filepath: Optional[str] = None):
        self._filepath = filepath or os.path.join(_BASE_DIR, "genai_cache.json")
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._entity_index: Dict[str, set] = {}
        # File-backend embedding index: cache_key -> {embedding, cached_at_ts, schema_version}
        self._emb_index: Dict[str, Dict[str, Any]] = {}
        self._stats = {
            "hits_exact": 0,
            "hits_semantic": 0,
            "hits_global": 0,
            "misses": 0,
            "invalidations": 0,
            "titan_embeds": 0,
        }

        if _get_redis() is None:
            self._load()

    # ── Normalization & Key ──

    def _normalize_semantic(self, text: str) -> str:
        """
        Tầng 1: Basic text normalization (không dùng hardcoded rules).

        Chỉ chuẩn hóa cơ bản:
        - Lowercase
        - Strip whitespace
        - Normalize multiple spaces to single space

        KHÔNG dùng hardcoded domain-specific replacements để tránh over-fitting.
        Semantic matching được xử lý bởi Titan Embeddings (Tier 2).
        """
        import re

        # Basic normalization only
        t = text.strip().lower()
        # Normalize multiple spaces to single space
        t = re.sub(r"\s+", " ", t)
        return t

    def _make_key(self, user_id: str, request_text: str) -> str:
        """Tạo cache key: copilot:genai:{user_id}:{sha256_of_normalized_text}"""
        normalized = self._normalize_semantic(request_text)
        hash_val = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"{self._KEY_PREFIX}{user_id}:{hash_val}"

    def _emb_index_key(self, user_id: str) -> str:
        """Redis Hash key chứa embedding index của một user."""
        return f"{self._EMB_INDEX_PREFIX}{user_id}"

    def _entity_key(self, entity_type: str, entity_id: str) -> str:
        return f"{self._ENTITY_INDEX_PREFIX}{entity_type}:{entity_id}"

    # ── Private: Valkey backend ──

    def _vget(self, key: str) -> Optional[Dict[str, Any]]:
        r = _get_redis()
        if r is None:
            return None
        try:
            raw = r.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug("[GENAI_CACHE] Valkey get error: %s", e)
            return None

    def _vset(self, key: str, entry: Dict[str, Any], ttl: int) -> None:
        r = _get_redis()
        if r is None:
            return
        try:
            r.setex(key, ttl, json.dumps(entry, ensure_ascii=False))
        except Exception as e:
            logger.debug("[GENAI_CACHE] Valkey set error: %s", e)

    def _vdel(self, key: str) -> None:
        r = _get_redis()
        if r:
            try:
                r.delete(key)
            except Exception as e:
                logger.debug("[GENAI_CACHE] Valkey delete error: %s", e)

    def _vget_set_members(self, set_key: str) -> set:
        r = _get_redis()
        if r:
            try:
                return r.smembers(set_key)
            except Exception:
                return set()
        return set()

    def _vadd_to_set(self, set_key: str, member: str) -> None:
        r = _get_redis()
        if r:
            try:
                r.sadd(set_key, member)
                r.expire(set_key, _GENAI_CACHE_TTL + 300)
            except Exception:
                pass

    # ── Private: Embedding Index (Valkey Hash backend) ──

    def _store_embedding(
        self, user_id: str, cache_key: str, embedding: List[float]
    ) -> None:
        """Lưu embedding metadata vào Redis Hash index của user."""
        emb_meta = {
            "embedding": embedding,
            "cached_at_ts": _now_ts(),
            "schema_version": _CACHE_SCHEMA_VERSION,
        }
        r = _get_redis()
        if r is not None:
            try:
                idx_key = self._emb_index_key(user_id)
                r.hset(idx_key, cache_key, json.dumps(emb_meta, ensure_ascii=False))
                r.expire(idx_key, _GENAI_CACHE_TTL + 60)
            except Exception as e:
                logger.warning("[TITAN_EMBED] Failed to store embedding index: %s", e)
        else:
            # File backend fallback
            self._emb_index[cache_key] = emb_meta

    def _delete_embedding(self, user_id: str, cache_key: str) -> None:
        """Xóa embedding metadata khi cache entry bị invalidate."""
        r = _get_redis()
        if r is not None:
            try:
                idx_key = self._emb_index_key(user_id)
                r.hdel(idx_key, cache_key)
            except Exception:
                pass
        else:
            self._emb_index.pop(cache_key, None)

    def _find_semantic_hit(
        self, user_id: str, query_embedding: List[float]
    ) -> Optional[str]:
        """
        Tìm cache_key có semantic similarity cao nhất với query_embedding.

        Returns:
            cache_key của entry tốt nhất (nếu sim ≥ threshold + schema version OK),
            hoặc None nếu không tìm thấy.
        """
        best_key: Optional[str] = None
        best_sim = 0.0

        r = _get_redis()
        if r is not None:
            try:
                idx_key = self._emb_index_key(user_id)
                # Redis Hash: {cache_key: emb_meta_json}
                all_entries = r.hgetall(idx_key)
                for cache_key, meta_json in all_entries.items():
                    try:
                        meta = json.loads(meta_json)
                    except Exception:
                        continue
                    # Schema version guard: bỏ qua entries của schema cũ
                    if meta.get("schema_version", 0) != _CACHE_SCHEMA_VERSION:
                        logger.debug(
                            "[TITAN_EMBED] Skipping stale schema version entry | key=%s "
                            "| entry_v=%s | current_v=%d",
                            cache_key,
                            meta.get("schema_version"),
                            _CACHE_SCHEMA_VERSION,
                        )
                        continue
                    stored_emb = meta.get("embedding", [])
                    sim = _cosine_similarity(query_embedding, stored_emb)
                    if sim > best_sim:
                        best_sim = sim
                        best_key = cache_key
            except Exception as e:
                logger.warning("[TITAN_EMBED] Semantic search error: %s", e)
        else:
            # File backend
            for cache_key, meta in self._emb_index.items():
                if meta.get("schema_version", 0) != _CACHE_SCHEMA_VERSION:
                    continue
                stored_emb = meta.get("embedding", [])
                sim = _cosine_similarity(query_embedding, stored_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_key = cache_key

        if best_sim >= _SEMANTIC_SIMILARITY_THRESHOLD and best_key:
            logger.info(
                "[TITAN_EMBED] Semantic HIT | user=%s | sim=%.4f | threshold=%.2f | key=%s",
                user_id,
                best_sim,
                _SEMANTIC_SIMILARITY_THRESHOLD,
                best_key,
            )
            return best_key

        logger.debug(
            "[TITAN_EMBED] Semantic MISS | user=%s | best_sim=%.4f | threshold=%.2f",
            user_id,
            best_sim,
            _SEMANTIC_SIMILARITY_THRESHOLD,
        )
        return None

    # ── Private: File backend ──

    def _load(self) -> None:
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._store = OrderedDict(data.get("entries", {}))
                    loaded_stats = data.get("stats", {})
                    self._stats.update(loaded_stats)
                    self._emb_index = data.get("emb_index", {})
                    # Rebuild entity index
                    self._entity_index = {}
                    for key, entry in self._store.items():
                        entities = entry.get("entities", [])
                        for entity in entities:
                            etype = entity.get("type")
                            eid = entity.get("id")
                            if etype and eid:
                                idx_key = f"{etype}:{eid}"
                                if idx_key not in self._entity_index:
                                    self._entity_index[idx_key] = set()
                                self._entity_index[idx_key].add(key)
                    logger.info(
                        "[GENAI_CACHE] Loaded %d entries + %d embeddings from %s",
                        len(self._store),
                        len(self._emb_index),
                        self._filepath,
                    )
        except Exception as e:
            logger.warning("[GENAI_CACHE] Load failed — starting fresh: %s", e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            tmp = self._filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "entries": dict(self._store),
                        "stats": self._stats,
                        "emb_index": self._emb_index,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            os.replace(tmp, self._filepath)
        except Exception as e:
            logger.error("[GENAI_CACHE] Save failed: %s", e)

    # ── Private: Phân loại câu hỏi riêng tư vs công khai ──

    _PRIVATE_KEYWORDS = [
        "cart",
        "giỏ",
        "gio",
        "checkout",
        "thanh toán",
        "thanh toan",
        "shipping",
        "giao hàng",
        "giao hang",
        "địa chỉ",
        "dia chi",
        "address",
        "order",
        "đơn hàng",
        "don hang",
        "lịch sử",
        "lich su",
        "ngân sách",
        "ngan sach",
        "sở thích",
        "so thich",
        "dị ứng",
        "di ung",
        "xác nhận",
        "xac nhan",
        "xong",
        "đặt hàng",
        "dat hang",
        "mua hàng",
        "mua hang",
    ]

    def _is_private_query(self, text: str) -> bool:
        """Trả True nếu câu hỏi liên quan PII/Cart/Order — không được lưu vào global pool."""
        t = text.lower()
        return any(kw in t for kw in self._PRIVATE_KEYWORDS)

    # ── Internals: lookup / store dùng chung cho user_id bất kỳ ──

    def _lookup(self, target_id: str, request_text: str) -> Optional[Dict[str, Any]]:
        """Tier-1 + Tier-2 lookup cho một target_id nhất định."""
        exact_key = self._make_key(target_id, request_text)

        # Tier 1: Exact match
        if _get_redis() is not None:
            entry = self._vget(exact_key)
            if entry is not None:
                self._stats["hits_exact"] += 1
                entry["hit_count"] = entry.get("hit_count", 0) + 1
                entry["cache_tier"] = "exact"
                self._vset(exact_key, entry, _GENAI_CACHE_TTL)
                return entry
        else:
            entry = self._store.get(exact_key)
            if entry is not None:
                if _now_ts() > entry.get("expires_at_ts", 0):
                    del self._store[exact_key]
                    self._save()
                else:
                    self._store.move_to_end(exact_key)
                    entry["hit_count"] = entry.get("hit_count", 0) + 1
                    entry["cache_tier"] = "exact"
                    self._stats["hits_exact"] += 1
                    self._save()
                    return entry

        # Tier 2: Titan Semantic
        if _TITAN_SEMANTIC_ENABLED:
            qemb = _titan_engine.embed(request_text)
            if qemb:
                self._stats["titan_embeds"] += 1
                sem_key = self._find_semantic_hit(target_id, qemb)
                if sem_key is not None:
                    entry = (
                        self._vget(sem_key)
                        if _get_redis() is not None
                        else self._store.get(sem_key)
                    )
                    if entry is not None:
                        # File backend: check TTL on semantic-matched entry too
                        if _get_redis() is None and _now_ts() > entry.get(
                            "expires_at_ts", 0
                        ):
                            del self._store[sem_key]
                            self._emb_index.pop(sem_key, None)
                            self._save()
                        else:
                            self._stats["hits_semantic"] += 1
                            entry["hit_count"] = entry.get("hit_count", 0) + 1
                            entry["cache_tier"] = "semantic"
                            if _get_redis() is not None:
                                self._vset(sem_key, entry, _GENAI_CACHE_TTL)
                            else:
                                self._store.move_to_end(sem_key)
                                self._save()
                            return entry
        return None

    def _write(
        self,
        target_id: str,
        key: str,
        entry: dict,
        request_text: str,
        entities: Optional[list],
    ) -> None:
        """Ghi một entry vào Valkey (hoặc file) và index embedding."""
        if _get_redis() is not None:
            self._vset(key, entry, _GENAI_CACHE_TTL)
            if entities:
                for ent in entities:
                    etype, eid = ent.get("type"), ent.get("id")
                    if etype and eid:
                        self._vadd_to_set(self._entity_key(etype, eid), key)
            if _TITAN_SEMANTIC_ENABLED:
                emb = _titan_engine.embed(request_text)
                if emb:
                    self._stats["titan_embeds"] += 1
                    self._store_embedding(target_id, key, emb)
        else:
            expires_ts = _now_ts() + _GENAI_CACHE_TTL
            entry["expires_at_ts"] = expires_ts
            entry["expires_at"] = datetime.fromtimestamp(
                expires_ts, timezone.utc
            ).isoformat()
            self._store[key] = entry
            self._store.move_to_end(key)
            if _TITAN_SEMANTIC_ENABLED:
                emb = _titan_engine.embed(request_text)
                if emb:
                    self._stats["titan_embeds"] += 1
                    self._store_embedding(target_id, key, emb)
            if len(self._store) > _CACHE_MAX_ENTRIES:
                self._store.popitem(last=False)
            self._save()

    # ── Public API ──

    def get(self, user_id: str, request_text: str) -> Optional[Dict[str, Any]]:
        """
        Lấy cached response qua 3 tầng lookup:

        Tier 1 — User Exact Match    (0ms)
        Tier 2 — User Semantic Match (~30ms, Titan Embed)
        Tier 3 — Global Shared Pool  (exact + semantic, chỉ với câu hỏi không riêng tư)

        Tier 3 giải quyết bài toán 1000 users hỏi cùng câu hỏi public (liệt kê sản phẩm,
        tìm telescope...) mà không cần mỗi user phải miss riêng. Response trong global pool
        đã qua guardrail và không chứa PII/private data.

        Khi global hit: tự động copy vào user-specific cache (warm-up) để lần sau
        user đó hit từ tier riêng → nhanh hơn + traceable rõ ràng hơn.

        Returns:
            {reply, steps, intent, evidence, cached_at, hit_count, cache_tier}
            hoặc None nếu miss ở cả 3 tầng.
        """
        # ── Tier 1 + 2: User-specific lookup ──
        entry = self._lookup(user_id, request_text)
        if entry is not None:
            logger.info(
                "[GENAI_CACHE] HIT user=%s | tier=%s | hits=%d",
                user_id,
                entry.get("cache_tier"),
                entry.get("hit_count", 0),
            )
            return entry

        # ── Tier 3: Global Shared Pool fallback ──
        # Chỉ dùng cho câu hỏi public (không liên quan cart/PII/order).
        # Response trong pool đã qua toàn bộ guardrail pipeline, không chứa data
        # riêng tư của bất kỳ user nào — an toàn để phục vụ cho user khác.
        if user_id != "global" and not self._is_private_query(request_text):
            global_entry = self._lookup("global", request_text)
            if global_entry is not None:
                self._stats["hits_global"] += 1
                global_entry["cache_tier"] = "global"
                logger.info(
                    "[GENAI_CACHE] HIT global_pool | user=%s | tier=%s | hits=%d",
                    user_id,
                    global_entry.get("cache_tier"),
                    global_entry.get("hit_count", 0),
                )

                # ── Warm-up: copy vào user-specific cache ──
                # Lần sau user này hỏi lại sẽ hit từ tier riêng (Tier 1/2)
                # thay vì phải fallback lại global pool.
                user_key = self._make_key(user_id, request_text)
                user_entry = {
                    **global_entry,
                    "user_id": user_id,
                    "cache_tier": "global_warmup",
                }
                entities = global_entry.get("entities", [])
                self._write(user_id, user_key, user_entry, request_text, entities)
                logger.debug(
                    "[GENAI_CACHE] Warm-up: copied global entry to user=%s",
                    user_id,
                )

                return global_entry

        # ── Miss ──
        self._stats["misses"] += 1
        logger.debug(
            "[GENAI_CACHE] MISS | user=%s | key=%s",
            user_id,
            self._make_key(user_id, request_text),
        )
        return None

    def set(
        self,
        user_id: str,
        request_text: str,
        response_data: Dict[str, Any],
        entities: Optional[list] = None,
    ) -> None:
        """
        Lưu GenAI response vào cache + lưu Titan embedding.
        Nếu câu hỏi không riêng tư (cart/PII), tự động nhân bản vào Global Shared Pool.

        Args:
            user_id: User ID (for isolation)
            request_text: Original user request
            response_data: {reply, steps, intent, evidence}
            entities: List of {type, id} for invalidation tracking
        """
        key = self._make_key(user_id, request_text)
        entry = {
            "user_id": user_id,
            "request": request_text[:200],
            "reply": response_data.get("reply"),
            "steps": response_data.get("steps", []),
            "intent": response_data.get("intent"),
            "evidence": response_data.get("evidence"),
            "cached_at": _now_iso(),
            "hit_count": 0,
            "entities": entities or [],
            "schema_version": _CACHE_SCHEMA_VERSION,
            "cache_tier": "miss",
        }

        # ── Lưu vào User-specific cache ──
        self._write(user_id, key, entry.copy(), request_text, entities)
        logger.info(
            "[GENAI_CACHE] SET user=%s | entities=%d | schema_v=%d",
            user_id,
            len(entities) if entities else 0,
            _CACHE_SCHEMA_VERSION,
        )

        # ── Nhân bản vào Global Shared Pool nếu không phải câu hỏi riêng tư ──
        if user_id != "global" and not self._is_private_query(request_text):
            global_key = self._make_key("global", request_text)
            global_entry = {**entry.copy(), "user_id": "global"}
            self._write("global", global_key, global_entry, request_text, entities)
            logger.info(
                "[GENAI_CACHE] SET global_pool | origin_user=%s | entities=%d",
                user_id,
                len(entities) if entities else 0,
            )

    def invalidate_by_entity(self, entity_type: str, entity_id: str) -> int:
        """
        Vô hiệu hóa tất cả cache entries liên quan đến entity.

        Returns:
            Number of entries invalidated
        """
        count = 0

        # Valkey backend
        if _get_redis() is not None:
            idx_key = self._entity_key(entity_type, entity_id)
            cache_keys = self._vget_set_members(idx_key)

            for key in cache_keys:
                # Extract user_id from key: copilot:genai:{user_id}:{hash}
                parts = key.split(":")
                if len(parts) >= 4:
                    user_id = parts[2]
                    self._delete_embedding(user_id, key)
                self._vdel(key)
                count += 1

            self._vdel(idx_key)
            self._stats["invalidations"] += count
            logger.info(
                "[GENAI_CACHE] Invalidated (valkey) | entity=%s:%s | count=%d",
                entity_type,
                entity_id,
                count,
            )
            return count

        # File backend
        idx_key = f"{entity_type}:{entity_id}"
        cache_keys = self._entity_index.get(idx_key, set())

        for key in list(cache_keys):
            if key in self._store:
                del self._store[key]
                self._emb_index.pop(key, None)
                count += 1

        if idx_key in self._entity_index:
            del self._entity_index[idx_key]

        self._stats["invalidations"] += count
        self._save()
        logger.info(
            "[GENAI_CACHE] Invalidated (file) | entity=%s:%s | count=%d",
            entity_type,
            entity_id,
            count,
        )
        return count

    def invalidate_by_user(self, user_id: str) -> int:
        """
        Xóa toàn bộ cache + embedding index của một user.

        Returns:
            Number of entries invalidated
        """
        count = 0
        prefix = f"{self._KEY_PREFIX}{user_id}:"

        # Valkey backend
        if _get_redis() is not None:
            r = _get_redis()
            try:
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor, match=f"{prefix}*", count=100)
                    for key in keys:
                        self._vdel(key)
                        count += 1
                    if cursor == 0:
                        break
                # Clear embedding index for user
                r.delete(self._emb_index_key(user_id))
            except Exception as e:
                logger.error("[GENAI_CACHE] User invalidation error: %s", e)

            self._stats["invalidations"] += count
            logger.info(
                "[GENAI_CACHE] Invalidated user (valkey) | user=%s | count=%d",
                user_id,
                count,
            )
            return count

        # File backend
        keys_to_delete = [k for k in self._store.keys() if k.startswith(prefix)]
        for key in keys_to_delete:
            del self._store[key]
            self._emb_index.pop(key, None)
            count += 1

        self._stats["invalidations"] += count
        self._save()
        logger.info(
            "[GENAI_CACHE] Invalidated user (file) | user=%s | count=%d", user_id, count
        )
        return count

    def clear(self) -> int:
        """Xóa sạch toàn bộ GenAI cache + embedding index (dùng để reset trước test suite)."""
        count = len(self._store)
        if _get_redis() is not None:
            r = _get_redis()
            try:
                cursor = 0
                while True:
                    # Xóa cả response cache và embedding index
                    cursor, keys = r.scan(
                        cursor, match=f"{self._KEY_PREFIX}*", count=100
                    )
                    for k in keys:
                        r.delete(k)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.error("[GENAI_CACHE] Clear redis error: %s", e)

        self._store.clear()
        self._emb_index.clear()
        self._entity_index.clear()
        self._stats = {
            "hits_exact": 0,
            "hits_semantic": 0,
            "hits_global": 0,
            "misses": 0,
            "invalidations": 0,
            "titan_embeds": 0,
        }
        self._save()
        logger.info("[GENAI_CACHE] Cleared all cache entries (%d entries)", count)
        return count

    def stats(self) -> Dict[str, Any]:
        """Trả về thống kê cache bao gồm semantic cache + global pool metrics."""
        hits_exact = self._stats.get("hits_exact", 0)
        hits_semantic = self._stats.get("hits_semantic", 0)
        hits_global = self._stats.get("hits_global", 0)
        total_hits = hits_exact + hits_semantic + hits_global
        total = total_hits + self._stats.get("misses", 0)
        hit_rate = round(total_hits / total * 100, 1) if total > 0 else 0
        semantic_rate = (
            round(hits_semantic / total_hits * 100, 1) if total_hits > 0 else 0
        )
        global_rate = round(hits_global / total_hits * 100, 1) if total_hits > 0 else 0
        return {
            **self._stats,
            "total_hits": total_hits,
            "total_entries": len(self._store),
            "total_requests": total,
            "hit_rate_pct": hit_rate,
            "semantic_hit_rate_pct": semantic_rate,
            "global_hit_rate_pct": global_rate,
            "backend": "valkey" if _get_redis() is not None else "file",
            "ttl_seconds": _GENAI_CACHE_TTL,
            "titan_enabled": _TITAN_SEMANTIC_ENABLED,
            "titan_model": _TITAN_EMBED_MODEL,
            "similarity_threshold": _SEMANTIC_SIMILARITY_THRESHOLD,
            "schema_version": _CACHE_SCHEMA_VERSION,
        }

    def dump(self) -> Dict[str, Any]:
        """Snapshot toàn bộ cache (dùng để debug + cache-manager UI)."""
        # Build entries dict for UI (file backend has full data, valkey has sample)
        if _get_redis() is None:
            # File backend: expose entries (without embedding vectors to save bandwidth)
            entries = {}
            for key, entry in self._store.items():
                entries[key] = {k: v for k, v in entry.items() if k != "embedding"}
        else:
            entries = {}

        return {
            "config": {
                "ttl_seconds": _GENAI_CACHE_TTL,
                "max_entries": _GENAI_CACHE_MAX_ENTRIES,
                "backend": "valkey" if _get_redis() is not None else "file",
                "titan_semantic_enabled": _TITAN_SEMANTIC_ENABLED,
                "titan_model": _TITAN_EMBED_MODEL,
                "similarity_threshold": _SEMANTIC_SIMILARITY_THRESHOLD,
                "schema_version": _CACHE_SCHEMA_VERSION,
            },
            "stats": self.stats(),
            "entries": entries,
            "sample_entries": (
                list(self._store.keys())[:10] if _get_redis() is None else []
            ),
        }


# ══════════════════════════════════════════════════════════════════
# Singleton instance
# ══════════════════════════════════════════════════════════════════

_genai_cache_store = None


def get_genai_cache_store() -> GenAICacheStore:
    """Singleton accessor cho GenAICacheStore."""
    global _genai_cache_store
    if _genai_cache_store is None:
        _genai_cache_store = GenAICacheStore()
    return _genai_cache_store
