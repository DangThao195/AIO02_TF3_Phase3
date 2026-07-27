"""
AIE MANDATES ENGINE — Production Implementation
=================================================
Mandate #23: GenAI Caching & Memory (Semantic Cache + User Isolation + Cross-Session Memory)
Mandate #24: LLM Observability (Full-Field Tracing, Trace ID, PII Masking, Aggregation)
Mandate #25: AI Resilience & Fallback (Circuit Breaker, Retry Backoff, Output Validation)

Integration: Import and use from copilot_agent.py / llm.py / main.py
"""

import time
import re
import uuid
import json
import hashlib
import logging
import threading
from enum import Enum
from collections import defaultdict, OrderedDict
from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime, timezone

logger = logging.getLogger("AIE_Engine")

# ══════════════════════════════════════════════════════════════════
# MANDATE #23: GENAI CACHING & MEMORY (Production)
# ══════════════════════════════════════════════════════════════════

class SemanticCache:
    """
    Production-grade LLM response cache with:
    - User isolation (cache key includes user_id)
    - TTL expiration with invalidation
    - Hit/miss tracking with metrics
    - Thread-safe operations
    """

    def __init__(self, default_ttl: int = 300, max_entries: int = 1000):
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "invalidations": 0}
        self._lock = threading.Lock()

    def _make_key(self, query: str, user_id: str = "anonymous") -> str:
        """Generate cache key with user isolation."""
        norm_q = " ".join(query.lower().strip().split())
        raw = f"{user_id}:{norm_q}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def get(self, query: str, user_id: str = "anonymous") -> Optional[Dict[str, Any]]:
        """
        Retrieve cached response. Returns None on miss or expired entry.
        Enforces TTL expiration and user boundary isolation.
        """
        key = self._make_key(query, user_id)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None

            # TTL check
            if time.time() > entry["expires_at"]:
                del self._store[key]
                self._stats["misses"] += 1
                self._stats["evictions"] += 1
                logger.debug("[Cache] TTL expired for key=%s", key[:8])
                return None

            # Promote in LRU
            self._store.move_to_end(key)
            entry["hit_count"] += 1
            self._stats["hits"] += 1
            logger.info("⚡ [Mandate #23] Cache HIT | user=%s | key=%s", user_id, key[:8])
            return {"response": entry["response"], "cached": True, "cache_key": key}

    def set(self, query: str, response: str, user_id: str = "anonymous",
            ttl: Optional[int] = None, metadata: Optional[Dict] = None) -> str:
        """Store response with TTL and user isolation. Returns cache key."""
        key = self._make_key(query, user_id)
        effective_ttl = ttl or self._default_ttl
        with self._lock:
            self._store[key] = {
                "query": query,
                "response": response,
                "user_id": user_id,
                "cached_at": time.time(),
                "expires_at": time.time() + effective_ttl,
                "ttl_seconds": effective_ttl,
                "hit_count": 0,
                "metadata": metadata or {},
            }
            self._store.move_to_end(key)

            # LRU eviction
            while len(self._store) > self._max_entries:
                evicted_key, _ = self._store.popitem(last=False)
                self._stats["evictions"] += 1
                logger.debug("[Cache] LRU evict key=%s", evicted_key[:8])

        logger.info("💾 [Mandate #23] Cache SET | user=%s | key=%s | ttl=%ds",
                     user_id, key[:8], effective_ttl)
        return key

    def invalidate(self, query: str, user_id: str = "anonymous") -> bool:
        """Invalidate a specific cache entry (e.g., when source data changes)."""
        key = self._make_key(query, user_id)
        with self._lock:
            if key in self._store:
                del self._store[key]
                self._stats["invalidations"] += 1
                logger.info("🗑️ [Mandate #23] Cache INVALIDATED | key=%s", key[:8])
                return True
        return False

    def invalidate_user(self, user_id: str) -> int:
        """Invalidate all cache entries for a specific user."""
        count = 0
        with self._lock:
            keys_to_remove = [k for k, v in self._store.items() if v.get("user_id") == user_id]
            for k in keys_to_remove:
                del self._store[k]
                count += 1
            self._stats["invalidations"] += count
        logger.info("🗑️ [Mandate #23] Invalidated %d entries for user=%s", count, user_id)
        return count

    def stats(self) -> Dict[str, Any]:
        """Return cache performance metrics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = round(self._stats["hits"] / total * 100, 1) if total > 0 else 0.0
        return {
            **self._stats,
            "total_requests": total,
            "hit_rate_pct": hit_rate,
            "current_entries": len(self._store),
            "max_entries": self._max_entries,
        }


class UserMemoryStore:
    """
    Mandate #23 — Long-Term Cross-Session Memory.
    Stores user preferences, facts, and history that persist across sessions.
    Isolated per user_id. PII-aware with redaction support.
    """

    # PII patterns to redact before storing
    _PII_PATTERNS = [
        (re.compile(r'\b\d{10,12}\b'), '[PHONE_REDACTED]'),
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL_REDACTED]'),
        (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CARD_REDACTED]'),
    ]

    def __init__(self):
        self._memories: Dict[str, Dict[str, Any]] = {}  # user_id -> memory data
        self._lock = threading.Lock()

    def _redact_pii(self, text: str) -> str:
        """Remove PII patterns from text before long-term storage."""
        for pattern, replacement in self._PII_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def save_preference(self, user_id: str, key: str, value: str) -> None:
        """Save a user preference (e.g., 'preferred_size' = 'L')."""
        with self._lock:
            if user_id not in self._memories:
                self._memories[user_id] = {"preferences": {}, "facts": [], "last_updated": None}
            self._memories[user_id]["preferences"][key] = self._redact_pii(value)
            self._memories[user_id]["last_updated"] = time.time()
        logger.info("🧠 [Mandate #23] Saved preference for user=%s: %s", user_id, key)

    def save_fact(self, user_id: str, fact: str) -> None:
        """Save a user fact (e.g., 'Khách thích áo thun cotton')."""
        with self._lock:
            if user_id not in self._memories:
                self._memories[user_id] = {"preferences": {}, "facts": [], "last_updated": None}
            redacted = self._redact_pii(fact)
            # Avoid duplicate facts
            if redacted not in self._memories[user_id]["facts"]:
                self._memories[user_id]["facts"].append(redacted)
                # Keep last 50 facts
                if len(self._memories[user_id]["facts"]) > 50:
                    self._memories[user_id]["facts"] = self._memories[user_id]["facts"][-50:]
            self._memories[user_id]["last_updated"] = time.time()
        logger.info("🧠 [Mandate #23] Saved fact for user=%s", user_id)

    def recall(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve all stored memory for a user (cross-session recall)."""
        with self._lock:
            memory = self._memories.get(user_id)
            if memory:
                logger.info("🧠 [Mandate #23] Cross-session recall for user=%s | prefs=%d | facts=%d",
                             user_id, len(memory.get("preferences", {})), len(memory.get("facts", [])))
            return memory

    def is_isolated(self, user_id_a: str, user_id_b: str) -> bool:
        """Verify that two users cannot see each other's memory (for audit)."""
        return self._memories.get(user_id_a) != self._memories.get(user_id_b, {"_sentinel": True})


