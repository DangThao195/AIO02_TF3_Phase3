"""Best-effort runtime trace storage for Product Reviews AI calls.

The trace intentionally stores black-box metadata only: ids, hashes, model
usage, latency and outcomes. It must not persist raw prompts, raw reviews, or
customer-visible answer text.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from guardrails.cache import redis_client

logger = logging.getLogger("guardrails.llm_trace")

TRACE_KEY_PREFIX = "product_reviews:llm_trace:"
TRACE_TTL_SECONDS = int(os.environ.get("PRODUCT_REVIEWS_TRACE_TTL_SECONDS", "86400"))
TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")

_usage_local = threading.local()

# Public Nova pricing used only for coarse audit estimates in runtime traces.
# Unit is USD per 1M tokens.
_PRICE_PER_1M_TOKENS = {
    "amazon.nova-lite-v1:0": {"input": 0.06, "output": 0.24},
    "amazon.nova-micro-v1:0": {"input": 0.035, "output": 0.14},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_trace_id() -> Tuple[str, str]:
    """Return the active OTel trace id, with a safe generated fallback."""
    try:
        from opentelemetry import trace as otel_trace

        span_context = otel_trace.get_current_span().get_span_context()
        if span_context and span_context.is_valid:
            return f"{span_context.trace_id:032x}", "otel"
    except Exception as exc:
        logger.debug("Unable to read current OTel trace id: %s", exc)
    return uuid.uuid4().hex, "generated"


def attach_trace_metadata(context: Any, trace_id: str) -> None:
    """Expose trace id to gRPC callers via trailing metadata."""
    if context is None:
        return
    try:
        context.set_trailing_metadata((("x-trace-id", trace_id),))
    except Exception as exc:
        logger.debug("Unable to attach x-trace-id metadata: %s", exc)


def question_sha256(question: str) -> str:
    return hashlib.sha256((question or "").encode("utf-8")).hexdigest()


def response_sha256(response_text: str) -> str:
    return hashlib.sha256((response_text or "").encode("utf-8")).hexdigest()


def estimate_cost_usd(model: Optional[str], input_tokens: int, output_tokens: int) -> Optional[float]:
    pricing = _PRICE_PER_1M_TOKENS.get((model or "").strip())
    if not pricing:
        return None
    cost = (input_tokens / 1_000_000 * pricing["input"]) + (
        output_tokens / 1_000_000 * pricing["output"]
    )
    return round(cost, 8)


def set_last_usage(
    role: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    latency_ms: float,
) -> None:
    call_index = len(getattr(_usage_local, f"{role}_usage_calls", []) or []) + 1
    usage = {
        "call_index": call_index,
        "provider": provider,
        "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "estimated_cost_usd": estimate_cost_usd(model, int(input_tokens or 0), int(output_tokens or 0)),
    }
    calls = getattr(_usage_local, f"{role}_usage_calls", []) or []
    calls.append(usage)
    setattr(_usage_local, f"{role}_usage_calls", calls)
    setattr(_usage_local, f"last_{role}_usage", usage)


def get_last_usage(role: str) -> Optional[Dict[str, Any]]:
    usage = getattr(_usage_local, f"last_{role}_usage", None)
    return copy.deepcopy(usage) if usage else None


def get_usage_trace(role: str) -> Optional[Dict[str, Any]]:
    calls = copy.deepcopy(getattr(_usage_local, f"{role}_usage_calls", []) or [])
    if not calls:
        return None

    total_input = sum(call.get("input_tokens", 0) or 0 for call in calls)
    total_output = sum(call.get("output_tokens", 0) or 0 for call in calls)
    total_tokens = sum(call.get("total_tokens", 0) or 0 for call in calls)
    total_latency = sum(call.get("latency_ms", 0.0) or 0.0 for call in calls)
    known_costs = [
        call.get("estimated_cost_usd")
        for call in calls
        if call.get("estimated_cost_usd") is not None
    ]
    estimated_cost = round(sum(known_costs), 8) if known_costs else None

    return {
        "calls": calls,
        "total_usage": {
            "call_count": len(calls),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_tokens,
            "latency_ms": round(total_latency, 2),
            "estimated_cost_usd": estimated_cost,
            "cost_source": "static_price_table" if estimated_cost is not None else None,
        },
    }


def clear_last_usage() -> None:
    for role in ("candidate", "judge"):
        for attr in (f"last_{role}_usage", f"{role}_usage_calls"):
            if hasattr(_usage_local, attr):
                delattr(_usage_local, attr)


def build_runtime_trace_record(
    trace_id: str,
    trace_id_source: str,
    product_id: str,
    question: str,
    candidate_provider: Optional[str],
    candidate_model: Optional[str],
    judge_provider: Optional[str],
    judge_model: Optional[str],
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "trace_id": trace_id,
        "trace_id_source": trace_id_source,
        "created_at": _utc_now_iso(),
        "service": "product-reviews",
        "operation": "AskProductAIAssistant",
        "product_id": product_id,
        "question_sha256": question_sha256(question),
        "candidate": {
            "provider": candidate_provider,
            "model": candidate_model,
            "calls": [],
            "total_usage": None,
        },
        "judge": {
            "provider": judge_provider,
            "model": judge_model,
            "calls": [],
            "total_usage": None,
            "status": None,
        },
        "guardrails": {
            "input_safe": None,
            "output_filtered": True,
            "runtime_fidelity_gate": None,
        },
        "cache": {
            "hit": False,
            "key_sha256": None,
            "source_trace_id": None,
            "source_response_sha256": None,
        },
        "outcome": "unknown",
        "fallback_reason": None,
        "response_class": None,
        "response_sha256": None,
        "total_latency_ms": None,
    }


def classify_response(response_text: str, fallback_message: str, unverified_message: str, out_of_scope_message: str, no_info_message: str) -> str:
    if response_text == fallback_message:
        return "fallback"
    if response_text == unverified_message:
        return "unverified"
    if response_text == out_of_scope_message:
        return "out_of_scope"
    if response_text == no_info_message:
        return "no_info"
    return "grounded_answer"


def finalize_runtime_trace(
    record: Dict[str, Any],
    started_perf_counter: float,
    response_text: str,
    *,
    outcome: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    cache_hit: bool = False,
    judge_status: Optional[str] = None,
    cache_key: Optional[str] = None,
    fallback_message: str,
    unverified_message: str,
    out_of_scope_message: str,
    no_info_message: str,
) -> Dict[str, Any]:
    response_class = classify_response(
        response_text,
        fallback_message,
        unverified_message,
        out_of_scope_message,
        no_info_message,
    )
    record["completed_at"] = _utc_now_iso()
    record["total_latency_ms"] = round((time.perf_counter() - started_perf_counter) * 1000, 2)
    record["response_class"] = response_class
    record["response_sha256"] = response_sha256(response_text)
    record["outcome"] = outcome or response_class
    record["fallback_reason"] = fallback_reason
    record["cache"]["hit"] = bool(cache_hit)
    record["cache"]["key_sha256"] = hashlib.sha256(cache_key.encode("utf-8")).hexdigest() if cache_key else None
    candidate_usage = get_usage_trace("candidate")
    judge_usage = get_usage_trace("judge")
    if candidate_usage:
        record["candidate"].update(candidate_usage)
    if judge_usage:
        record["judge"].update(judge_usage)
    record["judge"]["status"] = judge_status
    record["guardrails"]["runtime_fidelity_gate"] = judge_status
    if response_class in {"unverified", "fallback"}:
        record["guardrails"]["output_filtered"] = True
    return record


def _trace_key(trace_id: str) -> str:
    return f"{TRACE_KEY_PREFIX}{trace_id}"


def write_llm_trace(record: Dict[str, Any], ttl_seconds: int = TRACE_TTL_SECONDS) -> bool:
    """Persist a trace record to Redis. Fail-open by design."""
    if not redis_client:
        return False
    trace_id = str(record.get("trace_id") or "")
    if not TRACE_ID_RE.match(trace_id):
        logger.warning("Skipping LLM trace write due to invalid trace_id=%r", trace_id)
        return False
    try:
        redis_client.setex(_trace_key(trace_id), ttl_seconds, json.dumps(record, ensure_ascii=False))
        logger.info("LLM_TRACE_SAVED trace_id=%s redis_key=%s ttl_seconds=%s", trace_id, _trace_key(trace_id), ttl_seconds)
        return True
    except Exception as exc:
        logger.warning("Failed to write LLM trace to Redis: %s", exc)
        return False


def read_llm_trace(trace_id: str) -> Optional[Dict[str, Any]]:
    """Read a trace record from Redis for a debug/audit endpoint."""
    if not redis_client or not TRACE_ID_RE.match(trace_id or ""):
        return None
    try:
        payload = redis_client.get(_trace_key(trace_id))
        if not payload:
            return None
        return json.loads(payload)
    except Exception as exc:
        logger.warning("Failed to read LLM trace from Redis: %s", exc)
        return None
