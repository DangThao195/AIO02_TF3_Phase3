"""C2 alert emitter — turns an Incident into an AlertEvent and delivers it to on-call.

Every alert answers 3 questions at a glance: what hurts, how bad, what next (C2). It carries
copy-pasteable evidence (PromQL, Grafana link, log query) so on-call never opens the engine.

Storm control (C2 §Failure-modes): >20 alerts/hour flips to digest mode — one bulletin per
10 minutes — but criticals always pass through immediately.
"""
from __future__ import annotations

import hashlib
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
    h = int(hashlib.sha256(incident.incident_id.encode("utf-8")).hexdigest(), 16)
    alert_id = f"TF3-{now:%Y%m%d}-{h % 10000:04d}"


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
                 storm_threshold: int = 20, clock=time.time, slack_cfg=None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=5)
        self._storm_threshold = storm_threshold
        self._clock = clock
        self._slack_cfg = slack_cfg
        self._emit_times: list[float] = []
        self._digest: list[AlertEvent] = []
        # C2.9: fingerprint -> the last firing AlertEvent, so we can send a matching resolved
        # notice when it stops firing. Keyed by fingerprint (service|sli|layer), not alert_id.
        self._active: dict[str, AlertEvent] = {}

    async def emit(self, incident: Incident) -> AlertEvent:
        alert = build_alert(incident)
        ALERTS_EMITTED.labels(severity=alert.severity.value, source_layer=alert.source_layer.value).inc()

        if alert.severity is Severity.CRITICAL or not self._in_storm():
            await self._deliver(alert)
        else:
            self._digest.append(alert)
        self._emit_times.append(self._clock())
        self._active[alert.fingerprint] = alert
        return alert

    async def reconcile(self, incidents) -> list[AlertEvent]:
        """C2.9 — after a tick, any previously-firing fingerprint NOT in this tick's incidents
        has recovered: emit a `status:"resolved"` notice so on-call gets closure, not silence.
        Returns the resolved events emitted."""
        still_firing = {build_alert(inc).fingerprint for inc in incidents}
        resolved: list[AlertEvent] = []
        for fp in list(self._active):
            if fp in still_firing:
                continue
            prev = self._active.pop(fp)
            notice = prev.model_copy(update={
                "status": "resolved",
                "ends_at": datetime.now(timezone.utc),
                "severity": prev.severity,
                "suggested_action": "Đã phục hồi — SLI về dưới ngưỡng. Đóng incident nếu không còn tín hiệu.",
            })
            await self._deliver_resolved(notice)
            resolved.append(notice)
        return resolved

    async def _deliver_resolved(self, alert: AlertEvent) -> None:
        # A resolved notice is low-noise: plain text so it never re-triggers the incident card.
        if self._slack_cfg and self._slack_cfg.bot_token and self._slack_cfg.channel_id:
            text = f"✅ *ĐÃ PHỤC HỒI* — `{alert.service}` / `{alert.sli_impacted}` về ngưỡng (alert {alert.alert_id})."
            try:
                headers = {"Authorization": f"Bearer {self._slack_cfg.bot_token}",
                           "Content-Type": "application/json; charset=utf-8"}
                await self._client.post("https://slack.com/api/chat.postMessage",
                                        json={"channel": self._slack_cfg.channel_id, "text": text},
                                        headers=headers)
                return
            except Exception as exc:
                log.warning("resolved-notice slack delivery failed: %s", exc)
        if self._cfg.webhook_url:
            try:
                await self._client.post(self._cfg.webhook_url, json=alert.model_dump(mode="json"))
            except httpx.HTTPError as exc:
                log.warning("resolved-notice webhook failed: %s", exc)
        else:
            log.info("resolved (no webhook): %s", alert.model_dump_json())

    def _in_storm(self) -> bool:
        cutoff = self._clock() - 3600
        self._emit_times = [t for t in self._emit_times if t > cutoff]
        return len(self._emit_times) >= self._storm_threshold

    async def _deliver(self, alert: AlertEvent) -> None:
        # Deliver via Slack Bot Token if configured
        if self._slack_cfg and self._slack_cfg.bot_token and self._slack_cfg.channel_id:
            try:
                payload = self._format_slack_message(alert)
                payload["channel"] = self._slack_cfg.channel_id
                headers = {
                    "Authorization": f"Bearer {self._slack_cfg.bot_token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                res = await self._client.post("https://slack.com/api/chat.postMessage", json=payload, headers=headers)
                log.info("Alert delivered via Slack Bot: %s", res.text)
                return
            except Exception as exc:
                log.warning("Slack Bot alert delivery failed: %s", exc)

        # Deliver via Incoming Webhook (Slack compatible format if URL matches)
        if not self._cfg.webhook_url:
            log.info("alert (no webhook configured): %s", alert.model_dump_json())
            return

        try:
            if "hooks.slack.com" in self._cfg.webhook_url:
                payload = self._format_slack_message(alert)
                await self._client.post(self._cfg.webhook_url, json=payload)
            else:
                await self._client.post(self._cfg.webhook_url, json=alert.model_dump(mode="json"))
        except httpx.HTTPError as exc:
            log.warning("alert webhook delivery failed (dashboard fallback still shows it): %s", exc)

    def _format_slack_message(self, alert: AlertEvent) -> dict:
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 Báo động hệ thống: {alert.service.upper()} ({alert.severity.value.upper()})"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Dịch vụ:* `{alert.service}`\n*Chỉ số vỡ:* `{alert.sli_impacted}`\n*Mức độ:* `{alert.severity.value}`"
                }
            }
        ]

        fields = []
        if alert.burn_rate:
            fields.append(f"*Burn Rate:* `{alert.burn_rate}x`")
        if alert.windows:
            fields.append(f"*Cửa sổ:* `{alert.windows.long}/{alert.windows.short}`")
        if alert.slo_target:
            fields.append(f"*Mục tiêu SLO:* `{alert.slo_target * 100}%`")

        if fields:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": " | ".join(fields)
                }
            })

        blocks.append({"type": "divider"})

        evidence_fields = []
        if alert.evidence.promql:
            evidence_fields.append(f"*PromQL:* \n`{alert.evidence.promql}`")
        if alert.evidence.log_query:
            evidence_fields.append(f"*Log Query:* \n`{alert.evidence.log_query}`")

        if evidence_fields:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(evidence_fields)
                }
            })

        actions = []
        if alert.evidence.grafana_panel:
            actions.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "📊 Xem Grafana"},
                "url": alert.evidence.grafana_panel,
                "action_id": "view_grafana"
            })
        if alert.runbook_link:
            actions.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "📖 Xem Runbook"},
                "url": "https://github.com/kietoichoiDXD/AIOPS-w1/blob/main/" + alert.runbook_link,
                "action_id": "view_runbook"
            })

        if actions:
            blocks.append({
                "type": "actions",
                "elements": actions
            })

        if alert.suggested_action:
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"*Gợi ý xử lý:* {alert.suggested_action}"}
                ]
            })

        return {"blocks": blocks}

    async def flush_digest(self) -> list[AlertEvent]:
        """Called every 10 min by the loop: deliver the folded warning/info bulletin."""
        batch, self._digest = self._digest, []
        for a in batch:
            await self._deliver(a)
        return batch
