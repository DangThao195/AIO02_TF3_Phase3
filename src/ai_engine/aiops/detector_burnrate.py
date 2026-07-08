"""Burn-rate detector — C2 layer 1 (deterministic, the ONLY source of `critical` pages).

Google SRE Workbook multiwindow multi-burn-rate: a signal fires only when BOTH the long
and short windows breach the burn-rate threshold. This kills 5-minute spikes and is the
reason critical alerts stay trustworthy (precision target ≥90%, C2).

The detector reads the SLI recording rules (recording_rules.yaml) via PromQL. The math is
pure and unit-testable; the only I/O is `PrometheusClient.scalar`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..common.config import SLOConfig
from ..common.schemas import Severity, SourceLayer
from ..common.telemetry import PrometheusClient, TelemetryError


_TIERS = [
    (14.4, "1h", "5m", Severity.CRITICAL),
    (6.0, "6h", "30m", Severity.WARNING),
    (1.0, "3d", "6h", Severity.INFO),
]


@dataclass(frozen=True)
class SLODef:
    """A single SLO to watch. `error_ratio_rule` is the recording-rule name prefix."""

    service: str
    sli: str
    target: float
    error_rule_prefix: str

    @property
    def error_budget(self) -> float:
        return 1.0 - self.target


@dataclass
class BurnSignal:
    service: str
    sli: str
    severity: Severity
    burn_rate: float
    error_ratio: float
    target: float
    long_window: str
    short_window: str
    source_layer: SourceLayer = SourceLayer.SLO_BURNRATE


def default_slos(slo: SLOConfig) -> list[SLODef]:
    return [
        SLODef("checkout", "checkout_success_ratio", slo.checkout_target, "sli:checkout_error:ratio_rate"),
        SLODef("frontend", "browse_success_ratio", slo.browse_target, "sli:frontend_error:ratio_rate"),
        SLODef("cart", "cart_success_ratio", slo.cart_target, "sli:cart_error:ratio_rate"),
    ]


def classify(error_ratio_long: float, error_ratio_short: float, budget: float) -> tuple[Severity, float] | None:
    """Pure decision: given long/short error ratios and the budget, return (severity, burn_rate)
    for the most severe tier where BOTH windows breach, else None."""
    for burn_rate, _lw, _sw, severity in _TIERS:
        threshold = burn_rate * budget
        if error_ratio_long > threshold and error_ratio_short > threshold:
            long_burn = error_ratio_long / budget if budget else 0.0
            return severity, long_burn
    return None


class BurnRateDetector:
    def __init__(self, prom: PrometheusClient, slos: list[SLODef]):
        self._prom = prom
        self._slos = slos

    async def evaluate(self) -> list[BurnSignal]:
        """Evaluate every SLO across the SRE tiers. Returns the most-severe firing signal per SLO."""
        signals: list[BurnSignal] = []
        for slo in self._slos:
            signal = await self._evaluate_one(slo)
            if signal is not None:
                signals.append(signal)
        return signals

    async def _evaluate_one(self, slo: SLODef) -> BurnSignal | None:

        try:
            for burn_rate, lw, sw, severity in _TIERS:
                long_ratio = await self._prom.scalar(f"{slo.error_rule_prefix}{lw}", default=None)
                short_ratio = await self._prom.scalar(f"{slo.error_rule_prefix}{sw}", default=None)
                if long_ratio is None or short_ratio is None:
                    continue
                threshold = burn_rate * slo.error_budget
                if long_ratio > threshold and short_ratio > threshold:
                    return BurnSignal(
                        service=slo.service,
                        sli=slo.sli,
                        severity=severity,
                        burn_rate=round(long_ratio / slo.error_budget, 1) if slo.error_budget else 0.0,
                        error_ratio=round(short_ratio, 4),
                        target=slo.target,
                        long_window=lw,
                        short_window=sw,
                    )
        except TelemetryError:
            return None
        return None
