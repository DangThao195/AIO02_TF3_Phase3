"""Chaos validation harness — đo CHÍNH pipeline detect→correlate→RCA, không đo app.

Bài học W3-D2: "system alive" không phải là thước đo; thước đo là confusion matrix của
pipeline AIOps. Harness này replay 10 experiment (map INC-1..8 từ INCIDENT_HISTORY.md
+ retry-storm + multi-fault) và 2 control run (no-fault, dup-storm) qua Correlator +
RCAAssistant thật với telemetry stub — offline, deterministic, chạy được trong CI.

Acceptance (playbook §1.8): recall ≥ 70% · RCA top-3 accuracy ≥ 70% · false alarm ≤ 1.

Mỗi experiment: fault "bắt đầu" ở tick 1 (tín hiệu layer-2 anomaly), SLO vỡ ở tick 2
(burn-rate) — đúng trình tự thật (warning đi trước breach). MTTD mô phỏng = số tick từ
fault-start đến incident đầu tiên × TICK_S (30s/tick như engine thật).

Chạy:  .venv\\Scripts\\python scripts\\chaos_validate.py
Output: console + chaos/scoreboard.md (bằng chứng định lượng cho Ops Review).
Exit 0 = đạt acceptance, 1 = trượt.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_engine.aiops.correlator import Correlator, Incident  # noqa: E402
from ai_engine.aiops.detector_anomaly import AnomalySignal  # noqa: E402
from ai_engine.aiops.detector_burnrate import BurnSignal  # noqa: E402
from ai_engine.aiops.rca_assistant import RCAAssistant  # noqa: E402
from ai_engine.common.schemas import Severity, SourceLayer  # noqa: E402

TICK_S = 30
RECALL_MIN, RCA_ACC_MIN, FALSE_ALARM_MAX = 0.70, 0.70, 1


# ── telemetry stubs: RCA fail-graceful path (pack ships without cluster) ──
class _StubJaeger:
    async def find_error_traces(self, service, limit=5):
        return []


class _StubOS:
    async def search(self, index, body):
        return {}


def _burn(service: str) -> BurnSignal:
    return BurnSignal(service=service, sli="availability", severity=Severity.CRITICAL,
                      burn_rate=14.4, error_ratio=0.05, target=0.99,
                      long_window="1h", short_window="5m")


def _anom(service: str, sli: str, note: str, conf: float = 0.85) -> AnomalySignal:
    return AnomalySignal(service=service, sli=sli, severity=Severity.WARNING,
                         current_value=9.0, baseline_median=1.0, z_score=8.0,
                         confidence=conf, source_layer=SourceLayer.ML_ANOMALY,
                         note=f"{service} {note}")


@dataclass
class Experiment:
    exp_id: str
    inc_ref: str
    description: str
    # tick -> (burn signals, anomaly signals)
    ticks: dict[int, tuple[list, list]]
    expected_culprit: str | None  # None = control (không được có incident)
    expected_incidents: int | None = None  # dùng cho control/multi-fault
    fault_start_tick: int = 1


@dataclass
class Result:
    exp: Experiment
    detected: bool = False
    mttd_s: int | None = None
    rca_hit: bool | None = None
    incidents: int = 0
    notes: list[str] = field(default_factory=list)


def experiments() -> list[Experiment]:
    return [
        Experiment("exp01", "INC-1", "PostgreSQL pool exhaustion (checkout ← product-catalog)",
                   {1: ([], [_anom("product-catalog", "latency_p95", "pool wait spike")]),
                    2: ([_burn("checkout")], [_anom("product-catalog", "latency_p95", "pool wait spike")])},
                   "product-catalog"),
        Experiment("exp02", "INC-2", "Valkey cart state loss (cart ← valkey-cart, KHÔNG restart)",
                   {1: ([], [_anom("valkey-cart", "availability", "pod rescheduled, state gone")]),
                    2: ([_burn("cart")], [_anom("valkey-cart", "availability", "pod rescheduled")])},
                   "valkey-cart"),
        Experiment("exp03", "INC-3", "gRPC EventStream timeout lúc deploy (fraud-detection ← kafka)",
                   {1: ([], [_anom("kafka", "eventstream_errors", "grpc status 4 deadline")]),
                    2: ([_burn("fraud-detection")], [_anom("kafka", "eventstream_errors", "grpc status 4")])},
                   "kafka"),
        Experiment("exp04", "INC-4", "Bedrock 429 rate limit (product-reviews ← llm)",
                   {1: ([], [_anom("llm", "http_429_rate", "429 too many requests")]),
                    2: ([_burn("product-reviews")], [_anom("llm", "http_429_rate", "429 flood")])},
                   "llm"),
        Experiment("exp05", "INC-5", "Kafka consumer lag (accounting ← kafka)",
                   {1: ([], [_anom("kafka", "consumer_lag", "lag 12000 msgs")]),
                    2: ([_burn("accounting")], [_anom("kafka", "consumer_lag", "lag 15000 msgs")])},
                   "kafka"),
        Experiment("exp06", "INC-6", "Memory pressure + GC (frontend ← recommendation)",
                   {1: ([], [_anom("recommendation", "memory_working_set", "RAM 95%, GC pauses")]),
                    2: ([_burn("frontend")], [_anom("recommendation", "memory_working_set", "RAM 96%")])},
                   "recommendation"),
        Experiment("exp07", "INC-7", "Circuit breaker kẹt OPEN (product-reviews chính chủ)",
                   {1: ([], [_anom("product-reviews", "breaker_state", "breaker stuck OPEN")]),
                    2: ([_burn("product-reviews")], [])},
                   "product-reviews"),
        Experiment("exp08", "INC-8", "Cold start currency (checkout ← currency, self-heal)",
                   {1: ([], [_anom("currency", "startup_latency", "cold start warming cache")]),
                    2: ([_burn("checkout")], [_anom("currency", "startup_latency", "cold start")])},
                   "currency"),
        Experiment("exp09", "RETRY-STORM", "Retry storm: payment (victim) ồn hơn product-catalog (culprit)",
                   {1: ([], [_anom("product-catalog", "latency_p95", "pool wait — TRUE culprit")]),
                    2: ([_burn("checkout")],
                        [_anom("product-catalog", "latency_p95", "pool wait"),
                         _anom("payment", "error_rate", "retry storm noise — victim"),
                         _anom("payment", "latency_p95", "retry storm noise — victim")])},
                   "product-catalog"),
        Experiment("exp10", "MULTI-FAULT", "2 fault độc lập cùng lúc → phải ra 2 incident, không gộp",
                   {2: ([_burn("checkout"), _burn("frontend")], [])},
                   "checkout", expected_incidents=2, fault_start_tick=2),
        # Controls — đo false alarm
        Experiment("ctrl01", "CONTROL", "No fault: telemetry sạch → 0 incident",
                   {1: ([], []), 2: ([], []), 3: ([], [])},
                   None, expected_incidents=0),
        Experiment("ctrl02", "CONTROL", "Dup storm: cùng burn signal 3 tick → dedup fold về 1 incident",
                   {2: ([_burn("checkout")], []), 3: ([_burn("checkout")], []),
                    4: ([_burn("checkout")], [])},
                   None, expected_incidents=1),
    ]


async def run_experiment(exp: Experiment) -> Result:
    t = [1000.0]
    correlator = Correlator(clock=lambda: t[0])
    rca = RCAAssistant(None, _StubOS(), _StubJaeger())
    res = Result(exp=exp)

    first_critical: Incident | None = None
    max_tick = max(exp.ticks)
    for tick in range(1, max_tick + 1):
        t[0] = 1000.0 + tick * TICK_S
        burns, anoms = exp.ticks.get(tick, ([], []))
        incidents = correlator.correlate(burns, anoms)
        res.incidents += len(incidents)

        for inc in incidents:
            hit = exp.expected_culprit is not None and (
                inc.primary.service == exp.expected_culprit
                or any(exp.expected_culprit in s for s in inc.correlated_signals)
            )
            if hit and not res.detected:
                res.detected = True
                res.mttd_s = (tick - exp.fault_start_tick + 1) * TICK_S
            if first_critical is None and inc.primary.severity is Severity.CRITICAL:
                first_critical = inc

    # RCA top-3: chỉ chấm trên incident critical (burn-rate) như pipeline thật
    if exp.expected_culprit and first_critical is not None:
        pack = await rca.build(first_critical)
        res.rca_hit = any(exp.expected_culprit in h.text for h in pack.hypotheses[:3])
        top = pack.hypotheses[0]
        res.notes.append(f"H1={top.text[:60]}… (score {top.rank_score})")
    return res


def scoreboard(results: list[Result]) -> tuple[str, bool]:
    faults = [r for r in results if r.exp.expected_culprit is not None]
    controls = [r for r in results if r.exp.expected_culprit is None]

    tp = sum(1 for r in faults if r.detected)
    fn = len(faults) - tp
    recall = tp / len(faults) if faults else 0.0

    rca_scored = [r for r in faults if r.rca_hit is not None]
    rca_acc = (sum(1 for r in rca_scored if r.rca_hit) / len(rca_scored)) if rca_scored else 0.0

    false_alarms = sum(max(0, r.incidents - (r.exp.expected_incidents or 0)) for r in controls)
    multi_ok = all(r.incidents >= (r.exp.expected_incidents or 0)
                   for r in results if r.exp.expected_incidents)

    mttds = sorted(r.mttd_s for r in faults if r.mttd_s is not None)
    mttd_p50 = mttds[len(mttds) // 2] if mttds else None

    passed = recall >= RECALL_MIN and rca_acc >= RCA_ACC_MIN and false_alarms <= FALSE_ALARM_MAX

    lines = [
        "# Chaos Validation Scoreboard — TF3 AIOps pipeline",
        "",
        "> Harness: `scripts/chaos_validate.py` (offline replay, deterministic). "
        f"Acceptance: recall ≥ {RECALL_MIN:.0%} · RCA top-3 ≥ {RCA_ACC_MIN:.0%} "
        f"· false alarm ≤ {FALSE_ALARM_MAX}.",
        "",
        "| Exp | Kịch bản | Detect | MTTD (mô phỏng) | RCA top-3 | Ghi chú |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        det = "✅" if r.detected else ("—" if r.exp.expected_culprit is None else "❌ MISS")
        mttd = f"{r.mttd_s}s" if r.mttd_s is not None else "—"
        rca = {True: "✅", False: "❌", None: "—"}[r.rca_hit]
        note = r.notes[0] if r.notes else (f"{r.incidents} incident(s)" if r.exp.expected_culprit is None else "")
        lines.append(f"| {r.exp.exp_id} | {r.exp.inc_ref}: {r.exp.description[:55]} | {det} | {mttd} | {rca} | {note} |")

    lines += [
        "",
        "## Tổng kết",
        f"- **Recall: {recall:.0%}** ({tp} TP / {fn} FN trên {len(faults)} fault) — ngưỡng {RECALL_MIN:.0%}",
        f"- **RCA top-3 accuracy: {rca_acc:.0%}** ({len(rca_scored)} incident chấm) — ngưỡng {RCA_ACC_MIN:.0%}",
        f"- **False alarms: {false_alarms}** (control runs) — ngưỡng ≤ {FALSE_ALARM_MAX}",
        f"- MTTD p50 mô phỏng: {mttd_p50}s (tick {TICK_S}s — con số thật đo lại trên cluster)",
        f"- Multi-fault tách incident đúng: {'✅' if multi_ok else '❌'}",
        "",
        f"## VERDICT: {'✅ PASS' if passed else '❌ FAIL'}",
    ]
    return "\n".join(lines), passed


async def main() -> int:
    results = [await run_experiment(e) for e in experiments()]
    board, passed = scoreboard(results)
    print(board)
    out = Path(__file__).resolve().parents[1] / "chaos" / "scoreboard.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(board, encoding="utf-8")
    print(f"\nscoreboard -> {out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