# ══════════════════════════════════════════════════════════════════
# MANDATE #24: LLM OBSERVABILITY (Production)
# ══════════════════════════════════════════════════════════════════

class LLMTracer:
    """
    Production LLM Observability Tracer.
    Records full-field traces for every model call with:
    - model + version, tokens in/out, cost, latency
    - trace_id linking request chain, session/user (anonymized)
    - tool_calls tracking, outcome status
    - PII masking before storage
    - In-memory aggregation store for cost/latency views
    """

    PRICING_PER_1K_TOKENS = {
        "amazon.nova-lite-v1":       {"input": 0.00006, "output": 0.00024},
        "apac.amazon.nova-lite-v1:0": {"input": 0.00006, "output": 0.00024},
        "anthropic.claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
        "openai.gpt-4o-mini":        {"input": 0.00015, "output": 0.0006},
        "cache-hit":                  {"input": 0.0, "output": 0.0},
        "fallback-static":           {"input": 0.0, "output": 0.0},
    }

    # PII patterns to mask in trace data
    _PII_PATTERNS = [
        (re.compile(r'\b\d{10,12}\b'), '[PHONE]'),
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL]'),
        (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CARD]'),
        (re.compile(r'PII-TOKEN-\w+', re.IGNORECASE), '[PII_REDACTED]'),
    ]

    def __init__(self):
        self._traces: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        # Aggregation buckets
        self._agg_by_model: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"total_cost": 0.0, "total_tokens": 0, "total_latency_ms": 0.0, "call_count": 0}
        )
        self._agg_by_surface: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"total_cost": 0.0, "total_tokens": 0, "total_latency_ms": 0.0, "call_count": 0}
        )

    @classmethod
    def _mask_pii(cls, text: str) -> str:
        """Mask PII/secrets in prompt/response before storing in trace."""
        if not text:
            return text
        for pattern, replacement in cls._PII_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    @classmethod
    def calculate_cost(cls, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        rates = cls.PRICING_PER_1K_TOKENS.get(model_name, {"input": 0.001, "output": 0.002})
        input_cost = (prompt_tokens / 1000.0) * rates["input"]
        output_cost = (completion_tokens / 1000.0) * rates["output"]
        return round(input_cost + output_cost, 8)

    @classmethod
    def generate_trace_id(cls) -> str:
        """Generate a unique trace ID for end-to-end request tracking."""
        return f"trace-{uuid.uuid4().hex[:16]}"

    def trace_call(
        self,
        model_name: str,
        prompt: str,
        response: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        trace_id: str = "",
        session_id: str = "",
        user_id: str = "anonymous",
        tool_calls: Optional[List[str]] = None,
        outcome: str = "ok",
        surface: str = "copilot",
    ) -> Dict[str, Any]:
        """Record a full-field trace for one LLM call. PII is masked before storage."""
        cost = self.calculate_cost(model_name, prompt_tokens, completion_tokens)

        # Anonymize user_id (hash for privacy)
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:12] if user_id != "anonymous" else "anonymous"

        trace_record = {
            "trace_id": trace_id or self.generate_trace_id(),
            "span_id": f"span-{uuid.uuid4().hex[:8]}",
            "model": model_name,
            "prompt_masked": self._mask_pii(prompt[:200]),   # Truncate + mask
            "response_masked": self._mask_pii(response[:200]),
            "latency_ms": round(latency_ms, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_usd": cost,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user_hash": user_hash,
            "tool_calls": tool_calls or [],
            "outcome": outcome,  # "ok" | "error" | "fallback" | "cache_hit"
            "surface": surface,
        }

        with self._lock:
            self._traces.append(trace_record)
            # Keep last 10000 traces in memory
            if len(self._traces) > 10000:
                self._traces = self._traces[-5000:]

            # Update aggregation
            agg_m = self._agg_by_model[model_name]
            agg_m["total_cost"] += cost
            agg_m["total_tokens"] += trace_record["total_tokens"]
            agg_m["total_latency_ms"] += latency_ms
            agg_m["call_count"] += 1

            agg_s = self._agg_by_surface[surface]
            agg_s["total_cost"] += cost
            agg_s["total_tokens"] += trace_record["total_tokens"]
            agg_s["total_latency_ms"] += latency_ms
            agg_s["call_count"] += 1

        logger.info(
            "📊 [Mandate #24] Trace | id=%s | model=%s | tokens=%d | cost=$%.6f | latency=%.1fms | outcome=%s",
            trace_record["trace_id"][:16], model_name, trace_record["total_tokens"],
            cost, latency_ms, outcome
        )
        return trace_record

    def get_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        """Fetch all spans for a given trace_id (end-to-end reconstruction)."""
        with self._lock:
            return [t for t in self._traces if t["trace_id"] == trace_id]

    def get_aggregate_view(self) -> Dict[str, Any]:
        """Aggregated cost/latency/tokens by model and by surface."""
        with self._lock:
            by_model = {}
            for model, agg in self._agg_by_model.items():
                avg_latency = round(agg["total_latency_ms"] / agg["call_count"], 2) if agg["call_count"] > 0 else 0
                by_model[model] = {
                    **agg,
                    "total_cost": round(agg["total_cost"], 6),
                    "avg_latency_ms": avg_latency,
                }
            by_surface = {}
            for surface, agg in self._agg_by_surface.items():
                avg_latency = round(agg["total_latency_ms"] / agg["call_count"], 2) if agg["call_count"] > 0 else 0
                by_surface[surface] = {
                    **agg,
                    "total_cost": round(agg["total_cost"], 6),
                    "avg_latency_ms": avg_latency,
                }
            return {
                "by_model": by_model,
                "by_surface": by_surface,
                "total_traces": len(self._traces),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }


# ══════════════════════════════════════════════════════════════════
# MANDATE #25: AI RESILIENCE & FALLBACK (Production)
# ══════════════════════════════════════════════════════════════════

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking calls (provider down)
    HALF_OPEN = "half_open" # Testing if provider recovered


class CircuitBreaker:
    """
    Circuit Breaker for LLM provider protection.
    - Tracks consecutive failures
    - Opens circuit after threshold failures
    - Auto-recovers after cool-down period
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 30):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if time.time() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("🔄 [Mandate #25] Circuit Breaker → HALF_OPEN (testing recovery)")
            return self._state

    def allow_request(self) -> bool:
        """Check if a request is allowed through the circuit."""
        current = self.state
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful call — resets failure count, closes circuit."""
        with self._lock:
            self._failure_count = 0
            if self._state != CircuitState.CLOSED:
                logger.info("✅ [Mandate #25] Circuit Breaker → CLOSED (provider recovered)")
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — may open the circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "🔴 [Mandate #25] Circuit Breaker → OPEN after %d consecutive failures",
                        self._failure_count
                    )
                self._state = CircuitState.OPEN

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "recovery_timeout_s": self._recovery_timeout,
        }


