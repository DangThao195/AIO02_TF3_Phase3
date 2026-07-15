"""Central config — read from env only (C1). No hardcoded endpoints.

CDO owns the observability stack; AIO reads its endpoints via env so that when CDO
refactors namespaces/services, only env changes — engine code does not.
See contracts/C1-telemetry-access.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Load local .env file immediately at module import time to avoid configuration race condition
try:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#") and "=" in line:
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
except Exception:
    pass


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
    # Backend = AWS Bedrock (us-east-1). Route: baseline rẻ (volume cao) + heavy cho câu khó/RCA.
    # Mock dev vẫn dùng "techx-llm". Đổi provider = đổi env, code không đổi (C4).
    llm_model: str = os.environ.get("LLM_MODEL", "techx-llm")                    # baseline
    # Route heavy TẠM dùng Nova Lite: Opus 4.8 chưa được cấp quyền (AccessDenied, 2026-07-10).
    # Nâng cấp tức thì (đã có quyền, không cần chờ AWS): đặt LLM_MODEL_HEAVY=
    #   us.anthropic.claude-sonnet-4-5-20250929-v1:0  (reasoning mạnh cho câu khó/RCA), hoặc
    #   amazon.nova-pro-v1:0. Đổi env, code không đổi (C4).
    llm_model_heavy: str = os.environ.get(
        "LLM_MODEL_HEAVY", "amazon.nova-lite-v1:0")                              # route câu khó/RCA
    bedrock_region: str = os.environ.get("AWS_BEDROCK_REGION", "us-east-1")
    per_call_timeout_ms: int = int(os.environ.get("AI_LLM_TIMEOUT_MS", "800"))
    total_budget_ms: int = int(os.environ.get("AI_TOTAL_BUDGET_MS", "2000"))
    max_retries: int = int(os.environ.get("AI_MAX_RETRIES", "2"))
    retry_budget_ratio: float = float(os.environ.get("AI_RETRY_BUDGET_RATIO", "0.20"))
    breaker_fail_threshold: int = int(os.environ.get("AI_BREAKER_FAILS", "5"))
    breaker_open_seconds: int = int(os.environ.get("AI_BREAKER_OPEN_S", "60"))
    cache_ttl_seconds: int = int(os.environ.get("AI_CACHE_TTL_S", "86400"))


@dataclass(frozen=True)
class CostConfig:
    """C5 — AI cost showback + budget guardrail.

    `weekly_budget_usd` is the ONE number CDO Cost pillar must supply (via env, backed by an
    ADR). Until they do, this default is AIO's proposal; alerts fire at 80% (warning) and
    100% (critical) of it.
    """

    weekly_budget_usd: float = float(os.environ.get("AI_BUDGET_WEEKLY_USD", "50"))
    warn_ratio: float = float(os.environ.get("AI_BUDGET_WARN_RATIO", "0.80"))
    pricing_path: str = os.environ.get(
        "AI_PRICING_PATH",
        str(__import__("pathlib").Path(__file__).resolve().parents[3] / "cost" / "model-pricing.yaml"),
    )


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
class SlackConfig:
    """Slack App configuration (C6 Approval Gate / AIOps-06)."""

    app_id: str | None = os.environ.get("SLACK_APP_ID")
    client_id: str | None = os.environ.get("SLACK_CLIENT_ID")
    client_secret: str | None = os.environ.get("SLACK_CLIENT_SECRET")
    signing_secret: str | None = os.environ.get("SLACK_SIGNING_SECRET")
    verification_token: str | None = os.environ.get("SLACK_VERIFICATION_TOKEN")
    bot_token: str | None = os.environ.get("SLACK_BOT_TOKEN")
    channel_id: str | None = os.environ.get("SLACK_CHANNEL_ID")


@dataclass(frozen=True)
class Config:
    telemetry: TelemetryConfig = TelemetryConfig()
    gateway: GatewayConfig = GatewayConfig()
    slo: SLOConfig = SLOConfig()
    alert: AlertConfig = AlertConfig()
    slack: SlackConfig = SlackConfig()
    cost: CostConfig = CostConfig()


def load_config() -> Config:
    return Config()
