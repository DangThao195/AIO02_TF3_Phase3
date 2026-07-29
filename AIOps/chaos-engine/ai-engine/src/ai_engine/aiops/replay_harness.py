"""Replay harness — MANDATE #15: "cửa replay nhận kịch bản từ ngoài".

Mandate #15 đòi detector đáng tin phải:
  - Bắt đúng sự cố thật (precision/recall/lead-time trên bộ CÓ NHÃN).
  - KHÔNG bị masking (spike nhiễu không che một sự cố nhẹ khác).
  - KHÔNG kêu oan khi service chỉ đang BẬN (tải cao nhưng healthy).
  - Chứng minh bằng bộ kịch bản ẩn do BTC bơm vào lúc chấm → cần một CỬA nhận input
    NGOÀI, không phải test nội bộ hard-code.

Module này là cửa đó. Nó nhận một **scenario file JSON** (BTC/mentor soạn, không đụng code),
replay qua `Correlator` + `RCAAssistant` THẬT, rồi chấm:
  - detected / MTTD cho mỗi sự cố có nhãn,
  - precision = kêu-đúng / tổng-kêu, recall = bắt-được / tổng-sự-cố-thật,
  - masking check: sự cố nhẹ có bị spike nhiễu nuốt không,
  - busy check: cửa sổ tải-cao-healthy có bị kêu oan không,
  - incident summary (severity + service) cho từng lần kêu.

Logic chấm MỞ (đọc được) — mentor soi được cách ta chấm, đúng yêu cầu #15.

Định dạng scenario (JSON):
{
  "name": "hidden-set-01",
  "tick_seconds": 30,
  "windows": [
    {
      "tick": 1,
      "label": "real|masking-noise|masking-real|busy-healthy|normal",
      "burns":  [{"service":"checkout","burn_rate":14.4,"severity":"critical"}],
      "anomalies": [{"service":"product-catalog","sli":"latency_p95","z":8,"confidence":0.85,"note":"pool wait"}]
    }
  ],
  "ground_truth": [
    {"service":"product-catalog","starts_tick":1,"kind":"real"}
  ]
}

Chạy:  python scripts/replay.py <scenario.json>
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common.schemas import Severity, SourceLayer
from .correlator import Correlator, Incident
from .detector_anomaly import AnomalySignal
from .detector_burnrate import BurnSignal


# ── stubs telemetry (replay chấm detect+correlate, RCA optional) ──
class _StubJaeger:
    async def find_error_traces(self, service, limit=5):
        return []


class _StubOS:
    async def search(self, index, body):
        return {}


def _mk_burn(d: dict) -> BurnSignal:
    sev = Severity(d.get("severity", "critical"))
    return BurnSignal(
        service=d["service"], sli=d.get("sli", "availability"), severity=sev,
        burn_rate=float(d.get("burn_rate", 14.4)), error_ratio=float(d.get("error_ratio", 0.05)),
        target=float(d.get("target", 0.99)),
        long_window=d.get("long_window", "1h"), short_window=d.get("short_window", "5m"),
    )


def _mk_anom(d: dict) -> AnomalySignal:
    sev = Severity(d.get("severity", "warning"))
    return AnomalySignal(
        service=d["service"], sli=d.get("sli", "anomaly"), severity=sev,
        current_value=float(d.get("current", 9.0)), baseline_median=float(d.get("median", 1.0)),
        z_score=float(d.get("z", 8.0)), confidence=float(d.get("confidence", 0.85)),
        source_layer=SourceLayer.ML_ANOMALY, note=f"{d['service']} {d.get('note', '')}",
    )


@dataclass
class IncidentSummary:
    """Tóm tắt sự cố tự sinh khi detector kêu (yêu cầu #15 §5)."""

    tick: int
    at_seconds: int
    service: str
    severity: str
    signals: int
    blast_radius: list[str]

    def to_line(self) -> str:
        return (f"[+{self.at_seconds}s] INCIDENT {self.service} ({self.severity}) — "
                f"{self.signals} tín hiệu, blast: {', '.join(self.blast_radius) or '—'}")


@dataclass
class ReplayResult:
    name: str
    fired: list[IncidentSummary] = field(default_factory=list)
    # sự cố thật (ground truth) -> tick phát hiện (None = miss)
    detection: dict[str, int | None] = field(default_factory=dict)
    mttd_s: dict[str, int] = field(default_factory=dict)
    false_fires: list[str] = field(default_factory=list)   # kêu ở service KHÔNG trong ground truth
    masking_ok: bool | None = None
    busy_ok: bool | None = None

    @property
    def recall(self) -> float:
        gt = self.detection
        if not gt:
            return 1.0
        caught = sum(1 for v in gt.values() if v is not None)
        return round(caught / len(gt), 3)

    @property
    def precision(self) -> float:
        total = len(self.fired)
        if total == 0:
            return 1.0
        correct = total - len(self.false_fires)
        return round(correct / total, 3)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "recall": self.recall,
            "precision": self.precision,
            "mttd_seconds": self.mttd_s,
            "false_fires": self.false_fires,
            "masking_ok": self.masking_ok,
            "busy_ok": self.busy_ok,
            "incidents": [s.to_line() for s in self.fired],
        }