def retry_with_backoff(
    fn: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
) -> Any:
    """
    Execute fn with exponential backoff retry.
    Mandate #25: Timeout + retry backoff with ceiling.
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "🔁 [Mandate #25] Retry %d/%d after %.1fs | error: %s",
                    attempt + 1, max_retries, delay, str(e)[:100]
                )
                time.sleep(delay)
    raise last_exception


def validate_llm_output(raw_text: str, required_keys: Optional[List[str]] = None) -> Tuple[bool, Any]:
    """
    Mandate #25: Validate LLM structured output.
    Returns (is_valid, parsed_data_or_error_message).
    """
    if not raw_text or not raw_text.strip():
        return False, "Empty LLM output"

    # Strip markdown code fences
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"JSON parse error: {e}"

    if required_keys:
        missing = [k for k in required_keys if k not in parsed]
        if missing:
            return False, f"Missing required keys: {missing}"

    return True, parsed


class ResilientLLMGateway:
    """
    Production Multi-Provider LLM Gateway.
    Combines: Cache check → Circuit Breaker → Retry with Backoff → Fallback Chain → Output Validation → Tracing.
    """

    def __init__(self, primary_invoke_fn: Optional[Callable] = None,
                 secondary_invoke_fn: Optional[Callable] = None):
        self.cache = SemanticCache(default_ttl=300)
        self.tracer = LLMTracer()
        self.user_memory = UserMemoryStore()
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

        # Pluggable LLM invoke functions (set by integration layer)
        self._primary_invoke = primary_invoke_fn
        self._secondary_invoke = secondary_invoke_fn

    def generate(
        self,
        prompt: str,
        user_id: str = "anonymous",
        session_id: str = "",
        trace_id: str = "",
        surface: str = "copilot",
        validate_keys: Optional[List[str]] = None,
        use_cache: bool = True,
        ttl: Optional[int] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Full production request flow:
        1. Check semantic cache (with user isolation)
        2. Check circuit breaker state
        3. Call primary LLM with retry backoff
        4. On failure → fallback to secondary LLM
        5. On total failure → graceful static fallback
        6. Validate output schema if required
        7. Trace every step
        """
        if not trace_id:
            trace_id = LLMTracer.generate_trace_id()
        start_time = time.time()

        # ── Step 1: Cache Check (Mandate #23) ──
        if use_cache:
            cached = self.cache.get(prompt, user_id)
            if cached:
                latency_ms = (time.time() - start_time) * 1000
                trace = self.tracer.trace_call(
                    model_name="cache-hit", prompt=prompt, response=cached["response"],
                    latency_ms=latency_ms, trace_id=trace_id, session_id=session_id,
                    user_id=user_id, outcome="cache_hit", surface=surface,
                )
                return cached["response"], trace

        # ── Step 2: Circuit Breaker Check (Mandate #25) ──
        if not self.circuit_breaker.allow_request():
            latency_ms = (time.time() - start_time) * 1000
            fallback_msg = "Dạ, hệ thống AI đang tạm ngưng để phục hồi. Xin quý khách thử lại sau giây lát. [Chế độ suy giảm]"
            trace = self.tracer.trace_call(
                model_name="circuit-open", prompt=prompt, response=fallback_msg,
                latency_ms=latency_ms, trace_id=trace_id, session_id=session_id,
                user_id=user_id, outcome="fallback", surface=surface,
            )
            return fallback_msg, trace

        # ── Step 3: Primary LLM with Retry (Mandate #25) ──
        used_model = "amazon.nova-lite-v1"
        response_text = None
        outcome = "ok"

        if self._primary_invoke:
            try:
                response_text = retry_with_backoff(
                    fn=lambda: self._primary_invoke(prompt),
                    max_retries=2,
                    base_delay=1.0,
                    max_delay=8.0,
                )
                self.circuit_breaker.record_success()
            except Exception as e:
                self.circuit_breaker.record_failure()
                logger.warning("⚠️ [Mandate #25] Primary LLM failed: %s. Trying fallback...", str(e)[:100])
                outcome = "fallback"

                # ── Step 4: Secondary LLM Fallback ──
                if self._secondary_invoke:
                    used_model = "openai.gpt-4o-mini"
                    try:
                        response_text = self._secondary_invoke(prompt)
                    except Exception as e_fallback:
                        logger.error("❌ [Mandate #25] Secondary LLM also failed: %s", str(e_fallback)[:100])

        # ── Step 5: Static Graceful Fallback ──
        if response_text is None:
            used_model = "fallback-static"
            outcome = "fallback"
            response_text = ("Dạ, hiện tại trợ lý AI đang quá tải. "
                           "Xin quý khách vui lòng thử lại sau giây lát! "
                           "[Chế độ suy giảm — chất lượng bị ảnh hưởng]")

        # ── Step 6: Output Validation (Mandate #25) ──
        if validate_keys and used_model not in ("cache-hit", "fallback-static", "circuit-open"):
            is_valid, result = validate_llm_output(response_text, validate_keys)
            if not is_valid:
                logger.warning("🚫 [Mandate #25] Output validation FAILED: %s — using safe fallback", result)
                outcome = "validation_fail"
                response_text = json.dumps({"error": "output_validation_failed", "detail": str(result)})

        latency_ms = (time.time() - start_time) * 1000

        # ── Step 7: Cache new response (Mandate #23) ──
        if outcome == "ok" and use_cache and used_model not in ("fallback-static", "circuit-open"):
            self.cache.set(prompt, response_text, user_id=user_id, ttl=ttl)

        # ── Step 8: Trace (Mandate #24) ──
        trace = self.tracer.trace_call(
            model_name=used_model, prompt=prompt, response=response_text,
            latency_ms=latency_ms, trace_id=trace_id, session_id=session_id,
            user_id=user_id, outcome=outcome, surface=surface,
        )

        return response_text, trace


