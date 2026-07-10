"""AIOps engine loop — the standalone service (ns ai-engine) that wires detection together.

Every tick: read SLIs (burn-rate detector) -> correlate into incidents -> emit C2 alerts.
Runs OFF the request critical path (ADR-001). Exposes /metrics for Prometheus scrape and
/healthz for the kubelet probe. If telemetry is blind, it flips ai_engine_blind and keeps
running (never silent) — the C1 failure-mode contract.

Also processes Slack interactive callbacks (C6 Approval Gate / AIOps-06) for automated
incident remediation with human-in-the-loop approvals.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
from prometheus_client import make_asgi_app

from .aiops.alert_emitter import AlertEmitter
from .aiops.approval import parse_callback
from .aiops.correlator import Correlator
from .aiops.detector_anomaly import AnomalyDetector, default_anomaly_metrics
from .aiops.detector_burnrate import BurnRateDetector, default_slos
from .aiops.detector_latency import MultiWindowLatencyDetector, default_latency_metrics
from .aiops.audit_log import AuditLog
from .aiops.rca_assistant import RCAAssistant
from .aiops.remediation import RemediationEngine, ActionType, RemediationRecord
from .aiops.verify_loop import VerifyLoop
from .common.config import Config, load_config
from .common.metrics import DETECTION_LATENCY
from .common.schemas import ApprovalDecision
from .common.telemetry import JaegerClient, OpenSearchClient, PrometheusClient

log = logging.getLogger("ai_engine.server")


def k8s_executor(record: RemediationRecord, mode) -> str:
    """Production-grade K8s executor running kubectl mutations under least privilege.

    `mode` is: True (server-side dry-run), False (real apply), or the string "rollback"
    (run the record's rollback_plan verbatim — C6 auto-rollback path). Splitting these here
    keeps the RemediationEngine cluster-agnostic and testable.
    """
    ns = "techx-tf3"
    dry_run = mode is True

    if mode == "rollback":
        plan = (record.execution.rollback_plan if record.execution else "").strip()
        if not plan:
            raise ValueError("no rollback_plan to execute")
        # rollback_plan is an operator-authored kubectl line; run it as given.
        cmd = plan.split()
        log.warning("Executing rollback plan: %s", plan)
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        return res.stdout or "rollback applied"

    target = record.target  # e.g., "deployment/payment"
    action = record.action  # e.g., ActionType.RESTART

    if not (target.startswith("deployment/") or target.startswith("deploy/")):
        raise ValueError(f"Unsupported target format: {target}")

    dep_name = target.split("/")[-1]

    if action == ActionType.RESTART:
        cmd = ["kubectl", "rollout", "restart", f"deployment/{dep_name}", "-n", ns]
        if dry_run:
            cmd.append("--dry-run=server")
    elif action == ActionType.SCALE:
        replicas = record.parameters.get("replicas", 2)
        cmd = ["kubectl", "scale", f"deployment/{dep_name}", f"--replicas={replicas}", "-n", ns]
        if dry_run:
            return f"dry-run: scale deployment/{dep_name} to {replicas}"
    else:
        raise ValueError(f"Unsupported action: {action}")

    log.info("Running command: %s (dry_run=%s)", " ".join(cmd), dry_run)
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
    return res.stdout or "success"


def verify_slack_signature(body: bytes, timestamp: str, signature: str, secret: str | None) -> bool:
    if not secret:
        return False
    try:
        if abs(time.time() - float(timestamp)) > 300:
            return False
    except ValueError:
        return False

    sig_basestring = f"v0:{timestamp}:".encode("utf-8") + body
    computed = "v0=" + hmac.new(
        secret.encode("utf-8"),
        sig_basestring,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


async def read_body(receive) -> bytes:
    body = b""
    more_body = True
    while more_body:
        message = await receive()
        body += message.get("body", b"")
        more_body = message.get("more_body", False)
    return body


class AIOpsEngine:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        prom = PrometheusClient(cfg.telemetry)
        self._detector = BurnRateDetector(prom, default_slos(cfg.slo))
        self._anomaly = AnomalyDetector(prom, default_anomaly_metrics())
        # Layer-2 latency (bật ở giai đoạn 24-48h khi baseline đã đủ). Multi-window robust z-score.
        self._latency = MultiWindowLatencyDetector(prom, default_latency_metrics())
        self._correlator = Correlator()
        self._emitter = AlertEmitter(cfg.alert, slack_cfg=cfg.slack)
        self._rca = RCAAssistant(
            prom, OpenSearchClient(cfg.telemetry), JaegerClient(cfg.telemetry),
        )
        self._audit = AuditLog()
        self._verify = VerifyLoop(prom)
        self._remediation = RemediationEngine(
            executor=k8s_executor,
            audit=self._audit,
            escalate=self._escalate_rollback_failure,
        )
        self.pending_remediations: dict[str, RemediationRecord] = {}

    def _escalate_rollback_failure(self, record: RemediationRecord, reason: str) -> None:
        """C6.11 — a failed rollback is the one thing a human MUST see. Fire a critical Slack
        page synchronously-safe (schedule the async post) so the engine loop never blocks."""
        text = (
            f"🆘 *ESCALATION — rollback FAILED* for action `{record.action_id}` "
            f"(incident `{record.incident_id}`, target `{record.target}`).\n"
            f"Reason: {reason}\n"
            f"*Manual intervention required.* Rollback plan: `{record.execution.rollback_plan}`"
        )
        log.error("ESCALATION: %s", text)
        try:
            asyncio.get_event_loop().create_task(self._post_slack_text(text))
        except RuntimeError:
            # no running loop (e.g. unit/sync context) — the log line above is the record.
            pass

    async def _post_slack_text(self, text: str) -> None:
        if not (self._cfg.slack.bot_token and self._cfg.slack.channel_id):
            return
        headers = {"Authorization": f"Bearer {self._cfg.slack.bot_token}",
                   "Content-Type": "application/json; charset=utf-8"}
        body = {"channel": self._cfg.slack.channel_id, "text": text}
        async with httpx.AsyncClient() as client:
            await client.post("https://slack.com/api/chat.postMessage", json=body, headers=headers)

    async def tick(self) -> int:
        """One detection cycle. Returns number of incidents emitted.

        Layer 1 (burn-rate) + layer 2 (anomaly) feed the correlator, which folds them into
        incidents. Each incident is emitted (C2) and gets a draft Evidence Pack (C3).
        """
        started = datetime.now(timezone.utc)
        signals = await self._detector.evaluate()
        # Layer 2 = anomaly (median/MAD spot) + multi-window latency (long AND short breach).
        anomalies = await self._anomaly.evaluate()
        anomalies += await self._latency.evaluate()
        incidents = self._correlator.correlate(signals, anomalies)
        for incident in incidents:
            alert = await self._emitter.emit(incident)
            if alert.severity.value == "critical":
                DETECTION_LATENCY.observe((datetime.now(timezone.utc) - started).total_seconds())

                try:
                    pack = await self._rca.build(incident)
                    pack_path = pack.write()  # C3: durable evidence pack to incidents/<id>/
                    log.info("evidence pack ready for %s (%d hypotheses) -> %s",
                             incident.incident_id, len(pack.hypotheses), pack_path)
                except Exception:
                    log.exception("rca build failed for %s", incident.incident_id)

                # Auto-propose remediation for checkout critical failures (INC-1 retry/scale lesson)
                if incident.primary.service == "checkout":
                    try:
                        record = self._remediation.propose(
                            incident_id=incident.incident_id,
                            action=ActionType.SCALE,
                            target="deployment/checkout",
                            parameters={"replicas": 4},
                            rationale="Checkout SLO error budget burn rate high. Scaling to contain load.",
                            risk_note="Slightly increases pod count and database connection count.",
                            rollback_plan="Scale back to 2 replicas: kubectl scale deployment/checkout --replicas=2 -n techx-tf3"
                        )
                        self.pending_remediations[record.action_id] = record
                        log.info("Proposed remediation %s for checkout", record.action_id)
                        await self.send_slack_card(record)
                    except Exception:
                        log.exception("Auto-proposal failed")

        # C2.9 — emit resolved notices for fingerprints that stopped firing this tick.
        try:
            resolved = await self._emitter.reconcile(incidents)
            if resolved:
                log.info("emitted %d resolved notice(s)", len(resolved))
        except Exception:
            log.exception("resolve reconciliation failed")
        return len(incidents)

    async def verify_and_maybe_rollback(self, record: RemediationRecord) -> None:
        """C6.6 — poll the impacted SLI for 5 min after an action executes. If it did not
        recover, run the rollback and re-audit. The action's own execution record is updated
        so the audit trail shows "executed → verified failed → rolled back"."""
        svc = record.target.split("/")[-1]
        # Recovery = error ratio back under a small threshold (SLO-relative). Uses the same
        # recording-rule family the burn-rate detector reads.
        recovery_query = f"sli:{svc}_error:ratio_rate5m"
        threshold = 0.01  # <1% error ratio = healthy enough to call it recovered
        try:
            result = await self._verify.verify(recovery_query=recovery_query, threshold=threshold)
        except Exception:
            log.exception("verify loop crashed for %s; leaving action in place", record.action_id)
            return

        if result.recovered:
            record.execution.verification += f"; VERIFIED {result.detail}"
            log.info("remediation %s verified recovered", record.action_id)
        else:
            record.execution.verification += f"; VERIFY FAILED {result.detail} — rolling back"
            log.warning("remediation %s did not recover; auto-rollback", record.action_id)
            try:
                out = k8s_executor(record, "rollback")
                record.execution.verification += f"; rolled back: {out}"
            except Exception as exc:
                self._escalate_rollback_failure(record, f"post-verify rollback failed: {exc}")
        self._audit.append(record)  # re-audit the verified/rolled-back outcome (append-only)

    async def send_slack_card(self, record: RemediationRecord) -> None:
        if not self._cfg.slack.bot_token or not self._cfg.slack.channel_id:
            log.info("Slack approval card not sent (missing bot_token or channel_id)")
            return

        from .aiops.approval import render_slack_blockkit
        card = render_slack_blockkit(record, evidence_url=f"http://frontend-proxy:8080/grafana/d/slo-{record.target.split('/')[-1]}")
        body = {
            "channel": self._cfg.slack.channel_id,
            "blocks": card["blocks"]
        }

        headers = {
            "Authorization": f"Bearer {self._cfg.slack.bot_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        async with httpx.AsyncClient() as client:
            res = await client.post("https://slack.com/api/chat.postMessage", json=body, headers=headers)
            log.info("Sent Slack card: %s", res.text)

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
    engine = AIOpsEngine(cfg)

    # Start the background detection loop
    loop = asyncio.get_event_loop()
    loop.create_task(engine.run())

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path.startswith("/metrics"):
            return await metrics_app(scope, receive, send)

        if path == "/healthz":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})
            return

        if path == "/webhooks/slack/interactive" and method == "POST":
            # Extract headers for signature verification
            headers = dict(scope.get("headers", []))
            timestamp = headers.get(b"x-slack-request-timestamp", b"").decode("utf-8")
            signature = headers.get(b"x-slack-signature", b"").decode("utf-8")

            body = await read_body(receive)

            # Security: Verify signature
            if not verify_slack_signature(body, timestamp, signature, cfg.slack.signing_secret):
                log.warning("Invalid Slack signature received")
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return

            try:
                params = parse_qs(body.decode("utf-8"))
                payload = json.loads(params.get("payload", ["{}"])[0])
                callback = parse_callback(payload)

                record = engine.pending_remediations.get(callback.action_id)
                if not record:
                    raise ValueError(f"No pending remediation record found for {callback.action_id}")

                if callback.decision.value == "approve":
                    engine._remediation.approve_and_execute(record, approver=callback.user)
                    status_text = f"✅ Action approved and executed by @{callback.user}. Verification: {record.execution.verification}"
                    # C6.6: verify the SLI actually recovered; auto-rollback if not (non-blocking).
                    if record.execution and record.execution.result == "success":
                        asyncio.get_event_loop().create_task(engine.verify_and_maybe_rollback(record))
                else:
                    engine._remediation.reject(record, approver=callback.user)
                    status_text = f"❌ Action rejected by @{callback.user}."

                # Cleanup pending
                engine.pending_remediations.pop(callback.action_id, None)

                # Respond to Slack to update the message card
                response_url = payload.get("response_url")
                if response_url:
                    async with httpx.AsyncClient() as client:
                        await client.post(response_url, json={"text": status_text, "replace_original": True})

                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": json.dumps({"text": "ok"}).encode("utf-8")})
            except Exception as e:
                log.exception("Error processing Slack callback")
                await send({"type": "http.response.start", "status": 400, "headers": []})
                await send({"type": "http.response.body", "body": str(e).encode("utf-8")})
            return

        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"not found"})

    return app


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    # To run standalone, we just start the app server loop
    engine = AIOpsEngine(cfg)
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
