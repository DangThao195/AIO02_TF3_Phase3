"""AIOps engine loop — the standalone service (ns ai-engine) that wires detection together.

Every tick: read SLIs (burn-rate detector) -> correlate into incidents -> emit C2 alerts.
Runs OFF the request critical path (ADR-001). Exposes /metrics for Prometheus scrape and
/healthz for the kubelet probe. If telemetry is blind, it flips ai_engine_blind and keeps
running (never silent) — the C1 failure-mode contract.

This is the reference loop; the AIE gateway/guardrail run in-process inside product-reviews,
not here.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from prometheus_client import make_asgi_app

from .aiops.alert_emitter import AlertEmitter
from .aiops.correlator import Correlator
from .aiops.detector_anomaly import AnomalyDetector, default_anomaly_metrics
from .aiops.detector_burnrate import BurnRateDetector, default_slos
from .aiops.rca_assistant import RCAAssistant
from .common.config import Config, load_config
from .common.metrics import DETECTION_LATENCY
from .common.telemetry import JaegerClient, OpenSearchClient, PrometheusClient

log = logging.getLogger("ai_engine.server")


class AIOpsEngine:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        prom = PrometheusClient(cfg.telemetry)
        self._detector = BurnRateDetector(prom, default_slos(cfg.slo))
        self._anomaly = AnomalyDetector(prom, default_anomaly_metrics())
        self._correlator = Correlator()
        self._emitter = AlertEmitter(cfg.alert)
        self._rca = RCAAssistant(
            prom, OpenSearchClient(cfg.telemetry), JaegerClient(cfg.telemetry),
        )

    async def tick(self) -> int:
        """One detection cycle. Returns number of incidents emitted.

        Layer 1 (burn-rate) + layer 2 (anomaly) feed the correlator, which folds them into
        incidents. Each incident is emitted (C2) and gets a draft Evidence Pack (C3).
        """
        started = datetime.now(timezone.utc)
        signals = await self._detector.evaluate()
        anomalies = await self._anomaly.evaluate()
        incidents = self._correlator.correlate(signals, anomalies)
        for incident in incidents:
            alert = await self._emitter.emit(incident)
            if alert.severity.value == "critical":
                DETECTION_LATENCY.observe((datetime.now(timezone.utc) - started).total_seconds())

                try:
                    pack = await self._rca.build(incident)
                    log.info("evidence pack ready for %s (%d hypotheses)",
                             incident.incident_id, len(pack.hypotheses))
                except Exception:
                    log.exception("rca build failed for %s", incident.incident_id)
        return len(incidents)

    async def run(self, interval_s: int = 30, digest_every_s: int = 600) -> None:
        log.info("AIOps engine loop starting (interval=%ss)", interval_s)
        last_digest = 0.0
        while True:
            try:
                n = await self.tick()
                if n:
                    log.info("emitted %d incident(s)", n)
            except Exception:
                log.exception("tick failed; continuing")
            loop = asyncio.get_event_loop().time()
            if loop - last_digest >= digest_every_s:
                await self._emitter.flush_digest()
                last_digest = loop
            await asyncio.sleep(interval_s)


def create_app(cfg: Config | None = None):
    cfg = cfg or load_config()
    metrics_app = make_asgi_app()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        path = scope.get("path", "")
        if path.startswith("/metrics"):
            return await metrics_app(scope, receive, send)
        if path == "/healthz":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})
            return
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"not found"})

    return app


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    engine = AIOpsEngine(cfg)
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
