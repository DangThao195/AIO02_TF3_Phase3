import time
import uuid
import hashlib
import datetime
import logging
from typing import Optional

from src.telemetry.models import ModelTrace
from src.telemetry.storage import JsonlTraceStore

logger = logging.getLogger("telemetry.tracer")

_NOVA_LITE_INPUT_PRICE_PER_TOKEN = 0.00006 / 1000
_NOVA_LITE_OUTPUT_PRICE_PER_TOKEN = 0.00024 / 1000


def _hash_id(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens * _NOVA_LITE_INPUT_PRICE_PER_TOKEN + completion_tokens * _NOVA_LITE_OUTPUT_PRICE_PER_TOKEN


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


class ModelTracer:
    def __init__(self, logs_dir: str = "logs/traces"):
        self._store = JsonlTraceStore(logs_dir)

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
        extra_metadata: Optional[dict] = None,
    ) -> None:
        pt, ct, tt = _extract_usage(response) if response else (0, 0, 0)
        model_name = _extract_model(response) or os.getenv("BEDROCK_MODEL_ID")
        cost = _estimate_cost(pt, ct)
        masked_prompt = _sanitize_pii(prompt_text)[:500] if prompt_text else ""
        masked_resp = _sanitize_pii(_extract_text(response))[:500] if response else ""

        record = ModelTrace(
            trace_id=trace_id,
            request_id=request_id,
            parent_span_id=None,
            surface=surface,
            layer=layer,
            model=model_name,
            model_version="",
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
            tool_calls=None,
            prompt_preview=masked_prompt,
            response_preview=masked_resp,
            prompt_masked=bool(prompt_text),
            response_masked=bool(masked_resp),
            metadata=extra_metadata or {},
        )
        self._store.save(record.to_dict())
        logger.debug("[TRACE] %s | %s | %s | %dms | %d tokens | $%.6f",
                     trace_id[:8], layer, outcome, latency_ms, tt, cost)


_tracer_instance: Optional[ModelTracer] = None


def get_tracer() -> ModelTracer:
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = ModelTracer()
    return _tracer_instance


def reset_tracer():
    global _tracer_instance
    _tracer_instance = None
