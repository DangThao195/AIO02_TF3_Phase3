"""Tests cho AIOps mở rộng: forecast (capacity/cost), drift (PSI), và G4 verify guard.

Không cần cluster/AWS — prom client là fake, mọi hàm toán là pure.
"""
from __future__ import annotations

import math

import pytest

from ai_engine.aiops.detector_drift import (
    PSI_MAJOR,
    DriftDetector,
    DriftMetric,
    population_stability_index,
)
from ai_engine.aiops.forecast import (
    CapacityForecaster,
    CapacityMetric,
    fit_linear,
    forecast_budget,
    minutes_to_threshold,
)
from ai_engine.aiops.verify_loop import VerifyLoop
from ai_engine.common.schemas import Severity
from ai_engine.common.telemetry import TelemetryError


# ── fake prom ──
class _FakeProm:
    def __init__(self, series: list[float] | None = None, blind: bool = False):
        self._series = series or []
        self._blind = blind

    async def instant(self, query):
        if self._blind:
            raise TelemetryError("prom blind")
        return [{"values": [[i, str(v)] for i, v in enumerate(self._series)]}]

    async def scalar(self, query, default=None):
        if self._blind:
            raise TelemetryError("prom blind")
        return self._series[-1] if self._series else default


# ── fit_linear ──
def test_fit_linear_perfect_slope():
    fit = fit_linear([float(2 * i + 5) for i in range(20)])
    assert fit is not None
    assert fit.slope == pytest.approx(2.0)
    assert fit.intercept == pytest.approx(5.0)
    assert fit.r_squared == pytest.approx(1.0)


def test_fit_linear_needs_min_points():
    assert fit_linear([1.0, 2.0, 3.0]) is None  # < MIN_POINTS


def test_fit_linear_flat_series_is_perfect_but_zero_slope():
    fit = fit_linear([7.0] * 20)
    assert fit is not None and fit.slope == 0.0


# ── minutes_to_threshold ──
def test_eta_to_ceiling_linear_growth():
    # 50 → 71, +1/mẫu, trần 100 → còn 29 mẫu × 5 phút = 145 phút
    series = [float(50 + i) for i in range(22)]
    eta, fit = minutes_to_threshold(series, threshold=100.0, step_minutes=5.0)
    assert fit is not None and fit.slope == pytest.approx(1.0)
    assert eta == pytest.approx(145.0, abs=1.0)


def test_eta_none_when_already_over_threshold():
    series = [float(100 + i) for i in range(20)]
    eta, _ = minutes_to_threshold(series, threshold=50.0)
    assert eta is None  # đã vượt — việc của detector, không phải forecast


def test_eta_none_when_trending_down():
    series = [float(100 - i) for i in range(20)]
    eta, _ = minutes_to_threshold(series, threshold=200.0)
    assert eta is None  # đi xuống → không bao giờ chạm


def test_eta_none_when_fit_is_noise():
    # chuỗi nhiễu quanh hằng số → R² thấp → không dự báo bừa
    series = [50.0 + (13 * i % 7) - 3 for i in range(30)]
    eta, fit = minutes_to_threshold(series, threshold=100.0)
    assert eta is None
    assert fit is not None and fit.r_squared < 0.5


# ── CapacityForecaster ──
async def test_forecaster_warns_before_exhaustion():
    series = [float(50 + i) for i in range(30)]  # leo đều tới trần 100
    det = CapacityForecaster(
        _FakeProm(series),
        [CapacityMetric(name="pool", service="product-catalog", query="q", ceiling=100.0)],
        horizon_min=300,
    )
    sigs = await det.evaluate()
    assert len(sigs) == 1
    assert sigs[0].sli == "pool_forecast_exhaustion"
    assert sigs[0].severity is Severity.WARNING  # layer-2: KHÔNG page
    assert "dự báo chạm trần" in sigs[0].note


async def test_forecaster_silent_when_exhaustion_beyond_horizon():
    series = [50.0 + 0.01 * i for i in range(30)]  # leo cực chậm
    det = CapacityForecaster(
        _FakeProm(series),
        [CapacityMetric(name="pool", service="product-catalog", query="q", ceiling=100.0)],
        horizon_min=120,
    )
    assert await det.evaluate() == []  # không làm phiền on-call


