"""Prometheus metrics the engine emits — the ONLY way SLAs in the contracts become real.

"Không đo được = không tồn tại" (README TF3). Every commitment in C4/C5/C6 maps to a
metric here. Cardinality rule (observability best practice): labels are small fixed sets
only — never product_id / user_id / request_id (those go to logs & trace exemplars).
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


GATEWAY_REQUESTS = Counter(
    "ai_gateway_requests_total",
    "AI gateway calls by outcome",
    ["outcome"],
)
GATEWAY_LATENCY = Histogram(
    "ai_gateway_latency_seconds",
    "AI gateway call latency (contribution of AI to page latency)",
    buckets=(0.05, 0.1, 0.25, 0.4, 0.8, 1.0, 2.0),
)
CACHE_HIT_RATIO = Gauge("ai_cache_hit_ratio", "Rolling cache hit ratio (cost & latency lever)")
GUARDRAIL_BLOCK = Counter(
    "ai_guardrail_block_total",
    "Summaries blocked by faithfulness guardrail",
    ["reason"],
)
BREAKER_STATE = Gauge("ai_breaker_state", "0=closed 1=half-open 2=open")


COST_TOKENS = Counter(
    "ai_cost_tokens_total", "Tokens consumed", ["direction", "model", "feature"]
)
COST_USD = Counter("ai_cost_usd_total", "Cumulative AI cost in USD", ["model", "feature"])
COST_PER_REQUEST = Gauge("ai_cost_per_request_usd", "Rolling 1h avg cost per summary")


ALERTS_EMITTED = Counter("ai_engine_alerts_total", "Alerts emitted", ["severity", "source_layer"])
DETECTION_LATENCY = Histogram(
    "ai_engine_detection_latency_seconds",
    "Incident-inject to critical-alert latency (SLA <= 3 min, C2)",
    buckets=(30, 60, 120, 180, 300, 600),
)
ENGINE_BLIND = Gauge(
    "ai_engine_blind", "1 if a telemetry source is unreachable (C1 fail-mode meta-alert)"
)
