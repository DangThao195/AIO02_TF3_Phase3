"""C2 alert emitter — turns an Incident into an AlertEvent and delivers it to on-call.

Every alert answers 3 questions at a glance: what hurts, how bad, what next (C2). It carries
copy-pasteable evidence (PromQL, Grafana link, log query) so on-call never opens the engine.

Storm control (C2 §Failure-modes): >20 alerts/hour flips to digest mode — one bulletin per
10 minutes — but criticals always pass through immediately.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from ..common.config import AlertConfig
from ..common.metrics import ALERTS_EMITTED
from ..common.schemas import AlertEvent, AlertEvidence, AlertWindows, Severity
from .correlator import Incident

log = logging.getLogger("ai_engine.alert_emitter")

_ACK = {Severity.CRITICAL: "5m", Severity.WARNING: "30m", Severity.INFO: None}
_RUNBOOK = {
    "checkout": "TF3/ai-engine/runbooks/RB-PAY-01.md",
    "cart": "TF3/ai-engine/runbooks/RB-CART-01.md",
}


def build_alert(incident: Incident, grafana_base: str = "http://frontend-proxy:8080/grafana") -> AlertEvent:
    """Pure: Incident -> AlertEvent. No I/O, fully testable."""
    sig = incident.primary
    now = datetime.now(timezone.utc)
    alert_id = f"{ 'TF3'}-{now:%Y%m%d}-{abs(hash(incident.incident_id)) % 10000:04d}"


    _SLI_RULE_SERVICES = {"checkout", "frontend", "cart"}
    if sig.service in _SLI_RULE_SERVICES:
        error_rule = f"sli:{sig.service}_error:ratio_rate{sig.short_window}"
    else:
        error_rule = (
            f'sum(rate(traces_span_metrics_calls_total{{service_name="{sig.service}",'
            f'status_code="STATUS_CODE_ERROR"}}[{sig.short_window}]))'
            f' / sum(rate(traces_span_metrics_calls_total{{service_name="{sig.service}"}}[{sig.short_window}]))'
        )
    log_services = " OR ".join(f"service:{s}" for s in incident.blast_radius) or f"service:{sig.service}"

    return AlertEvent(
        alert_id=alert_id,
        fingerprint=f"{sig.service}|{sig.sli}|{sig.source_layer.value}",
        severity=sig.severity,
        source_layer=sig.source_layer,
        service=sig.service,
        sli_impacted=sig.sli,
        slo_target=sig.target,
        current_value=round(1 - sig.error_ratio, 4),
        burn_rate=sig.burn_rate,
        windows=AlertWindows(long=sig.long_window, short=sig.short_window),
        starts_at=now,
        correlated_signals=incident.correlated_signals,
        probable_blast_radius=incident.blast_radius,
        evidence=AlertEvidence(
            promql=error_rule,
            grafana_panel=f"{grafana_base}/d/slo-{sig.service}",
            log_query=f"({log_services}) AND level:error AND @timestamp:[now-30m TO now]",
        ),
        suggested_action=_suggest(sig.service, incident.blast_radius),
        runbook_link=_RUNBOOK.get(sig.service),
        requires_ack_within=_ACK[sig.severity],
    )


def _suggest(service: str, blast: list[str]) -> str:
    if service == "checkout":
        return ("Kiểm tra downstream trước (payment/cart/kafka cùng cửa sổ?). "
                "Nếu payment nghẽn: xem runbook RB-PAY-01 (retry budget + fallback).")
    if service == "cart":
        return "Kiểm tra cart + valkey-cart. Xem readiness probe (flag failedReadinessProbe?)."
    return f"Kiểm tra {service} và blast radius {blast}. Xem Evidence Pack sắp sinh (C3)."


class AlertEmitter:
    def __init__(self, cfg: AlertConfig, client: httpx.AsyncClient | None = None,
                 storm_threshold: int = 20, clock=time.time):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=5)
        self._storm_threshold = storm_threshold
        self._clock = clock
        self._emit_times: list[float] = []
        self._digest: list[AlertEvent] = []

    async def emit(self, incident: Incident) -> AlertEvent:
        alert = build_alert(incident)
        ALERTS_EMITTED.labels(severity=alert.severity.value, source_layer=alert.source_layer.value).inc()


        if alert.severity is Severity.CRITICAL or not self._in_storm():
            await self._deliver(alert)
        else:
            self._digest.append(alert)
        self._emit_times.append(self._clock())
        return alert

    def _in_storm(self) -> bool:
        cutoff = self._clock() - 3600
        self._emit_times = [t for t in self._emit_times if t > cutoff]
        return len(self._emit_times) >= self._storm_threshold

    async def _deliver(self, alert: AlertEvent) -> None:
        if not self._cfg.webhook_url:
            log.info("alert (no webhook configured): %s", alert.model_dump_json())
            return
        try:
            await self._client.post(self._cfg.webhook_url, json=alert.model_dump(mode="json"))
        except httpx.HTTPError as exc:

            log.warning("alert webhook delivery failed (dashboard fallback still shows it): %s", exc)

    async def flush_digest(self) -> list[AlertEvent]:
        """Called every 10 min by the loop: deliver the folded warning/info bulletin."""
        batch, self._digest = self._digest, []
        for a in batch:
            await self._deliver(a)
        return batch
