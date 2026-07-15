"""Weekly AI cost report + budget threshold alerts — C5.4 / C5.5 / C5.6.

Reads the cost counters back from Prometheus (single source of truth — the meter already
exports them), attributes spend per feature, compares this week's total against the
CDO-supplied weekly budget, and:

  - writes `TF3/cost/reports/YYYY-Www.md` in the exact C5 §2 format (C5.4), and
  - returns budget AlertEvents at 80% (warning) / 100% (critical) with source_layer=cost
    (C5.5), using the weekly budget from CostConfig / AI_BUDGET_WEEKLY_USD (C5.6).

The Prometheus read is injected so this is unit-testable with a fake that returns canned
`increase(...)` values — no live TSDB needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..common.config import CostConfig
from ..common.metrics import COST_BUDGET_USED_RATIO, COST_BUDGET_WEEKLY
from ..common.schemas import AlertEvent, AlertEvidence, Severity, SourceLayer

log = logging.getLogger("ai_engine.cost_report")

_REPORTS_DIR = Path(__file__).resolve().parents[3] / "cost" / "reports"


@dataclass
class FeatureSpend:
    feature: str
    tokens_in: float = 0.0
    tokens_out: float = 0.0
    usd: float = 0.0
    requests: float = 0.0


@dataclass
class CostSnapshot:
    total_usd: float
    per_feature: list[FeatureSpend]
    cache_hit_ratio: float | None = None
    prev_total_usd: float | None = None
    incomplete: list[str] = field(default_factory=list)


# A PromReader is anything with async .instant(query) and .scalar(query, default).
PromReader = object


class CostReporter:
    def __init__(self, prom, cfg: CostConfig, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._prom = prom
        self._cfg = cfg
        self._clock = clock

    async def snapshot(self, window: str = "7d") -> CostSnapshot:
        """Pull per-feature spend for the trailing `window` from Prometheus counters."""
        incomplete: list[str] = []

        async def _series(query: str) -> list[dict]:
            try:
                return await self._prom.instant(query)
            except Exception as exc:
                incomplete.append(f"{query}: {exc}")
                return []

        usd_rows = await _series(f'sum by (feature) (increase(ai_cost_usd_total[{window}]))')
        in_rows = await _series(
            f'sum by (feature) (increase(ai_cost_tokens_total{{direction="input"}}[{window}]))')
        out_rows = await _series(
            f'sum by (feature) (increase(ai_cost_tokens_total{{direction="output"}}[{window}]))')

        by_feature: dict[str, FeatureSpend] = {}

        def _bump(rows, attr):
            for r in rows:
                feat = r.get("metric", {}).get("feature", "untagged")
                val = float(r.get("value", [0, 0])[1])
                fs = by_feature.setdefault(feat, FeatureSpend(feature=feat))
                setattr(fs, attr, getattr(fs, attr) + val)

        _bump(usd_rows, "usd")
        _bump(in_rows, "tokens_in")
        _bump(out_rows, "tokens_out")

        total = sum(fs.usd for fs in by_feature.values())
        try:
            cache_hit = await self._prom.scalar("ai_cache_hit_ratio", default=None)
        except Exception:
            cache_hit = None
        try:
            prev = await self._prom.scalar(
                f'sum(increase(ai_cost_usd_total[{window}] offset {window}))', default=None)
        except Exception:
            prev = None

        return CostSnapshot(
            total_usd=round(total, 4),
            per_feature=sorted(by_feature.values(), key=lambda f: -f.usd),
            cache_hit_ratio=cache_hit,
            prev_total_usd=prev,
            incomplete=incomplete,
        )

    def evaluate_budget(self, snapshot: CostSnapshot) -> list[AlertEvent]:
        """C5.5/5.6 — emit budget threshold alerts. Also exports the budget gauges so CDO
        sees ratio in Grafana without re-deriving it."""
        budget = self._cfg.weekly_budget_usd
        COST_BUDGET_WEEKLY.set(budget)
        ratio = snapshot.total_usd / budget if budget > 0 else 0.0
        COST_BUDGET_USED_RATIO.set(ratio)

        alerts: list[AlertEvent] = []
        now = self._clock()
        if ratio >= 1.0:
            sev, label = Severity.CRITICAL, "100%"
        elif ratio >= self._cfg.warn_ratio:
            sev, label = Severity.WARNING, f"{int(self._cfg.warn_ratio*100)}%"
        else:
            return alerts

        alerts.append(AlertEvent(
            alert_id=f"TF3-COST-{now:%Y%m%d}-{int(ratio*100):03d}",
            fingerprint=f"ai-cost|weekly-budget|{label}",
            severity=sev,
            source_layer=SourceLayer.COST,
            service="ai-engine",
            sli_impacted="ai_weekly_budget",
            slo_target=budget,
            current_value=round(snapshot.total_usd, 2),
            starts_at=now,
            confidence=1.0,
            evidence=AlertEvidence(
                promql="sum(increase(ai_cost_usd_total[7d]))",
                log_query="feature-level breakdown: sum by (feature)(increase(ai_cost_usd_total[7d]))",
            ),
            suggested_action=(
                "Chạm 100% trần: tăng cache TTL, hạ rca-assistant xuống model rẻ/mock, "
                "KHÔNG tắt guardrail (C5)." if sev is Severity.CRITICAL else
                "Chạm 80% trần: bàn ở standup; xem feature nào tăng đột biến."
            ),
        ))
        return alerts

    def render_markdown(self, snapshot: CostSnapshot) -> str:
        budget = self._cfg.weekly_budget_usd
        ratio = (snapshot.total_usd / budget * 100) if budget else 0.0
        now = self._clock()
        _, week, _ = now.isocalendar()

        change = ""
        if snapshot.prev_total_usd:
            delta = (snapshot.total_usd - snapshot.prev_total_usd)
            pct = (delta / snapshot.prev_total_usd * 100) if snapshot.prev_total_usd else 0.0
            change = f"[tuần trước: ${snapshot.prev_total_usd:.2f}, thay đổi: {pct:+.1f}%]"
        cache = f"{snapshot.cache_hit_ratio*100:.0f}%" if snapshot.cache_hit_ratio is not None else "n/a"

        lines = [
            f"# AI Cost Report — Tuần {week:02d}",
            f"> Sinh tự động {now.isoformat()} (C5.4).",
            "",
            "## Tổng quan",
            f"- Tổng chi AI tuần: **${snapshot.total_usd:.2f} / trần ${budget:.2f} ({ratio:.0f}%)** {change}",
            f"- Cache hit: {cache}",
            "",
            "## Phân rã",
            "| Feature | Tokens in/out | USD | % |",
            "|---|---|---|---|",
        ]
        for fs in snapshot.per_feature:
            share = (fs.usd / snapshot.total_usd * 100) if snapshot.total_usd else 0.0
            lines.append(
                f"| {fs.feature} | {fs.tokens_in:.0f}/{fs.tokens_out:.0f} | ${fs.usd:.4f} | {share:.0f}% |")
        if not snapshot.per_feature:
            lines.append("| (no cost data in window — mock llm = $0 or meter cold) | — | $0.00 | — |")

        lines += [
            "",
            "## Diễn giải spike (nếu có)",
            "- " + ("; ".join(snapshot.incomplete) if snapshot.incomplete
                    else "Không có gap số liệu. Chưa phát hiện spike bất thường."),
            "",
            "## Đề xuất tối ưu tuần tới",
            "- Nếu cache hit thấp: tăng TTL 24h→72h. Nếu guardrail-judge tốn: cân nhắc rule-based trước LLM-judge.",
            "",
        ]
        return "\n".join(lines)

    def write_report(self, snapshot: CostSnapshot, out_dir: Path | None = None) -> Path:
        now = self._clock()
        year, week, _ = now.isocalendar()
        d = out_dir or _REPORTS_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{year}-W{week:02d}.md"
        path.write_text(self.render_markdown(snapshot), encoding="utf-8")
        log.info("cost report written: %s", path)
        return path
