"""Multi-Window Robust Z-score latency detector — C2 layer 2, giai đoạn 24-48h (nâng cao).

Giai đoạn đầu (0-24h) hệ dựa vào MWMBR trên error-rate (burn-rate detector) — lá chắn không
cần data lịch sử. Sau ~1-2 ngày, khi đã có "hơi thở" traffic để dựng baseline, ta bật thêm
lớp latency này để bắt hiện tượng NGHẼN (p95 latency tăng dị thường) mà error-rate chưa kịp vỡ.

Nguyên lý (đúng như chiến lược "Robust Z-score + Multi-Window"):
  - Robust Z-score = (Xi - Median) / MAD thay cho (Xi - Mean) / StdDev. Median + MAD kháng
    outlier — chính những điểm dị biệt ta đang đi săn không làm méo baseline (mean/std thì có).
  - Multi-Window: tính z cho CẢ long window (p95 30m) VÀ short window (p95 5m), so cùng một
    baseline 1 tuần. Chỉ Alert khi z > 3 breach ở CẢ HAI cửa sổ — giống MWMBR, để một spike
    5 phút thoáng qua (chỉ short breach) KHÔNG kéo còi. "z>3 kéo dài suốt cả 2 window → nghẽn".

Trần severity: đây là lớp ML/thống kê (SourceLayer.ML_ANOMALY) nên TỐI ĐA `warning`, không
bao giờ `critical` (C2.3). confidence < 0.7 bị loại trước khi rời engine (C2.4).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..common.schemas import Severity
from ..common.telemetry import PrometheusClient, TelemetryError
from .detector_anomaly import (
    AnomalySignal,
    FOCUS_WEIGHTS,
    DEFAULT_WEIGHT,
    _confidence,
    robust_zscore,
)

# Ngưỡng theo slide: z > 3 = dị thường. Cả-hai-window z>3 -> WARNING; chỉ-một-window -> INFO.
Z_ALERT = 3.0
MIN_BASELINE = 20  # cần đủ mẫu baseline mới đáng tin (1 tuần @5m >> 20)


@dataclass(frozen=True)
class LatencyMetric:
    """Một metric latency để canh, kèm 3 query: long-window p95, short-window p95, và
    baseline range (chuỗi p95 trong 1 tuần) để dựng median + MAD."""

    name: str
    service: str
    long_query: str      # p95 trên cửa sổ dài (vd rate[...30m])
    short_query: str     # p95 trên cửa sổ ngắn (vd rate[...5m])
    baseline_query: str  # ([p95])[1w:5m] -> chuỗi để lấy median/MAD
    unit: str = "ms"


class MultiWindowLatencyDetector:
    def __init__(self, prom: PrometheusClient, metrics: list[LatencyMetric]):
        self._prom = prom
        self._metrics = metrics

    async def evaluate(self) -> list[AnomalySignal]:
        signals: list[AnomalySignal] = []
        for m in self._metrics:
            sig = await self._evaluate_one(m)
            if sig is not None and sig.confidence >= 0.7:
                signals.append(sig)
        return signals

    async def _evaluate_one(self, m: LatencyMetric) -> AnomalySignal | None:
        try:
            p95_long = await self._prom.scalar(m.long_query, default=None)
            p95_short = await self._prom.scalar(m.short_query, default=None)
            baseline = await self._baseline_series(m.baseline_query)
        except TelemetryError:
            return None
        if p95_long is None or p95_short is None or len(baseline) < MIN_BASELINE:
            return None

        z_long, median = robust_zscore(p95_long, baseline)
        z_short, _ = robust_zscore(p95_short, baseline)

        # Latency: chỉ quan tâm chiều TĂNG (higher is worse). z âm = nhanh hơn baseline, bỏ.
        long_breach = z_long > Z_ALERT
        short_breach = z_short > Z_ALERT

        # Cốt lõi Multi-Window: cả hai window mới là "nghẽn kéo dài" -> WARNING.
        if long_breach and short_breach:
            severity = Severity.WARNING
        elif long_breach or short_breach:
            # Một window breach = spike thoáng qua HOẶC mới chớm — chỉ INFO (bối cảnh, không page).
            severity = Severity.INFO
        else:
            return None

        weight = FOCUS_WEIGHTS.get(m.service, DEFAULT_WEIGHT)
        # confidence dựa trên window YẾU hơn — độ tin chỉ cao khi cả hai đều cao.
        directing_z = min(z_long, z_short) if severity is Severity.WARNING else max(z_long, z_short)
        confidence = _confidence(directing_z, weight)

        windows = (
            f"long(30m) z={z_long:.1f} & short(5m) z={z_short:.1f}"
            if severity is Severity.WARNING
            else f"chỉ {'long' if long_breach else 'short'} breach (z={directing_z:.1f})"
        )
        return AnomalySignal(
            service=m.service,
            sli=m.name,
            severity=severity,
            current_value=round(p95_short, 3),
            baseline_median=round(median, 3),
            z_score=round(directing_z, 2),
            confidence=round(confidence, 2),
            note=(
                f"{m.name} p95 tăng dị thường: {p95_short:.0f}{m.unit} "
                f"vs baseline {median:.0f}{m.unit} — {windows}"
            ),
        )

    async def _baseline_series(self, query: str) -> list[float]:
        """Range/subquery -> danh sách giá trị p95 để dựng median + MAD."""
        results = await self._prom.instant(query)
        values: list[float] = []
        for r in results:
            points = r.get("values")
            if points:
                for p in points:
                    try:
                        values.append(float(p[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
            else:
                v = r.get("value")
                if v:
                    try:
                        values.append(float(v[1]))
                    except (TypeError, ValueError, IndexError):
                        pass
        return values


def default_latency_metrics() -> list[LatencyMetric]:
    """Bộ metric p95 latency canh sẵn, ưu tiên storefront + service doanh thu (INC history).

    long = rate window 30m, short = rate window 5m (đúng tinh thần Long/Short của slide).
    baseline = chuỗi p95(5m) suốt 1 tuần, step 5m -> ~2016 mẫu, thừa cho median + MAD.
    Tên metric bám OTel spanmetrics dùng ở chỗ khác trong engine.
    """
    def p95(service: str, window: str) -> str:
        return (
            "histogram_quantile(0.95, sum by (le) (rate("
            f'traces_span_metrics_duration_milliseconds_bucket{{service_name="{service}"}}[{window}])))'
        )

    metrics: list[LatencyMetric] = []
    # "Storefront" = frontend + các trang doanh thu. frontend đứng đầu vì slide nhắm p95 storefront.
    for svc in ("frontend", "checkout", "cart", "payment"):
        metrics.append(LatencyMetric(
            name=f"{svc}_latency_p95_mw",
            service=svc,
            long_query=p95(svc, "30m"),
            short_query=p95(svc, "5m"),
            baseline_query=f"({p95(svc, '5m')})[1w:5m]",
        ))
    return metrics
