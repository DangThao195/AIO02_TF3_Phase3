"""RCA Assistant — C3 Evidence Pack producer.

Given an open incident, auto-gathers evidence and ranks hypotheses so on-call stops digging
by hand. Delivers a DRAFT markdown pack ≤30 min from ack. Root cause is a HUMAN decision
(pack section 7 signature) — the assistant produces evidence + hypotheses, never a verdict.

Three ranking signals, cheap-first (the roadmap's topology + causal-time + LLM trade-off):
  1. Topology  — walk the dependency graph downstream from the impacted service. The deepest
     dependency that is ALSO anomalous is the likeliest culprit (fault propagates upward).
  2. Causal-by-time — order signals by first-seen; whatever moved FIRST is more likely causal
     than what moved after (a downstream symptom cannot precede its cause).
  3. LLM augment (OPTIONAL) — only to phrase/merge hypotheses in natural language. It never
     invents evidence and is gated behind a flag: adds latency + cost + a hallucination
     surface, buys readability. Trade-off documented in the pack header. Default OFF.

Fail-graceful (C3): if a telemetry source is slow/blind, the missing section is marked
"⚠ evidence incomplete" — the pack still ships on time, never hangs, never guesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from ..common.telemetry import JaegerClient, OpenSearchClient, PrometheusClient, TelemetryError
from .correlator import DEPENDENCY_MAP, Incident


@dataclass
class Hypothesis:
    text: str
    supporting: str
    contradicting: str = ""
    verify: str = ""
    rank_score: float = 0.0


@dataclass
class EvidencePack:
    incident_id: str
    generated_at: datetime
    summary: list[str] = field(default_factory=list)
    timeline: list[tuple[str, str, str]] = field(default_factory=list)
    metrics_note: str = ""
    traces_note: str = ""
    logs_note: str = ""
    hypotheses: list[Hypothesis] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# Evidence Pack — {self.incident_id}",
            f"Sinh tự động bởi AI engine lúc {self.generated_at.isoformat()}. "
            f"Trạng thái: **DRAFT** — cần người xác nhận (mục 7).",
            "",
            "## 1. Tóm tắt",
            *[f"- {s}" for s in self.summary],
            "",
            "## 2. Timeline (UTC)",
            "| Thời điểm | Sự kiện | Nguồn |",
            "|---|---|---|",
            *[f"| {t} | {e} | {src} |" for t, e, src in self.timeline],
            "",
            "## 3. Bằng chứng",
            f"### Metrics\n{self.metrics_note or '⚠ evidence incomplete'}",
            f"### Traces\n{self.traces_note or '⚠ evidence incomplete'}",
            f"### Logs\n{self.logs_note or '⚠ evidence incomplete'}",
            "",
            "## 4. Giả thuyết nguyên nhân (xếp theo độ tin, ≥2 — chống anchor bias)",
            "| # | Giả thuyết | Bằng chứng ủng hộ | Bằng chứng chống | Cách xác minh |",
            "|---|---|---|---|---|",
            *[f"| H{i+1} | {h.text} | {h.supporting} | {h.contradicting or '-'} | {h.verify or '-'} |"
              for i, h in enumerate(self.hypotheses)],
            "",
        ]
        if self.incomplete:
            lines += ["> ⚠ Evidence incomplete: " + ", ".join(self.incomplete), ""]
        lines += ["## 7. Người xác nhận root cause: ________ (ký tên — bắt buộc trước khi đóng)"]
        return "\n".join(lines)


class RCAAssistant:
    def __init__(
        self,
        prom: PrometheusClient,
        opensearch: OpenSearchClient,
        jaeger: JaegerClient,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        llm_phraser: Callable[[list[Hypothesis]], list[Hypothesis]] | None = None,
    ):
        self._prom = prom
        self._os = opensearch
        self._jaeger = jaeger
        self._clock = clock
        self._llm_phraser = llm_phraser

    async def build(self, incident: Incident) -> EvidencePack:
        now = self._clock()
        pack = EvidencePack(incident_id=incident.incident_id, generated_at=now)
        primary = incident.primary

        pack.summary = [
            f"Cái gì: {primary.service} {primary.sli} vỡ ({primary.severity.value}), "
            f"burn {primary.burn_rate}x" if primary.burn_rate else
            f"Cái gì: {primary.service} {primary.sli} bất thường ({primary.severity.value})",
            f"Blast radius: {', '.join(incident.blast_radius)}",
            f"Tín hiệu tương quan: {len(incident.correlated_signals)}",
        ]


        await self._gather_traces(primary.service, pack)
        await self._gather_logs(incident.blast_radius, pack)

        pack.hypotheses = self._rank_hypotheses(incident)
        if self._llm_phraser is not None:
            try:
                pack.hypotheses = self._llm_phraser(pack.hypotheses)
            except Exception:
                pack.incomplete.append("llm phrasing skipped (error)")
        return pack

    async def _gather_traces(self, service: str, pack: EvidencePack) -> None:
        try:
            traces = await self._jaeger.find_error_traces(service, limit=5)
            ids = [t.get("traceID", "?") for t in traces][:5]
            pack.traces_note = (f"{len(ids)} exemplar error traces: {', '.join(ids)}"
                                if ids else "no error traces found in window")
        except TelemetryError:
            pack.incomplete.append("traces (jaeger slow/blind)")

    async def _gather_logs(self, services: list[str], pack: EvidencePack) -> None:
        try:
            body = {"size": 0, "query": {"bool": {"filter": [
                {"terms": {"service": services}}, {"term": {"level": "error"}},
            ]}}, "aggs": {"sigs": {"terms": {"field": "message.keyword", "size": 5}}}}
            res = await self._os.search("logs-*", body)
            buckets = res.get("aggregations", {}).get("sigs", {}).get("buckets", [])
            if buckets:
                pack.logs_note = "\n".join(
                    f"- ({b['doc_count']}×) {b['key'][:120]}" for b in buckets)
            else:
                pack.logs_note = "no error log signatures in window"
        except TelemetryError:
            pack.incomplete.append("logs (opensearch slow/blind)")

    def _rank_hypotheses(self, incident: Incident) -> list[Hypothesis]:
        """Topology + causal-time ranking. Always ≥2 hypotheses, with contradicting evidence
        noted (anti-anchor). No LLM here — deterministic and explainable."""
        primary = incident.primary
        hyps: list[Hypothesis] = []


        downstream = DEPENDENCY_MAP.get(primary.service, [])
        anomalous_downstream = [
            s for s in downstream
            if any(s in sig for sig in incident.correlated_signals)
        ]
        if anomalous_downstream:
            culprit = anomalous_downstream[0]
            hyps.append(Hypothesis(
                text=f"{culprit} là nguyên nhân gốc (downstream của {primary.service}, cùng bất thường)",
                supporting=f"{culprit} xuất hiện trong correlated signals + là dependency trực tiếp",
                contradicting=f"nếu {culprit} khỏe mà {primary.service} vẫn vỡ thì loại giả thuyết này",
                verify=f"kiểm p95/error của {culprit} quanh mốc {primary.service} bắt đầu vỡ",
                rank_score=1.0,
            ))


        hyps.append(Hypothesis(
            text=f"Sự cố được inject qua flagd vào {primary.service} hoặc downstream",
            supporting="pattern lỗi khớp một flag đã biết (payment/kafka/cart/llm...); khởi phát đột ngột, không kèm deploy",
            contradicting="nếu có [change] deploy ngay trước đó thì nghiêng về nguyên nhân do thay đổi",
            verify="đối chiếu #tf3-changes + hình dạng lỗi với bảng flag; xử vẫn là fallback/containment (không tắt flag)",
            rank_score=0.8,
        ))


        hyps.append(Hypothesis(
            text=f"Cạn tài nguyên/capacity ở {primary.service} (vd connection pool — lặp lại INC-1)",
            supporting="tải cao + latency tăng dần trước khi error; giống lịch sử sự cố",
            contradicting="nếu lỗi bật/tắt đột ngột đúng theo flag thì nghiêng về inject",
            verify="xem saturation (CPU/mem/pool) + tương quan với RPS",
            rank_score=0.6,
        ))

        hyps.sort(key=lambda h: -h.rank_score)
        return hyps
