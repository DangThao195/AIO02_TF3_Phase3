"""Central config — read from env only (C1). No hardcoded endpoints.

CDO owns the observability stack; AIO reads its endpoints via env so that when CDO
refactors namespaces/services, only env changes — engine code does not.
See contracts/C1-telemetry-access.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise RuntimeError(f"required env var {key} is not set")
    return val


@dataclass(frozen=True)
class TelemetryConfig:
    """Read-only telemetry endpoints (C1). Defaults match in-cluster chart service names."""

    prometheus_url: str = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
    opensearch_url: str = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
    jaeger_url: str = os.environ.get("JAEGER_URL", "http://jaeger-query:16686")

    query_timeout_s: float = float(os.environ.get("TELEMETRY_QUERY_TIMEOUT_S", "10"))


@dataclass(frozen=True)
class GatewayConfig:
    """AI Gateway (C4) — latency budget + resilience knobs that protect storefront p95 < 1s."""

    llm_base_url: str = os.environ.get("LLM_BASE_URL", "http://llm:8000/v1")
    llm_model: str = os.environ.get("LLM_MODEL", "techx-llm")
    per_call_timeout_ms: int = int(os.environ.get("AI_LLM_TIMEOUT_MS", "800"))
    total_budget_ms: int = int(os.environ.get("AI_TOTAL_BUDGET_MS", "2000"))
    max_retries: int = int(os.environ.get("AI_MAX_RETRIES", "2"))
    retry_budget_ratio: float = float(os.environ.get("AI_RETRY_BUDGET_RATIO", "0.20"))
    breaker_fail_threshold: int = int(os.environ.get("AI_BREAKER_FAILS", "5"))
    breaker_open_seconds: int = int(os.environ.get("AI_BREAKER_OPEN_S", "60"))
    cache_ttl_seconds: int = int(os.environ.get("AI_CACHE_TTL_S", "86400"))


@dataclass(frozen=True)
class SLOConfig:
    """SLO targets from onboarding/SLO.md — drive burn-rate thresholds (C2)."""

    checkout_target: float = float(os.environ.get("SLO_CHECKOUT", "0.99"))
    browse_target: float = float(os.environ.get("SLO_BROWSE", "0.995"))
    cart_target: float = float(os.environ.get("SLO_CART", "0.995"))


@dataclass(frozen=True)
class AlertConfig:
    """C2 alert delivery."""

    webhook_url: str | None = os.environ.get("ALERT_WEBHOOK_URL")
    tf_name: str = os.environ.get("TF_NAME", "TF3")


@dataclass(frozen=True)
class Config:
    telemetry: TelemetryConfig = TelemetryConfig()
    gateway: GatewayConfig = GatewayConfig()
    slo: SLOConfig = SLOConfig()
    alert: AlertConfig = AlertConfig()


def load_config() -> Config:
    return Config()
