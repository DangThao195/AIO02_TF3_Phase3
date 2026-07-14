"""Anomaly detector — C2 layer 2 (ML/statistical, WARNING max, never pages).

Covers signals with no direct SLO: per-service latency, kafka consumer lag, memory (OOM
risk), 429 rate. This is the "catch the injected fault BEFORE on-call notices / before the
system dies" layer the roadmap calls for.

Focus (from onboarding/INCIDENT_HISTORY.md — history repeats):
  INC-1 checkout DB pool exhaustion -> checkout/payment latency + error
  INC-2 cart state loss on reschedule -> cart availability
  INC-3 payment deploy readiness gap -> payment errors during rollout
  + flag-injected: kafka lag, email memory leak, high cpu.
So checkout / cart / payment / kafka / email are weighted first.

Two methods, cheap-first:
  1. Robust z-score (median + MAD) — no training, works from ~1 week baseline, resistant to
     the very outliers we hunt. Primary detector.
  2. IsolationForest (optional, [ml] extra) — multivariate, for subtle joint anomalies.
Both are DETECTORS OF CONTEXT: they raise warning/info and enrich the burn-rate incident;
they never emit critical. confidence < 0.7 is dropped before it ever leaves the engine (C2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..common.schemas import Severity, SourceLayer
from ..common.telemetry import PrometheusClient, TelemetryError


FOCUS_WEIGHTS: dict[str, float] = {
    "checkout": 1.0, "payment": 1.0, "cart": 0.9, "kafka": 0.9,
    "email": 0.7, "product-catalog": 0.6, "frontend": 0.6,
}
DEFAULT_WEIGHT = 0.4


@dataclass(frozen=True)
class AnomalyMetric:
    name: str
    service: str
    current_query: str
    baseline_query: str
    higher_is_worse: bool = True
    unit: str = ""


@dataclass
class AnomalySignal:
    service: str
    sli: str
    severity: Severity
    current_value: float
    baseline_median: float
    z_score: float
    confidence: float
    source_layer: SourceLayer = SourceLayer.ML_ANOMALY
    note: str = ""


def robust_zscore(current: float, baseline: list[float]) -> tuple[float, float]:
    """Median + MAD z-score. Returns (z, median). MAD-based so the anomalies we hunt don't
    poison the baseline the way mean/std would. 1.4826 scales MAD to a std estimate."""
    if not baseline:
        return 0.0, 0.0
    median = _median(baseline)
    s = sorted(baseline)
    mad = _median([abs(x - median) for x in s])
    if mad == 0:


        if median == 0:
            return (0.0, 0.0)
        rel = (current - median) / abs(median)
        return (rel / 0.05, median)
    z = (current - median) / (1.4826 * mad)
    return z, median


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


class AnomalyDetector:

    Z_WARNING = 4.0
    Z_INFO = 3.0

    def __init__(self, prom: PrometheusClient, metrics: list[AnomalyMetric]):
        self._prom = prom
        self._metrics = metrics

    async def evaluate(self) -> list[AnomalySignal]:
        signals: list[AnomalySignal] = []
        for m in self._metrics:
            sig = await self._evaluate_one(m)
            if sig is not None and sig.confidence >= 0.7:
                signals.append(sig)
        return signals

    async def _evaluate_one(self, m: AnomalyMetric) -> AnomalySignal | None:
        try:
            current = await self._prom.scalar(m.current_query, default=None)
            baseline = await self._baseline_series(m.baseline_query)
        except TelemetryError:
            return None
        if current is None or len(baseline) < 10:
            return None

        z, median = robust_zscore(current, baseline)
        directed_z = z if m.higher_is_worse else -z
        if directed_z <= 0:
            return None

        weight = FOCUS_WEIGHTS.get(m.service, DEFAULT_WEIGHT)

        eff_warning = self.Z_WARNING / max(weight, 0.1) * 0.5
        eff_info = self.Z_INFO / max(weight, 0.1) * 0.5

        if directed_z >= eff_warning:
            severity = Severity.WARNING
        elif directed_z >= eff_info:
            severity = Severity.INFO
        else:
            return None

        confidence = _confidence(directed_z, weight)
        return AnomalySignal(
            service=m.service,
            sli=m.name,
            severity=severity,
            current_value=round(current, 3),
            baseline_median=round(median, 3),
            z_score=round(directed_z, 2),
            confidence=round(confidence, 2),
            note=f"{m.name} {current:.2f}{m.unit} vs baseline {median:.2f}{m.unit} (z={directed_z:.1f})",
        )

    async def _baseline_series(self, query: str) -> list[float]:
        """A range query returns [[ts,val],...]; reduce to the list of values."""
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


def _confidence(z: float, weight: float) -> float:
    """Map z-score + focus weight to [0,1] confidence. Sigmoid-ish; watched services more
    confident at the same z. Kept simple and monotonic so it's explainable to on-call."""
    base = 1 / (1 + math.exp(-(z - 3)))
    return min(1.0, base * (0.7 + 0.3 * weight))


def default_anomaly_metrics() -> list[AnomalyMetric]:
    """Concrete metric set focused by incident history. Baseline = last 1 week at 5m step.
    Metric names verified against the OTel spanmetrics naming used elsewhere in the engine."""
    def dur_p95(service: str) -> str:
        return (f'histogram_quantile(0.95, sum by (le) '
                f'(rate(traces_span_metrics_duration_milliseconds_bucket{{service_name="{service}"}}[5m])))')

    metrics: list[AnomalyMetric] = []
    for svc in ("checkout", "payment", "cart"):
        metrics.append(AnomalyMetric(
            name=f"{svc}_latency_p95", service=svc,
            current_query=dur_p95(svc),
            baseline_query=f'({dur_p95(svc)})[1w:5m]',
            unit="ms",
        ))

    metrics.append(AnomalyMetric(
        name="kafka_consumer_lag", service="kafka",
        current_query='sum(kafka_consumergroup_lag)',
        baseline_query='(sum(kafka_consumergroup_lag))[1w:5m]',
    ))

    metrics.append(AnomalyMetric(
        name="email_memory_bytes", service="email",
        current_query='sum(container_memory_working_set_bytes{pod=~"email.*"})',
        baseline_query='(sum(container_memory_working_set_bytes{pod=~"email.*"}))[1w:5m]',
    ))
    return metrics
