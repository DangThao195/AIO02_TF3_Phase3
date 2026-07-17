"""Post-remediation verify loop — C6 §OUTPUT verification + C6.6 auto-rollback-on-no-recovery.

After an action executes, the engine does NOT assume it worked. It polls the impacted SLI
for up to 5 minutes. If the metric drops back under the SLO threshold → verified, done. If
the window elapses and it is STILL breached → the action did not help (or made it worse) →
run the rollback and page (C6 failure-mode "action thất bại giữa chừng").

Pure-ish and testable: the Prometheus read and the clock/sleep are injected, so a unit test
drives recovery / no-recovery deterministically without a cluster.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..common.telemetry import PrometheusClient, TelemetryError

log = logging.getLogger("ai_engine.verify_loop")


@dataclass
class VerifyResult:
    recovered: bool
    samples: list[float]
    detail: str


class VerifyLoop:
    def __init__(
        self,
        prom: PrometheusClient,
        window_s: int = 300,
        poll_s: int = 30,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._prom = prom
        self._window_s = window_s
        self._poll_s = poll_s
        self._sleep = sleep

    async def verify(
        self,
        *,
        recovery_query: str,
        threshold: float,
        recovered_when_below: bool = True,
    ) -> VerifyResult:
        """Poll `recovery_query` every poll_s for window_s. Recovered when the value crosses
        `threshold` in the healthy direction (below by default — e.g. error-ratio back under
        budget). A blind telemetry source is treated as NOT recovered (fail-safe → rollback).
        """
        samples: list[float] = []
        elapsed = 0
        while elapsed <= self._window_s:
            try:
                value = await self._prom.scalar(recovery_query, default=None)
            except TelemetryError:
                value = None
            if value is not None:
                samples.append(value)
                healthy = value < threshold if recovered_when_below else value > threshold
                if healthy:
                    return VerifyResult(
                        recovered=True,
                        samples=samples,
                        detail=f"recovered: {value:.4f} crossed {threshold} after {elapsed}s",
                    )
            if elapsed + self._poll_s > self._window_s:
                break
            await self._sleep(self._poll_s)
            elapsed += self._poll_s

        last = samples[-1] if samples else None
        return VerifyResult(
            recovered=False,
            samples=samples,
            detail=(
                f"NOT recovered after {self._window_s}s "
                f"(last={last}, threshold={threshold}, blind={not samples})"
            ),
        )