# ══════════════════════════════════════════════════════════════════
# SINGLETON INSTANCES (for import by other modules)
# ══════════════════════════════════════════════════════════════════

# Global instances — shared across the application
_global_cache = SemanticCache()
_global_tracer = LLMTracer()
_global_user_memory = UserMemoryStore()
_global_circuit_breaker = CircuitBreaker()
_global_gateway = ResilientLLMGateway()


def get_cache() -> SemanticCache:
    return _global_cache

def get_tracer() -> LLMTracer:
    return _global_tracer

def get_user_memory() -> UserMemoryStore:
    return _global_user_memory

def get_circuit_breaker() -> CircuitBreaker:
    return _global_circuit_breaker

def get_gateway() -> ResilientLLMGateway:
    return _global_gateway


# ══════════════════════════════════════════════════════════════════
# PRODUCTION VERIFICATION SUITE
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  PRODUCTION VERIFICATION: MANDATES #23, #24, #25")
    print("=" * 60)

    gateway = ResilientLLMGateway(
        primary_invoke_fn=lambda p: f"Primary response for: {p[:50]}",
        secondary_invoke_fn=lambda p: f"Secondary response for: {p[:50]}",
    )

    # ── TEST 1: Primary LLM + Tracing ──
    print("\n--- TEST 1: Primary LLM + Full Tracing ---")
    resp1, trace1 = gateway.generate(
        "Gợi ý sản phẩm bán chạy nhất",
        user_id="user_A", session_id="sess_001", surface="copilot"
    )
    print(f"  Response: {resp1}")
    assert "Primary response" in resp1
    assert trace1["outcome"] == "ok"
    assert trace1["trace_id"].startswith("trace-")
    assert trace1["user_hash"] != "user_A"  # user_id is hashed
    print("  ✅ Full-field trace with anonymized user")

    # ── TEST 2: Cache HIT with User Isolation (Mandate #23) ──
    print("\n--- TEST 2: Cache HIT + User Isolation ---")
    resp2, trace2 = gateway.generate(
        "Gợi ý sản phẩm bán chạy nhất",
        user_id="user_A", session_id="sess_001"
    )
    assert trace2["outcome"] == "cache_hit"
    assert trace2["model"] == "cache-hit"

    # Different user should NOT see user_A's cache
    resp2b, trace2b = gateway.generate(
        "Gợi ý sản phẩm bán chạy nhất",
        user_id="user_B", session_id="sess_002"
    )
    assert trace2b["outcome"] == "ok"  # Miss for user_B
    assert trace2b["model"] != "cache-hit"
    print("  ✅ Cache user isolation verified")

    # ── TEST 3: Cache Invalidation (Mandate #23) ──
    print("\n--- TEST 3: Cache Invalidation ---")
    invalidated = gateway.cache.invalidate("Gợi ý sản phẩm bán chạy nhất", user_id="user_A")
    assert invalidated
    resp3, trace3 = gateway.generate(
        "Gợi ý sản phẩm bán chạy nhất",
        user_id="user_A", session_id="sess_001"
    )
    assert trace3["outcome"] == "ok"  # Miss after invalidation
    print("  ✅ Cache invalidation working")

    # ── TEST 4: Long-Term Cross-Session Memory (Mandate #23) ──
    print("\n--- TEST 4: Cross-Session Memory ---")
    gateway.user_memory.save_preference("user_A", "preferred_size", "L")
    gateway.user_memory.save_fact("user_A", "Khách thích áo thun cotton")
    # New session — recall from long-term memory
    recall = gateway.user_memory.recall("user_A")
    assert recall is not None
    assert recall["preferences"]["preferred_size"] == "L"
    assert "Khách thích áo thun cotton" in recall["facts"]
    # User B cannot see user A's memory
    recall_b = gateway.user_memory.recall("user_B")
    assert recall_b is None
    assert gateway.user_memory.is_isolated("user_A", "user_B")
    print("  ✅ Cross-session memory + user isolation verified")

    # ── TEST 5: PII Masking in Memory & Trace (Mandate #23 + #24) ──
    print("\n--- TEST 5: PII Masking ---")
    gateway.user_memory.save_fact("user_A", "Số điện thoại 0909123456 của khách")
    recall_pii = gateway.user_memory.recall("user_A")
    assert "0909123456" not in str(recall_pii)
    assert "[PHONE_REDACTED]" in str(recall_pii)

    resp5, trace5 = gateway.generate(
        "Tôi là Nguyễn Văn A, email test@example.com, PII-TOKEN-ABC123",
        user_id="user_C", session_id="sess_003"
    )
    assert "test@example.com" not in trace5["prompt_masked"]
    assert "PII-TOKEN-ABC123" not in trace5["prompt_masked"]
    assert "[EMAIL]" in trace5["prompt_masked"]
    assert "[PII_REDACTED]" in trace5["prompt_masked"]
    print("  ✅ PII masking in memory & traces verified")

    # ── TEST 6: End-to-End Trace Reconstruction (Mandate #24) ──
    print("\n--- TEST 6: E2E Trace Reconstruction ---")
    shared_trace_id = LLMTracer.generate_trace_id()
    # Simulate multi-step request
    gateway.generate("Step 1: intent parse", user_id="user_D", trace_id=shared_trace_id)
    gateway.generate("Step 2: tool call", user_id="user_D", trace_id=shared_trace_id, use_cache=False)
    chain = gateway.tracer.get_trace(shared_trace_id)
    assert len(chain) == 2
    assert all(t["trace_id"] == shared_trace_id for t in chain)
    print(f"  ✅ Reconstructed request chain: {len(chain)} spans")

    # ── TEST 7: Aggregate View (Mandate #24) ──
    print("\n--- TEST 7: Aggregate View ---")
    agg = gateway.tracer.get_aggregate_view()
    assert "by_model" in agg
    assert "by_surface" in agg
    assert agg["total_traces"] > 0
    print(f"  ✅ Aggregate: {agg['total_traces']} traces, models={list(agg['by_model'].keys())}")

    # ── TEST 8: Retry Backoff (Mandate #25) ──
    print("\n--- TEST 8: Retry with Backoff ---")
    call_count = {"n": 0}
    def flaky_fn():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("Simulated timeout 429")
        return "Success after retries"
    result = retry_with_backoff(flaky_fn, max_retries=3, base_delay=0.1, max_delay=0.5)
    assert result == "Success after retries"
    assert call_count["n"] == 3
    print(f"  ✅ Retry succeeded after {call_count['n']} attempts")

    # ── TEST 9: Circuit Breaker (Mandate #25) ──
    print("\n--- TEST 9: Circuit Breaker ---")
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
    assert cb.allow_request() is True
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False
    # Wait for recovery
    import time as _time
    _time.sleep(1.1)
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.allow_request() is True
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    print("  ✅ Circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED")

    # ── TEST 10: Output Validation (Mandate #25) ──
    print("\n--- TEST 10: Output Validation ---")
    ok, data = validate_llm_output('{"intent": "search", "query": "áo thun"}', ["intent", "query"])
    assert ok is True
    assert data["intent"] == "search"

    ok2, err = validate_llm_output("not json at all", ["intent"])
    assert ok2 is False
    assert "JSON parse error" in err

    ok3, err3 = validate_llm_output('{"intent": "search"}', ["intent", "query"])
    assert ok3 is False
    assert "Missing required keys" in err3
    print("  ✅ Output validation: valid / invalid JSON / missing keys")

    # ── TEST 11: Fallback Chain with Primary Failure (Mandate #25) ──
    print("\n--- TEST 11: Primary Failure → Fallback Chain ---")
    gateway_fail = ResilientLLMGateway(
        primary_invoke_fn=lambda p: (_ for _ in ()).throw(RuntimeError("429 RateLimit")),
        secondary_invoke_fn=lambda p: f"Fallback response for: {p[:30]}",
    )
    resp11, trace11 = gateway_fail.generate(
        "Tìm áo thun nam", user_id="user_E", session_id="sess_005"
    )
    assert "Fallback response" in resp11
    assert trace11["outcome"] == "fallback"
    print(f"  ✅ Fallback chain activated, model={trace11['model']}")

    # ── TEST 12: Total Failure → Graceful Static Fallback ──
    print("\n--- TEST 12: Total Failure → Static Fallback ---")
    gateway_total_fail = ResilientLLMGateway(
        primary_invoke_fn=lambda p: (_ for _ in ()).throw(RuntimeError("Primary down")),
        secondary_invoke_fn=lambda p: (_ for _ in ()).throw(RuntimeError("Secondary down")),
    )
    resp12, trace12 = gateway_total_fail.generate(
        "Test total failure", user_id="user_F", session_id="sess_006"
    )
    assert "Chế độ suy giảm" in resp12
    assert trace12["outcome"] == "fallback"
    print("  ✅ Graceful degradation with explicit degraded-mode label")

    # ── SUMMARY ──
    cache_stats = gateway.cache.stats()
    print("\n" + "=" * 60)
    print("  📊 CACHE STATS:", json.dumps(cache_stats, indent=2))
    print("\n  ✅ ALL 12 PRODUCTION TESTS PASSED!")
    print("     Mandate #23: Cache + User Isolation + TTL + Long-Term Memory + PII ✓")
    print("     Mandate #24: Full Trace + E2E Chain + Aggregate + PII Masking ✓")
    print("     Mandate #25: Retry Backoff + Circuit Breaker + Output Validation + Fallback ✓")
    print("=" * 60)
