import os
import time
import uuid
import hashlib
import datetime
import asyncio
import logging
import threading
from typing import Optional

from src.telemetry.models import ModelTrace
from src.telemetry.storage import JsonlTraceStore

logger = logging.getLogger("telemetry.tracer")

# ── Per-model pricing (USD per token) — Bedrock on-demand, ap-southeast-1 ──
# Source: https://aws.amazon.com/bedrock/pricing/
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_price_per_token, output_price_per_token)
    "amazon.nova-lite-v1:0":  (0.00006 / 1000, 0.00024 / 1000),
    "amazon.nova-pro-v1:0":   (0.0008  / 1000, 0.0032  / 1000),
    "amazon.nova-micro-v1:0": (0.000035/ 1000, 0.00014 / 1000),
    "amazon.titan-text-express-v1": (0.0002 / 1000, 0.0006 / 1000),
    # Fallback default (Nova Lite)
    "__default__": (0.00006 / 1000, 0.00024 / 1000),
}


def _get_model_pricing(model_id: str) -> tuple[float, float]:
    """Return (input_price, output_price) per token for the given model."""
    if not model_id:
        return _MODEL_PRICING["__default__"]
    # Exact match first
    if model_id in _MODEL_PRICING:
        return _MODEL_PRICING[model_id]
    # Prefix/substring match (e.g. cross-region inference profiles)
    for key, prices in _MODEL_PRICING.items():
        if key != "__default__" and key in model_id:
            return prices
    return _MODEL_PRICING["__default__"]


def _hash_id(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _estimate_cost(prompt_tokens: int, completion_tokens: int, model_id: str = "") -> float:
    inp_price, out_price = _get_model_pricing(model_id)
    return prompt_tokens * inp_price + completion_tokens * out_price


def _extract_model_version(model_id: str) -> str:
    """Extract a human-readable version tag from Bedrock model_id strings."""
    if not model_id:
        return ""
    # e.g. "amazon.nova-pro-v1:0" → "v1:0"
    import re
    m = re.search(r"(v[\d]+[^:]*(?::\d+)?)", model_id)
    return m.group(1) if m else ""


def _extract_usage(response) -> tuple:
    try:
        if hasattr(response, "usage_metadata"):
            u = response.usage_metadata
            if isinstance(u, dict):
                return u.get("input_tokens", 0), u.get("output_tokens", 0), u.get("total_tokens", 0)
    except Exception:
        pass
    try:
        if hasattr(response, "response_metadata"):
            m = response.response_metadata
            if isinstance(m, dict):
                usage = m.get("usage", {})
                if usage:
                    return usage.get("inputTokens", 0), usage.get("outputTokens", 0), usage.get("totalTokens", 0)
    except Exception:
        pass
    return 0, 0, 0


def _extract_model(response) -> str:
    try:
        if hasattr(response, "response_metadata"):
            m = response.response_metadata
            if isinstance(m, dict):
                mid = m.get("model_id") or m.get("ModelId") or ""
                return str(mid)
    except Exception:
        pass
    return ""


def _extract_text(response) -> str:
    try:
        if hasattr(response, "content"):
            c = response.content
            if isinstance(c, list):
                parts = []
                for part in c:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(part["text"])
                    elif isinstance(part, str):
                        parts.append(part)
                    elif hasattr(part, "text"):
                        parts.append(part.text)
                return "".join(parts)
            return str(c)
    except Exception:
        pass
    return str(response) if response else ""


def _sanitize_pii(text: str) -> str:
    try:
        from src.guardrails.input_filter import sanitize_pii_from_input
        return sanitize_pii_from_input(text)
    except Exception:
        return text


# ── Background writer thread for async trace writes ──────────────────────────
_write_queue: list = []
_write_lock = threading.Lock()
_flush_event = threading.Event()


def _enqueue_write(store: "JsonlTraceStore", record_dict: dict) -> None:
    """Queue a trace record for background writing (non-blocking)."""
    with _write_lock:
        _write_queue.append((store, record_dict))
    _flush_event.set()


def _background_writer():
    """Worker thread that drains the write queue."""
    while True:
        _flush_event.wait(timeout=0.5)
        _flush_event.clear()
        with _write_lock:
            batch = list(_write_queue)
            _write_queue.clear()
        for store, record_dict in batch:
            try:
                store.save(record_dict)
            except Exception as e:
                logger.warning("[TRACE] Background write failed: %s", e)


_bg_writer_thread: Optional[threading.Thread] = None


def _ensure_bg_writer():
    global _bg_writer_thread
    if _bg_writer_thread is None or not _bg_writer_thread.is_alive():
        _bg_writer_thread = threading.Thread(
            target=_background_writer, daemon=True, name="trace-writer"
        )
        _bg_writer_thread.start()


class ModelTracer:
    def __init__(self, logs_dir: str = "logs/traces"):
        self._store = JsonlTraceStore(logs_dir)
        _ensure_bg_writer()

    def create_request_id(self) -> str:
        return str(uuid.uuid4())

    def record_call(
        self,
        *,
        trace_id: str,
        request_id: str,
        layer: str,
        session_id: str = "",
        user_id: str = "",
        surface: str = "copilot",
        prompt_text: str = "",
        response=None,
        error: Optional[str] = None,
        outcome: str = "ok",
        latency_ms: int = 0,
        tool_calls: Optional[list] = None,
        extra_metadata: Optional[dict] = None,
    ) -> None:
        pt, ct, tt = _extract_usage(response) if response else (0, 0, 0)
        model_name = _extract_model(response) or os.getenv("BEDROCK_MODEL_ID", "")
        model_version = _extract_model_version(model_name)
        # Cost calculated per actual model, not hard-coded
        cost = _estimate_cost(pt, ct, model_name)
        masked_prompt = _sanitize_pii(prompt_text)[:500] if prompt_text else ""
        masked_resp = _sanitize_pii(_extract_text(response))[:500] if response else ""

        record = ModelTrace(
            trace_id=trace_id,
            request_id=request_id,
            parent_span_id=None,
            surface=surface,
            layer=layer,
            model=model_name,
            model_version=model_version,
            session_id=_hash_id(session_id) if session_id else "",
            user_id=_hash_id(user_id) if user_id else "",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            latency_ms=latency_ms,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            estimated_cost_usd=round(cost, 8),
            outcome=outcome,
            error=error,
            tool_calls=tool_calls,
            prompt_preview=masked_prompt,
            response_preview=masked_resp,
            prompt_masked=bool(prompt_text),
            response_masked=bool(masked_resp),
            metadata=extra_metadata or {},
        )
        # ── Write async off the hot path ──────────────────────────────────
        _enqueue_write(self._store, record.to_dict())
        logger.debug(
            "[TRACE] %s | %s | %s | %dms | %d tokens | $%.6f | model=%s version=%s",
            trace_id[:8], layer, outcome, latency_ms, tt, cost, model_name, model_version,
        )


_tracer_instance: Optional[ModelTracer] = None


def get_tracer() -> ModelTracer:
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = ModelTracer()
    return _tracer_instance


def reset_tracer():
    global _tracer_instance
    _tracer_instance = None
