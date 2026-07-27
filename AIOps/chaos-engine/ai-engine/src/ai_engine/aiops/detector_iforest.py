"""IsolationForest detector — C2 layer 2, bắt anomaly TINH VI mà z-score điểm đơn bỏ sót.

Hiện thực hoá phần "IsolationForest (optional, [ml] extra)" mà docstring detector_anomaly
hứa. Bài học W1-D1 áp nguyên văn:

  - **Feature engineering là BẮT BUỘC** — raw time series không đủ ngữ cảnh. Mỗi điểm
    được mô tả bằng 6 feature: value, rolling mean, rolling std, rate-of-change, lag-1,
    lag-k. Nhờ vậy bắt được anomaly dạng "giá trị chưa vượt ngưỡng nhưng ĐANG leo bất
    thường" (drift, leak) hoặc "biến thiên đột ngột quanh mức bình thường" — vô hình
    với robust z-score điểm đơn.
  - Hyperparams theo playbook: n_estimators=200, contamination 0.02 (tune XUỐNG nếu ồn),
    max_features=1.0 (6 feature < 10).
  - Layer 2 discipline: WARNING tối đa, confidence <0.7 bị chặn, không bao giờ page.

sklearn import lười ([ml] extra): thiếu sklearn → detector câm (available=False), engine
chạy tiếp bằng z-score — degrade, không chết.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..common.schemas import Severity, SourceLayer
from .detector_anomaly import AnomalyMetric, AnomalySignal, FOCUS_WEIGHTS, DEFAULT_WEIGHT

log = logging.getLogger("ai_engine.detector_iforest")

N_ESTIMATORS = 200
CONTAMINATION = 0.02
ROLL_WINDOW = 12   # 12 điểm 5m = 1h ngữ cảnh gần
LAG_K = 12         # so với chính nó 1h trước
MIN_BASELINE = 60  # <60 điểm (5h) thì chưa đủ để fit — im lặng, không đoán


def build_features(series: list[float], *, window: int = ROLL_WINDOW, lag_k: int = LAG_K) -> list[list[float]]:
    """Ma trận feature từ raw series (pure python — test không cần sklearn).
    Mỗi hàng i (bắt đầu từ max(window, lag_k)): [value, roll_mean, roll_std, rate_of_change,
    lag_1, lag_k]. Trả [] nếu series quá ngắn."""
    start = max(window, lag_k)
    if len(series) <= start:
        return []
    rows: list[list[float]] = []
    for i in range(start, len(series)):
        win = series[i - window:i]
        mean = sum(win) / window
        var = sum((x - mean) ** 2 for x in win) / window
        rows.append([
            series[i],
            mean,
            var ** 0.5,
            series[i] - series[i - 1],
            series[i - 1],
            series[i - lag_k],
        ])
    return rows


@dataclass
class IForestVerdict:
    is_anomaly: bool
    score: float        # decision_function: càng âm càng bất thường
    confidence: float


class IForestSeriesDetector:
    """Fit-per-evaluate trên baseline của chính series đó (unsupervised, không cần label —
    đúng tinh thần 'không hard-code' của detector layer 2). 200 trees × ~2k điểm × 6
    feature ≈ vài chục ms — thoải mái trong tick 30s."""

    def __init__(self, contamination: float = CONTAMINATION, n_estimators: int = N_ESTIMATORS):
        self._contamination = contamination
        self._n_estimators = n_estimators
        try:
            from sklearn.ensemble import IsolationForest  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False
            log.info("sklearn không có ([ml] extra chưa cài) — iforest detector tắt, z-score vẫn chạy")

    def evaluate_series(self, series: list[float]) -> IForestVerdict | None:
        """Chấm điểm ĐIỂM CUỐI của series so với phần còn lại. None = không đủ dữ liệu/lib."""
        if not self.available:
            return None
        rows = build_features(series)
        if len(rows) < MIN_BASELINE:
            return None

        from sklearn.ensemble import IsolationForest

        baseline, current = rows[:-1], rows[-1:]
        model = IsolationForest(
            n_estimators=self._n_estimators,
            contamination=self._contamination,
            max_features=1.0,
            random_state=42,  # deterministic — cùng input cùng verdict, giải thích được
        )
        model.fit(baseline)
        is_anom = bool(model.predict(current)[0] == -1)
        score = float(model.decision_function(current)[0])
        # decision_function ~[-0.3, 0.3]; càng âm càng lạ. Map về [0,1] đơn điệu.
        confidence = min(0.95, max(0.0, 0.7 + (-score) * 1.5)) if is_anom else 0.0
        return IForestVerdict(is_anomaly=is_anom, score=round(score, 4),
                              confidence=round(confidence, 2))


class MultiFeatureIForestDetector:
    """Bản async cùng khuôn AnomalyDetector: đọc baseline từ Prometheus theo cùng
    AnomalyMetric, emit AnomalySignal (sli đuôi `_iforest` để không giẫm fingerprint
    z-score — correlator vẫn gộp về cùng incident theo cluster)."""

    def __init__(self, prom, metrics: list[AnomalyMetric]):
        self._prom = prom
        self._metrics = metrics
        self._core = IForestSeriesDetector()

    @property
    def available(self) -> bool:
        return self._core.available

    async def evaluate(self) -> list[AnomalySignal]:
        if not self._core.available:
            return []
        from ..common.telemetry import TelemetryError

        signals: list[AnomalySignal] = []
        for m in self._metrics:
            try:
                current = await self._prom.scalar(m.current_query, default=None)
                baseline = await self._baseline_series(m.baseline_query)
            except TelemetryError:
                continue
            if current is None or len(baseline) < MIN_BASELINE:
                continue

            verdict = self._core.evaluate_series([*baseline, float(current)])
            if verdict is None or not verdict.is_anomaly:
                continue
            weight = FOCUS_WEIGHTS.get(m.service, DEFAULT_WEIGHT)
            confidence = round(min(0.95, verdict.confidence * (0.7 + 0.3 * weight)), 2)
            if confidence < 0.7:  # C2: dưới 0.7 không rời khỏi engine
                continue
            signals.append(AnomalySignal(
                service=m.service, sli=f"{m.name}_iforest", severity=Severity.WARNING,
                current_value=round(float(current), 3), baseline_median=0.0,
                z_score=0.0, confidence=confidence,
                source_layer=SourceLayer.ML_ANOMALY,
                note=(f"{m.name} multivariate anomaly (iforest df={verdict.score}) — "
                      f"pattern lạ dù giá trị điểm đơn chưa vượt ngưỡng"),
            ))
        return signals

    async def _baseline_series(self, query: str) -> list[float]:
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
