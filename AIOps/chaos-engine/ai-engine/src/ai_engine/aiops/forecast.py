"""Dự báo capacity & cost — AIOps mở rộng (RULES §4 "dự báo capacity/cost").

Trả lời 2 câu hỏi vận hành mà detection KHÔNG trả lời được:
  1. "Còn bao lâu nữa thì cạn?" — pool/memory/disk đang leo, khi nào chạm trần?
  2. "Cuối tuần có vỡ ngân sách AI không?" — cost đang chạy, dự phóng tới cuối kỳ?

Phương pháp: **hồi quy tuyến tính OLS trên cửa sổ gần** (không phải ARIMA/Prophet).
Lý do chọn (bảo vệ được trước hội đồng):
  - Ràng buộc đề: "đo phải nhẹ, đừng dựng cụm nặng cho oách". OLS là O(n), vài chục dòng,
    không thêm dependency, chạy trong tick 30s.
  - Sự cố capacity ở TF3 (INC-1 pool, INC-6 memory leak) là **xu hướng đơn điệu** trong
    cửa sổ giờ — tuyến tính bắt đủ. Seasonality ngày/tuần KHÔNG quan trọng khi hỏi
    "còn 40 phút nữa cạn pool".
  - Giải thích được cho on-call: "đang tăng X đơn vị/phút, còn Y phút tới trần" — ARIMA
    cho số đẹp hơn nhưng on-call không cãi lại được nó lúc 2h sáng.

Kỷ luật (giống mọi detector layer-2):
  - WARNING tối đa, không bao giờ page critical (burn-rate giữ độc quyền page).
  - Chỉ báo khi fit đủ tin (R² ≥ 0.5) VÀ xu hướng đủ dốc VÀ chạm trần trong horizon.
    Ba điều kiện AND → không báo vì nhiễu lăn tăn.
  - Không đủ dữ liệu / xu hướng đi xuống / fit tệ → im lặng (None), không đoán bừa.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..common.schemas import Severity, SourceLayer
from .detector_anomaly import AnomalySignal

log = logging.getLogger("ai_engine.forecast")

MIN_POINTS = 12          # <12 mẫu (1h @5m) thì chưa đủ để nói về xu hướng
MIN_R_SQUARED = 0.5      # fit tệ hơn nửa phương sai giải thích được → không tin
DEFAULT_HORIZON_MIN = 120  # chỉ quan tâm "cạn trong 2h tới" — xa hơn là chuyện của capacity planning


@dataclass(frozen=True)
class TrendFit:
    """Kết quả fit y = slope*x + intercept. `slope` theo đơn vị-metric / bước-mẫu."""

    slope: float
    intercept: float
    r_squared: float
    n: int


def fit_linear(values: list[float]) -> TrendFit | None:
    """OLS thuần Python (không numpy — engine phải chạy được khi thiếu [ml] extra).
    x = chỉ số mẫu 0..n-1. Trả None nếu không đủ điểm hoặc phương sai x bằng 0."""
    n = len(values)
    if n < MIN_POINTS:
        return None

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n

    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    # R² = 1 - SS_res/SS_tot. SS_tot=0 (chuỗi phẳng tuyệt đối) → fit hoàn hảo nhưng slope=0,
    # caller sẽ tự loại vì slope không đủ dốc.
    ss_tot = sum((y - mean_y) ** 2 for y in values)
    if ss_tot == 0:
        return TrendFit(slope=0.0, intercept=intercept, r_squared=1.0, n=n)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
    r_squared = 1.0 - ss_res / ss_tot

    return TrendFit(slope=slope, intercept=intercept, r_squared=round(r_squared, 4), n=n)


def minutes_to_threshold(
    values: list[float], threshold: float, *, step_minutes: float = 5.0
) -> tuple[float | None, TrendFit | None]:
    """Còn bao nhiêu PHÚT nữa chuỗi chạm `threshold` theo xu hướng hiện tại.

    Trả (minutes, fit). minutes=None nghĩa là: không đủ dữ liệu, fit tệ, xu hướng đi
    ngược hướng threshold, hoặc đã vượt threshold rồi (lúc đó detection lo, không phải
    forecast). Không bao giờ raise."""
    fit = fit_linear(values)
    if fit is None or fit.r_squared < MIN_R_SQUARED:
        return None, fit

    current = values[-1]
    if current >= threshold:
        return None, fit  # đã chạm/vượt — việc của detector, không phải dự báo
    if fit.slope <= 0:
        return None, fit  # đang đi xuống hoặc phẳng → không bao giờ chạm

    steps_left = (threshold - current) / fit.slope
    return round(steps_left * step_minutes, 1), fit


@dataclass(frozen=True)
class CapacityMetric:
    """Một tài nguyên có TRẦN cứng: pool connection, memory limit, disk."""

    name: str
    service: str
    query: str        # PromQL trả chuỗi giá trị hiện tại
    ceiling: float    # trần (max connections / memory limit bytes / ...)
    unit: str = ""


class CapacityForecaster:
    """Dự báo cạn tài nguyên. Emit AnomalySignal (WARNING) đi thẳng vào Correlator —
    không cần sửa correlator, dùng chung đường alert với mọi layer-2."""

    def __init__(self, prom, metrics: list[CapacityMetric], horizon_min: int = DEFAULT_HORIZON_MIN):
        self._prom = prom
        self._metrics = metrics
        self._horizon = horizon_min

    async def evaluate(self) -> list[AnomalySignal]:
        from ..common.telemetry import TelemetryError

        signals: list[AnomalySignal] = []
        for m in self._metrics:
            try:
                series = await self._series(m.query)
            except TelemetryError:
                continue  # telemetry mù → im lặng, các detector khác vẫn chạy
            if len(series) < MIN_POINTS:
                continue

            eta, fit = minutes_to_threshold(series, m.ceiling)
            if eta is None or fit is None or eta > self._horizon:
                continue  # không cạn trong horizon → không làm phiền on-call

            # Confidence từ độ tin của fit (R²) — càng khớp tuyến tính càng chắc.
            confidence = round(min(0.95, 0.6 + fit.r_squared * 0.35), 2)
            if confidence < 0.7:
                continue  # C2: dưới 0.7 không rời khỏi engine

            signals.append(AnomalySignal(
                service=m.service,
                sli=f"{m.name}_forecast_exhaustion",
                severity=Severity.WARNING,   # layer-2: không bao giờ page
                current_value=round(series[-1], 3),
                baseline_median=m.ceiling,
                z_score=0.0,
                confidence=confidence,
                source_layer=SourceLayer.ML_ANOMALY,
                note=(f"{m.name} dự báo chạm trần {m.ceiling}{m.unit} trong ~{eta:.0f} phút "
                      f"(hiện {series[-1]:.1f}{m.unit}, +{fit.slope:.2f}{m.unit}/mẫu, R²={fit.r_squared})"),
            ))
        return signals

    async def _series(self, query: str) -> list[float]:
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
        return values


@dataclass(frozen=True)
class BudgetForecast:
    spent_usd: float
    projected_usd: float
    budget_usd: float
    days_elapsed: float
    days_total: float
    will_exceed: bool
    projected_ratio: float

    def to_dict(self) -> dict:
        return {
            "spent_usd": self.spent_usd,
            "projected_usd": self.projected_usd,
            "budget_usd": self.budget_usd,
            "will_exceed": self.will_exceed,
            "projected_ratio": self.projected_ratio,
        }


def forecast_budget(
    *, spent_usd: float, days_elapsed: float, budget_usd: float, days_total: float = 7.0
) -> BudgetForecast:
    """Dự phóng cost cuối kỳ theo tốc độ chi hiện tại (run-rate tuyến tính).

    Khác `cost_report` (báo cáo ĐÃ chi) — cái này trả lời "cứ đà này CÓ vỡ trần không",
    tức là cảnh báo TRƯỚC khi chạm 100%, đủ thời gian hạ model/tăng cache."""
    if days_elapsed <= 0:
        raise ValueError(f"days_elapsed must be > 0, got {days_elapsed}")
    if budget_usd <= 0:
        raise ValueError(f"budget_usd must be > 0, got {budget_usd}")

    run_rate = spent_usd / days_elapsed          # USD/ngày
    projected = run_rate * days_total
    ratio = projected / budget_usd
    return BudgetForecast(
        spent_usd=round(spent_usd, 4),
        projected_usd=round(projected, 2),
        budget_usd=budget_usd,
        days_elapsed=days_elapsed,
        days_total=days_total,
        will_exceed=projected > budget_usd,
        projected_ratio=round(ratio, 3),
    )


def default_capacity_metrics() -> list[CapacityMetric]:
    """Tài nguyên có trần, ưu tiên theo lịch sử sự cố (INC-1 pool, INC-6 memory)."""
    return [
        CapacityMetric(
            name="postgres_connections", service="product-catalog",
            query='(sum(pg_stat_activity_count))[2h:5m]',
            ceiling=100.0,  # max_connections mặc định; CDO chỉnh qua env nếu khác
        ),
        CapacityMetric(
            name="recommendation_memory", service="recommendation",
            query='(sum(container_memory_working_set_bytes{pod=~"recommendation.*"}))[2h:5m]',
            ceiling=512 * 1024 * 1024,  # 512Mi limit
            unit="B",
        ),
        CapacityMetric(
            name="kafka_lag", service="kafka",
            query='(sum(kafka_consumergroup_lag))[2h:5m]',
            ceiling=10000.0,  # lag > 10k = đơn hàng trễ thấy rõ (INC-5)
        ),
    ]