async def replay(scenario: dict[str, Any], rca=None) -> ReplayResult:
    """Replay một scenario qua pipeline thật. `rca` optional (nếu muốn chấm cả RCA)."""
    name = scenario.get("name", "unnamed")
    tick_s = int(scenario.get("tick_seconds", 30))
    windows = scenario.get("windows", [])
    ground_truth = {gt["service"]: gt for gt in scenario.get("ground_truth", [])}

    t = [1000.0]
    correlator = Correlator(clock=lambda: t[0])
    res = ReplayResult(name=name)
    # detection CHỈ theo dõi sự cố cần-bắt (real/masking-real). busy-healthy (không được kêu)
    # và masking-noise (nhiễu hợp lệ, không phải sự cố) KHÔNG vào recall.
    res.detection = {svc: None for svc, gt in ground_truth.items()
                     if gt.get("kind") not in ("busy-healthy", "masking-noise")}

    # busy-healthy: KHÔNG được kêu. masking-real: sự cố nhẹ PHẢI bắt. noise-expected: spike nhiễu
    # biết trước sẽ kêu (là anomaly hợp lệ) → không tính false-fire (BUG#3).
    busy_services = {gt["service"] for gt in ground_truth.values() if gt.get("kind") == "busy-healthy"}
    masking_real = {gt["service"] for gt in ground_truth.values() if gt.get("kind") == "masking-real"}
    noise_expected = {gt["service"] for gt in ground_truth.values() if gt.get("kind") == "masking-noise"}
    real_services = set(ground_truth) - busy_services

    max_tick = max((w["tick"] for w in windows), default=0)
    windows_by_tick: dict[int, dict] = {w["tick"]: w for w in windows}

    for tick in range(1, max_tick + 1):
        t[0] = 1000.0 + tick * tick_s
        w = windows_by_tick.get(tick, {})
        burns = [_mk_burn(b) for b in w.get("burns", [])]
        # Tôn trọng đúng cổng lọc của detector thật (C2): anomaly confidence < 0.7 bị chặn
        # TRƯỚC khi tới correlator. Đây là cơ chế "không kêu oan khi bận" — tải cao chỉ đẩy
        # z lên nhẹ (confidence thấp) nên không rời khỏi engine. Replay phải mô phỏng đúng.
        anoms = [_mk_anom(a) for a in w.get("anomalies", []) if float(a.get("confidence", 0.85)) >= 0.7]
        incidents = correlator.correlate(burns, anoms)

        for inc in incidents:
            summary = IncidentSummary(
                tick=tick, at_seconds=tick * tick_s, service=inc.primary.service,
                severity=inc.primary.severity.value,
                signals=len(inc.correlated_signals) + 1, blast_radius=inc.blast_radius,
            )
            res.fired.append(summary)

            # gán lần kêu này vào ground truth: khớp service primary HOẶC service trong cluster
            matched = _match_incident_to_gt(inc, ground_truth)
            if matched in noise_expected:
                # spike nhiễu ĐƯỢC BÁO TRƯỚC (masking-noise) — anomaly hợp lệ, không tính vào
                # detection lẫn false-fire (BUG#3: tính false sẽ phạt oan precision).
                continue
            if matched is not None and matched in res.detection:
                if res.detection.get(matched) is None:
                    starts = ground_truth[matched].get("starts_tick", tick)
                    res.detection[matched] = tick
                    # MTTD ≥ 1 chu kỳ: detect ở/sau starts → (tick-starts+1); detect TRƯỚC starts
                    # (anomaly cảnh báo sớm) → bắt ngay lúc sự cố mở = 1 tick, KHÔNG cho 0
                    # (0 nghĩa "phát hiện trước cả khi sự cố tồn tại" — số vô lý, BUG#2).
                    res.mttd_s[matched] = max(1, tick - starts + 1) * tick_s
            elif inc.primary.service not in busy_services:
                res.false_fires.append(f"tick{tick}:{inc.primary.service}")

    # masking check: mọi sự cố nhẹ (masking-real) PHẢI được bắt dù có spike nhiễu cùng lúc
    if masking_real:
        res.masking_ok = all(res.detection.get(s) is not None for s in masking_real)

    # busy check: KHÔNG service busy-healthy nào bị kêu
    if busy_services:
        fired_services = {s.service for s in res.fired}
        res.busy_ok = not (busy_services & fired_services)

    return res


