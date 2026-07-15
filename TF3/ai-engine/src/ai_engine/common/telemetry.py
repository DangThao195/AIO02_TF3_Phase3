"""Read-only telemetry clients (C1). AIO reads, never writes (except its own ai-engine-* index).

Failure mode contract (C1): if a source is unreachable the engine does NOT go silent —
it flips the `ai_engine_blind` gauge and callers emit a warning meta-alert. Never hang.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import TelemetryConfig
from .metrics import ENGINE_BLIND

log = logging.getLogger("ai_engine.telemetry")


class TelemetryError(Exception):
    """Raised when a telemetry source is unreachable/slow — caller decides fallback."""


class PrometheusClient:
    """PromQL over the HTTP API. Used by burn-rate (C2), anomaly, cost read-back."""

    def __init__(self, cfg: TelemetryConfig, client: httpx.AsyncClient | None = None):
        self._url = cfg.prometheus_url.rstrip("/")
        self._timeout = cfg.query_timeout_s
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    async def instant(self, query: str) -> list[dict[str, Any]]:
        """Instant query -> list of {metric, value}. Empty list if no data."""
        try:
            resp = await self._client.get(
                f"{self._url}/api/v1/query", params={"query": query}
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            ENGINE_BLIND.set(1)
            raise TelemetryError(f"prometheus instant query failed: {exc}") from exc
        ENGINE_BLIND.set(0)
        data = resp.json()
        if data.get("status") != "success":
            raise TelemetryError(f"prometheus returned {data.get('status')}")
        return data["data"]["result"]

    async def scalar(self, query: str, default: float | None = None) -> float | None:
        """Convenience: first result value as float, else default."""
        results = await self.instant(query)
        if not results:
            return default
        return float(results[0]["value"][1])


class OpenSearchClient:
    """Log search for RCA evidence (C3). Read-only on product indices."""

    def __init__(self, cfg: TelemetryConfig, client: httpx.AsyncClient | None = None):
        self._url = cfg.opensearch_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=cfg.query_timeout_s)

    async def search(self, index: str, body: dict) -> dict:
        try:
            resp = await self._client.post(f"{self._url}/{index}/_search", json=body)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:

            raise TelemetryError(f"opensearch search failed: {exc}") from exc
        return resp.json()


class JaegerClient:
    """Trace lookup for exemplar traces in RCA (C3)."""

    def __init__(self, cfg: TelemetryConfig, client: httpx.AsyncClient | None = None):
        self._url = cfg.jaeger_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=cfg.query_timeout_s)

    async def find_error_traces(self, service: str, limit: int = 5) -> list[dict]:
        try:
            resp = await self._client.get(
                f"{self._url}/api/traces",
                params={"service": service, "tags": '{"error":"true"}', "limit": limit},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise TelemetryError(f"jaeger query failed: {exc}") from exc
        return resp.json().get("data", [])
