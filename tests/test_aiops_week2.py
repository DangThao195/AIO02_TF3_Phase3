"""Week-2 AIOps tests: anomaly detection, graph correlation merge, RCA evidence pack."""
from __future__ import annotations

import pytest

from ai_engine.aiops.correlator import Correlator
from ai_engine.aiops.detector_anomaly import (
    AnomalyDetector,
    AnomalyMetric,
    AnomalySignal,
    robust_zscore,
)
from ai_engine.aiops.detector_burnrate import BurnSignal
from ai_engine.aiops.rca_assistant import RCAAssistant
from ai_engine.common.schemas import Severity, SourceLayer


# ─────────────────────────── anomaly: robust z-score ───────────────────────────
def test_robust_zscore_flags_spike():
    baseline = [100.0] * 20            # flat baseline ~100ms
    z, median = robust_zscore(current=500.0, baseline=baseline)
    assert median == 100.0
    assert z > 5                       # a 5x jump is a strong anomaly


def test_robust_zscore_ignores_normal_variation():
    baseline = [95, 100, 105, 98, 102, 99, 101, 100, 97, 103] * 2
    z, _ = robust_zscore(current=101, baseline=list(map(float, baseline)))
    assert abs(z) < 3                  # within normal band -> not anomalous


class FakeProm:
    def __init__(self, current, baseline, use_values_list=False):
        self._current = current
        self._baseline = baseline
        self._use_values_list = use_values_list
    async def scalar(self, q, default=None):
        return self._current
    async def instant(self, q):
        if self._use_values_list:
            # Range vector response style containing a 'values' list of points
            return [{"values": [[0, str(v)] for v in self._baseline]}]
        # Instant vector style containing a 'value' point per series
        return [{"value": [0, str(v)]} for v in self._baseline]


@pytest.mark.asyncio
async def test_anomaly_detector_fires_warning_on_latency_spike():
    m = AnomalyMetric(name="checkout_latency_p95", service="checkout",
                      current_query="q", baseline_query="b", unit="ms")
    det = AnomalyDetector(FakeProm(current=800.0, baseline=[100.0] * 20), [m])
    signals = await det.evaluate()
    assert len(signals) == 1
    assert signals[0].severity in (Severity.WARNING, Severity.INFO)
    assert signals[0].source_layer is SourceLayer.ML_ANOMALY  # never critical (layer 2)


@pytest.mark.asyncio
async def test_anomaly_detector_silent_when_normal():
    m = AnomalyMetric(name="cart_latency_p95", service="cart",
                      current_query="q", baseline_query="b")
    det = AnomalyDetector(FakeProm(current=101.0, baseline=[100.0] * 20), [m])
    assert await det.evaluate() == []


@pytest.mark.asyncio
async def test_anomaly_detector_handles_values_list():
    # Verify that the detector correctly parses a 'values' list returned by range subqueries.
    m = AnomalyMetric(name="checkout_latency_p95", service="checkout",
                      current_query="q", baseline_query="b", unit="ms")
    det = AnomalyDetector(FakeProm(current=800.0, baseline=[100.0] * 20, use_values_list=True), [m])
    signals = await det.evaluate()
    assert len(signals) == 1
    assert signals[0].severity in (Severity.WARNING, Severity.INFO)


# ─────────────────────────── correlator: graph merge ───────────────────────────
def _burn(service, sev=Severity.CRITICAL, burn=14.4):
    return BurnSignal(service=service, sli=f"{service}_success_ratio", severity=sev,
                      burn_rate=burn, error_ratio=0.05, target=0.99,
                      long_window="1h", short_window="5m")

def _anom(service):
    return AnomalySignal(service=service, sli=f"{service}_latency_p95", severity=Severity.WARNING,
                         current_value=800, baseline_median=100, z_score=7.0, confidence=0.9,
                         note=f"{service} latency 800ms vs 100ms")


def test_anomaly_enriches_burnrate_incident_not_separate_page():
    # checkout burns + payment anomaly (downstream) -> ONE incident, anomaly as context.
    corr = Correlator()
    incidents = corr.correlate([_burn("checkout")], [_anom("payment")])
    assert len(incidents) == 1
    assert any("[anomaly]" in s and "payment" in s for s in incidents[0].correlated_signals)


def test_standalone_anomaly_becomes_early_warning_incident():
    # anomaly with no burn-rate nearby -> its own warning incident (catch before system dies).
    corr = Correlator()
    incidents = corr.correlate([], [_anom("email")])
    assert len(incidents) == 1
    assert incidents[0].primary.severity is Severity.WARNING
    assert incidents[0].primary.source_layer is SourceLayer.ML_ANOMALY


def test_storm_dedup_folds_repeat_within_window():
    corr = Correlator(dedup_window_s=900, clock=lambda: 1000.0)
    first = corr.correlate([_burn("checkout")])
    second = corr.correlate([_burn("checkout")])
    assert len(first) == 1 and second == []


# ─────────────────────────── RCA assistant ───────────────────────────
class BlindTelemetry:
    async def find_error_traces(self, service, limit=5):
        from ai_engine.common.telemetry import TelemetryError
        raise TelemetryError("blind")
    async def search(self, index, body):
        from ai_engine.common.telemetry import TelemetryError
        raise TelemetryError("blind")


@pytest.mark.asyncio
async def test_rca_pack_ships_even_when_telemetry_blind():
    corr = Correlator()
    incident = corr.correlate([_burn("checkout")], [_anom("payment")])[0]
    blind = BlindTelemetry()
    rca = RCAAssistant(prom=None, opensearch=blind, jaeger=blind)
    pack = await rca.build(incident)
    md = pack.to_markdown()
    assert "DRAFT" in md
    assert len(pack.hypotheses) >= 2                     # anti-anchor: always ≥2
    assert "evidence incomplete" in md.lower()           # blind sources flagged, not hung
    assert "ký tên" in md                                # human sign-off required


@pytest.mark.asyncio
async def test_rca_ranks_downstream_anomaly_as_top_hypothesis():
    corr = Correlator()
    incident = corr.correlate([_burn("checkout")], [_anom("payment")])[0]
    rca = RCAAssistant(prom=None, opensearch=BlindTelemetry(), jaeger=BlindTelemetry())
    pack = await rca.build(incident)
    assert "payment" in pack.hypotheses[0].text          # deepest anomalous downstream = top