def _match_incident_to_gt(inc: Incident, ground_truth: dict) -> str | None:
    """Khớp một incident với sự cố thật: primary service hoặc bất kỳ service nào trong
    correlated signals / blast radius trùng ground truth."""
    if inc.primary.service in ground_truth:
        return inc.primary.service
    for svc in ground_truth:
        if any(svc in s for s in inc.correlated_signals) or svc in inc.blast_radius:
            return svc
    return None


def render_report(results: list[ReplayResult], *, baseline_mttd_s: int | None = None) -> str:
    """Báo cáo markdown — precision/recall/MTTD + masking/busy verdict cho mentor soi."""
    lines = [
        "# Replay Report — MANDATE #15 (detect đáng tin)",
        "",
        "> Chạy bộ kịch bản (có nhãn) qua pipeline thật. Logic chấm mở: recall = bắt/tổng-thật,",
        "> precision = kêu-đúng/tổng-kêu, MTTD = từ lúc sự cố bắt đầu tới lúc kêu.",
        "",
        "| Scenario | Recall | Precision | MTTD | Masking | Busy-healthy | False fires |",
        "|---|---|---|---|---|---|---|",
    ]
    all_mttd: list[int] = []
    for r in results:
        mttd_vals = list(r.mttd_s.values())
        all_mttd += mttd_vals
        mttd_str = f"{min(mttd_vals)}–{max(mttd_vals)}s" if mttd_vals else "—"
        mask = {True: "✅ bắt", False: "❌ bị che", None: "—"}[r.masking_ok]
        busy = {True: "✅ im", False: "❌ kêu oan", None: "—"}[r.busy_ok]
        lines.append(f"| {r.name} | {r.recall:.0%} | {r.precision:.0%} | {mttd_str} | "
                     f"{mask} | {busy} | {len(r.false_fires)} |")

    lines += ["", "## MTTD before/after (§15 §6)"]
    if all_mttd:
        avg_after = round(sum(all_mttd) / len(all_mttd))
        lines.append(f"- **MTTD after (detector tự động): p50 ≈ {sorted(all_mttd)[len(all_mttd)//2]}s, "
                     f"trung bình {avg_after}s**")
        if baseline_mttd_s:
            improve = round((1 - avg_after / baseline_mttd_s) * 100)
            lines.append(f"- MTTD before (soi Grafana thủ công, mốc mentor cấp): {baseline_mttd_s}s "
                         f"→ **giảm ~{improve}%**")
        else:
            lines.append("- MTTD before: _điền mốc thủ công do mentor cấp để tính % cải thiện_")
    else:
        lines.append("- (chưa có sự cố nào được bắt để đo MTTD)")

    lines += ["", "## Incident summaries tự sinh (§15 §5)"]
    for r in results:
        if r.fired:
            lines.append(f"### {r.name}")
            lines += [f"- {s.to_line()}" for s in r.fired]

    # verdict theo tiêu chí ẩn #15
    real_ok = all(r.recall >= 0.99 for r in results if r.detection)
    mask_ok = all(r.masking_ok is not False for r in results)
    busy_ok = all(r.busy_ok is not False for r in results)
    passed = real_ok and mask_ok and busy_ok
    lines += [
        "",
        "## VERDICT (tiêu chí ẩn #15)",
        f"- Sự cố thật → bắt: {'✅' if real_ok else '❌'}",
        f"- Masking → vẫn bắt sự cố nhẹ: {'✅' if mask_ok else '❌'}",
        f"- Tải-cao-healthy → không kêu oan: {'✅' if busy_ok else '❌'}",
        f"- **{'✅ PASS' if passed else '❌ FAIL'}**",
    ]
    return "\n".join(lines)


def load_scenarios(path: str | Path) -> list[dict]:
    """Nạp scenario từ file JSON (1 scenario) hoặc list scenario. Đây là 'input ngoài'."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]
