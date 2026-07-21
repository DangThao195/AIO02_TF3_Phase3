"""Cost meter (C5) — showback at request level (FinOps for AI), measured AT the gateway.

The llm service is a black box (not OTel-instrumented), so cost is metered on the caller
side from the OpenAI-compatible `usage` field. Prices from cost/model-pricing.yaml (mock = $0).
Tags: feature + model (NOT product_id — that is a cardinality bomb; it lives in logs).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..common.metrics import COST_TOKENS, COST_USD


class CostMeter:
    def __init__(self, pricing_path: str | Path | None = None):
        self._pricing = self._load_pricing(pricing_path)

    def _load_pricing(self, path) -> dict:
        if path and Path(path).exists():
            return yaml.safe_load(Path(path).read_text()) or {}
        return {}

    def record(self, *, model: str, feature: str, input_tokens: int, output_tokens: int) -> float:
        """Record usage, return USD for this call (0.0 for mock)."""
        COST_TOKENS.labels(direction="input", model=model, feature=feature).inc(input_tokens)
        COST_TOKENS.labels(direction="output", model=model, feature=feature).inc(output_tokens)

        price = self._pricing.get(model, {})
        usd = (
            input_tokens / 1000 * price.get("input_per_1k", 0.0)
            + output_tokens / 1000 * price.get("output_per_1k", 0.0)
        )
        if usd:
            COST_USD.labels(model=model, feature=feature).inc(usd)
        return usd
