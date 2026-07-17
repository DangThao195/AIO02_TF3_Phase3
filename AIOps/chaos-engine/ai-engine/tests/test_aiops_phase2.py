"""Phase 2 unit tests — AIOps detection (Tier-1 logic + Tier-2 mock telemetry).

Proves: multiwindow gating (both windows must breach), severity classification, dedup,
dependency correlation + blast radius, and C2 AlertEvent schema — without a cluster.
"""
from __future__ import annotations

import pytest

from ai_engine.aiops.alert_emitter import build_alert
from ai_engine.aiops.correlator import Correlator
from ai_engine.aiops.detector_burnrate import (
    BurnRateDetector,
    BurnSignal,
    SLODef,
    classify,
)
from ai_engine.common.schemas import Severity, SourceLayer


# ─────────────────────────── classify (pure math) ───────────────────────────
def test_classify_critical_when_both_windows_breach():
    # 99% SLO -> budget 0.01. 14.4x threshold = 0.144. Both windows above => critical.
    result = classify(error_ratio_long=0.20, error_ratio_short=0.20, budget=0.01)
    assert result is not None
    assert result[0] is Severity.CRITICAL


def test_classify_no_fire_when_only_short_window_spikes():
    # 5-min spike but the 1h window is clean -> NO page (the whole point of multiwindow).
    result = classify(error_ratio_long=0.001, error_ratio_short=0.30, budget=0.01)
    assert result is None


def test_classify_warning_tier():
    # Above 6x (0.06) but below 14.4x (0.144) on both windows -> warning.
    result = classify(error_ratio_long=0.08, error_ratio_short=0.08, budget=0.01)
    assert result is not None
    assert result[0] is Severity.WARNING


def test_classify_info_tier():
    # Above 1x (0.01) but below 6x (0.06) on both windows -> info.
    result = classify(error_ratio_long=0.02, error_ratio_short=0.02, budget=0.01)
    assert result is not None
    assert result[0] is Severity.INFO


# ─────────────────────────── detector with fake Prometheus ───────────────────────────
class FakeProm:
    def __init__(self, values: dict[str, float]):
        self._values = values

    async def scalar(self, query: str, default=None):
        return self._values.get(query, default)


@pytest.mark.asyncio
async def test_detector_fires_checkout_critical():
    prom = FakeProm({
        "sli:checkout_error:ratio_rate1h": 0.20,
        "sli:checkout_error:ratio_rate5m": 0.20,
    })
    det = BurnRateDetector(prom, [SLODef("checkout", "checkout_success_ratio", 0.99,
                                          "sli:checkout_error:ratio_rate")])
    signals = await det.evaluate()
    assert len(signals) == 1
    assert signals[0].severity is Severity.CRITICAL
    assert signals[0].service == "checkout"


@pytest.mark.asyncio
async def test_detector_fires_checkout_info():
    prom = FakeProm({
        "sli:checkout_error:ratio_rate3d": 0.02,
        "sli:checkout_error:ratio_rate6h": 0.02,
    })
    det = BurnRateDetector(prom, [SLODef("checkout", "checkout_success_ratio", 0.99,
                                          "sli:checkout_error:ratio_rate")])
    signals = await det.evaluate()
    assert len(signals) == 1
    assert signals[0].severity is Severity.INFO
    assert signals[0].service == "checkout"


@pytest.mark.asyncio
async def test_detector_silent_when_healthy():
    prom = FakeProm({
        "sli:checkout_error:ratio_rate1h": 0.0,
        "sli:checkout_error:ratio_rate5m": 0.0,
    })
    det = BurnRateDetector(prom, [SLODef("checkout", "checkout_success_ratio", 0.99,
                                          "sli:checkout_error:ratio_rate")])
    assert await det.evaluate() == []


# ─────────────────────────── correlator ───────────────────────────
def _sig(service, severity=Severity.CRITICAL, burn=14.4):
    return BurnSignal(service=service, sli=f"{service}_success_ratio", severity=severity,
                      burn_rate=burn, error_ratio=0.05, target=0.99,
                      long_window="1h", short_window="5m")


def test_correlator_groups_dependency_cluster_into_one_incident():
    # checkout + payment fire together -> one incident (payment is a checkout downstream).
    corr = Correlator()
    incidents = corr.correlate([_sig("checkout"), _sig("payment", Severity.WARNING, 6.0)])
    assert len(incidents) == 1
    assert incidents[0].primary.service == "checkout"        # worst severity is primary
    assert any("payment" in s for s in incidents[0].correlated_signals)


def test_correlator_dedups_repeat_within_window():
    corr = Correlator(dedup_window_s=900, clock=lambda: 1000.0)
    first = corr.correlate([_sig("checkout")])
    second = corr.correlate([_sig("checkout")])              # same fingerprint, within window
    assert len(first) == 1
    assert second == []


def test_correlator_blast_radius_includes_upstream():
    corr = Correlator()
    incidents = corr.correlate([_sig("payment")])
    # payment is downstream of checkout -> checkout is in the blast radius.
    assert "checkout" in incidents[0].blast_radius


# ─────────────────────────── C2 alert schema ───────────────────────────
def test_build_alert_produces_valid_c2_event():
    corr = Correlator()
    incident = corr.correlate([_sig("checkout")])[0]
    alert = build_alert(incident)
    assert alert.schema_version == "1.0"
    assert alert.severity is Severity.CRITICAL
    assert alert.source_layer is SourceLayer.SLO_BURNRATE
    assert alert.requires_ack_within == "5m"
    assert alert.evidence.promql                              # copy-pasteable evidence present
    assert alert.evidence.log_query
    # round-trips to JSON (what CDO's webhook receives)
    assert '"schema_version":"1.0"' in alert.model_dump_json().replace(" ", "")