async def test_forecaster_silent_when_prom_blind():
    det = CapacityForecaster(
        _FakeProm(blind=True),
        [CapacityMetric(name="pool", service="product-catalog", query="q", ceiling=100.0)],
    )
    assert await det.evaluate() == []  # telemetry mù → im, không đoán


# ── forecast_budget ──
def test_budget_forecast_will_exceed():
    # 3 ngày tiêu $30 → run-rate $10/ngày → 7 ngày = $70 > trần $50
    f = forecast_budget(spent_usd=30.0, days_elapsed=3.0, budget_usd=50.0, days_total=7.0)
    assert f.projected_usd == pytest.approx(70.0)
    assert f.will_exceed is True
    assert f.projected_ratio == pytest.approx(1.4)


def test_budget_forecast_within_budget():
    f = forecast_budget(spent_usd=10.0, days_elapsed=5.0, budget_usd=50.0, days_total=7.0)
    assert f.will_exceed is False


def test_budget_forecast_rejects_bad_input():
    with pytest.raises(ValueError):
        forecast_budget(spent_usd=1.0, days_elapsed=0.0, budget_usd=50.0)
    with pytest.raises(ValueError):
        forecast_budget(spent_usd=1.0, days_elapsed=1.0, budget_usd=0.0)


# ── PSI drift ──
def test_psi_stable_for_same_distribution():
    base = [50.0 + math.sin(i) * 5 for i in range(200)]
    actual = [50.0 + math.sin(i + 0.1) * 5 for i in range(200)]
    res = population_stability_index(base, actual)
    assert res is not None
    assert res.severity == "stable" and not res.drifted


def test_psi_detects_shifted_distribution():
    base = [50.0 + math.sin(i) * 5 for i in range(200)]
    actual = [90.0 + math.sin(i) * 5 for i in range(200)]  # dịch hẳn sang phải
    res = population_stability_index(base, actual)
    assert res is not None
    assert res.drifted and res.psi >= PSI_MAJOR


def test_psi_none_when_too_few_samples():
    assert population_stability_index([1.0] * 10, [2.0] * 10) is None


async def test_drift_detector_emits_warning_on_major_drift():
    class _TwoSeriesProm:
        async def instant(self, query):
            vals = ([50.0 + math.sin(i) * 5 for i in range(200)] if "7d" in query
                    else [95.0 + math.sin(i) * 5 for i in range(200)])
            return [{"values": [[i, str(v)] for i, v in enumerate(vals)]}]

    det = DriftDetector(_TwoSeriesProm(), [DriftMetric(
        name="checkout_latency_p95", service="checkout",
        baseline_query="q[7d:5m]", actual_query="q[1d:5m]")])
    sigs = await det.evaluate()
    assert len(sigs) == 1
    assert sigs[0].sli == "checkout_latency_p95_drift"
    assert sigs[0].severity is Severity.WARNING
    assert "re-baseline" in sigs[0].note  # gợi ý hành động cho on-call


# ── G4: verify blind vs not-recovered ──
async def test_verify_blind_flag_when_no_samples():
    """G4: prom mù → blind=True (KHÔNG phải 'chưa hồi phục') → caller escalate, không rollback."""
    loop = VerifyLoop(_FakeProm(blind=True), window_s=1, poll_s=1, sleep=_noop_sleep)
    res = await loop.verify(recovery_query="sli:x_error:ratio_rate5m", threshold=0.01)
    assert res.recovered is False
    assert res.blind is True
    assert "BLIND" in res.detail


async def test_verify_not_recovered_is_not_blind():
    """Đo được nhưng vẫn vỡ → blind=False → caller rollback (đúng)."""
    loop = VerifyLoop(_FakeProm([0.5]), window_s=1, poll_s=1, sleep=_noop_sleep)
    res = await loop.verify(recovery_query="q", threshold=0.01)
    assert res.recovered is False and res.blind is False


async def test_verify_recovered_sets_blind_false():
    loop = VerifyLoop(_FakeProm([0.001]), window_s=1, poll_s=1, sleep=_noop_sleep)
    res = await loop.verify(recovery_query="q", threshold=0.01)
    assert res.recovered is True and res.blind is False


async def _noop_sleep(_seconds):
    return None
