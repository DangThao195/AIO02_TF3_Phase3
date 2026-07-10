"""Multi-Window Robust Z-score latency detector tests (C2 layer-2, giai đoạn 24-48h).

Verifies the slide's core rule: Alert (WARNING) chỉ khi z>3 breach ở CẢ long VÀ short window;
một window breach = INFO; không bao giờ critical.
"""
from __future__ import annotations

import pytest

from ai_engine.aiops.detector_latency import (
    LatencyMetric,
    MultiWindowLatencyDetector,
    default_latency_metrics,
    Z_ALERT,
)
from ai_engine.common.schemas import Severity, SourceLayer


class _FakeProm:
    """Trả p95 long/short theo query + một baseline range cố định (ổn định quanh 100ms)."""

    def __init__(self, p95_long: float, p95_short: float, baseline: list[float]):
        self._long = p95_long
        self._short = p95_short
        self._baseline = baseline

    async def scalar(self, query, default=None):
        # long_query dùng [30m], short_query dùng [5m] — phân biệt bằng chuỗi window.
        if "[30m]" in query:
            return self._long
        if "[5m]" in query and "[1w" not in query:
            return self._short
        return default

    async def instant(self, query):
        return [{"values": [[i, str(v)] for i, v in enumerate(self._baseline)]}]


def _metric():
    return LatencyMetric(
        name="frontend_latency_p95_mw", service="frontend",
        long_query="q[30m]", short_query="q[5m]", baseline_query="(q[5m])[1w:5m]",
    )


# baseline: 40 mẫu quanh 100ms, MAD nhỏ -> lệch lớn = z cao
_BASELINE = [100.0 + (i % 5) for i in range(40)]  # 100..104, median 102, MAD ~1


@pytest.mark.asyncio
async def test_both_windows_breach_is_warning():
    # cả long lẫn short đều ~300ms >> baseline 102 -> z rất cao ở cả hai
    prom = _FakeProm(p95_long=300.0, p95_short=320.0, baseline=_BASELINE)
    det = MultiWindowLatencyDetector(prom, [_metric()])
    sigs = await det.evaluate()
    assert len(sigs) == 1
    assert sigs[0].severity is Severity.WARNING
    assert sigs[0].source_layer is SourceLayer.ML_ANOMALY  # layer 2


@pytest.mark.asyncio
async def test_short_only_spike_is_info_not_warning():
    # short vọt lên (spike 5m) nhưng long vẫn quanh baseline -> chỉ INFO (chống spike thoáng qua)
    prom = _FakeProm(p95_long=101.0, p95_short=320.0, baseline=_BASELINE)
    det = MultiWindowLatencyDetector(prom, [_metric()])
    sigs = await det.evaluate()
    # có thể bị lọc bởi confidence>=0.7; nếu qua thì phải là INFO, KHÔNG warning
    assert all(s.severity is not Severity.WARNING for s in sigs)


@pytest.mark.asyncio
async def test_long_only_breach_is_not_warning():
    prom = _FakeProm(p95_long=320.0, p95_short=101.0, baseline=_BASELINE)
    det = MultiWindowLatencyDetector(prom, [_metric()])
    sigs = await det.evaluate()
    assert all(s.severity is not Severity.WARNING for s in sigs)


@pytest.mark.asyncio
async def test_no_breach_no_signal():
    prom = _FakeProm(p95_long=103.0, p95_short=104.0, baseline=_BASELINE)
    det = MultiWindowLatencyDetector(prom, [_metric()])
    assert await det.evaluate() == []


@pytest.mark.asyncio
async def test_never_emits_critical_even_at_huge_z():
    # p95 x100 baseline: z khổng lồ, vẫn phải cap ở WARNING (C2.3)
    prom = _FakeProm(p95_long=10000.0, p95_short=12000.0, baseline=_BASELINE)
    det = MultiWindowLatencyDetector(prom, [_metric()])
    sigs = await det.evaluate()
    assert sigs and all(s.severity is not Severity.CRITICAL for s in sigs)


@pytest.mark.asyncio
async def test_insufficient_baseline_is_skipped():
    prom = _FakeProm(p95_long=300.0, p95_short=320.0, baseline=[100.0] * 5)  # < MIN_BASELINE
    det = MultiWindowLatencyDetector(prom, [_metric()])
    assert await det.evaluate() == []


def test_default_metrics_cover_storefront():
    names = {m.service for m in default_latency_metrics()}
    assert "frontend" in names  # slide nhắm p95 storefront
    assert {"checkout", "cart", "payment"} <= names
    # mỗi metric có cả long + short window riêng biệt
    for m in default_latency_metrics():
        assert "[30m]" in m.long_query and "[5m]" in m.short_query


def test_z_alert_threshold_matches_slide():
    assert Z_ALERT == 3.0  # "Robust Z-score > 3"
