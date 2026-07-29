"""C3 evidence-pack writer + C2.9 resolved-event tests (need light fixtures)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_engine.aiops.alert_emitter import AlertEmitter
from ai_engine.aiops.correlator import Correlator
from ai_engine.aiops.detector_burnrate import BurnSignal
from ai_engine.aiops.rca_assistant import EvidencePack, Hypothesis
from ai_engine.common.config import AlertConfig
from ai_engine.common.schemas import Severity


def test_evidence_pack_writes_file(tmp_path):
    pack = EvidencePack(incident_id="TF3-20260710-0042", generated_at=datetime.now(timezone.utc))
    pack.summary = ["Cái gì: checkout vỡ"]
    pack.hypotheses = [Hypothesis(text="H1", supporting="s"), Hypothesis(text="H2", supporting="s")]
    path = pack.write(root=tmp_path)
    assert path.exists()
    assert path.name == "evidence-pack.md"
    assert path.parent.name == "TF3-20260710-0042"
    assert "DRAFT" in path.read_text(encoding="utf-8")


class _RecordingEmitter(AlertEmitter):
    """Capture deliveries instead of hitting the network."""
    def __init__(self):
        super().__init__(AlertConfig(webhook_url=None), storm_threshold=100)
        self.delivered = []
        self.resolved = []
    async def _deliver(self, alert):
        self.delivered.append(alert)
    async def _deliver_resolved(self, alert):
        self.resolved.append(alert)


def _incident(service="checkout", severity=Severity.CRITICAL):
    sig = BurnSignal(service=service, sli=f"{service}_success_ratio", severity=severity,
                     burn_rate=14.4, error_ratio=0.15, target=0.99, long_window="1h", short_window="5m")
    return Correlator().correlate([sig], [])[0]


@pytest.mark.asyncio
async def test_resolved_emitted_when_fingerprint_clears():
    em = _RecordingEmitter()
    inc = _incident()
    await em.emit(inc)                 # firing
    resolved = await em.reconcile([])  # next tick: nothing firing
    assert len(resolved) == 1
    assert resolved[0].status == "resolved"
    assert resolved[0].ends_at is not None


@pytest.mark.asyncio
async def test_no_resolved_while_still_firing():
    em = _RecordingEmitter()
    inc = _incident()
    await em.emit(inc)
    resolved = await em.reconcile([inc])  # still firing this tick
    assert resolved == []
