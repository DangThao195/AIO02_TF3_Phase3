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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..common.telemetry import JaegerClient, OpenSearchClient, PrometheusClient, TelemetryError
from .correlator import DEPENDENCY_MAP, Incident
from .kb_retriever import retrieve_scored
from .local_matcher import match_incident_locally
from .rca_guardrail import RCAVerdict, validate_llm_verdict

log = logging.getLogger("ai_engine.rca_assistant")

# Repo-relative: .../aiops/rca_assistant.py -> parents[4] == TF3/
_INCIDENTS_ROOT = Path(__file__).resolve().parents[4] / "incidents"

# W2-D2 fusion: cấu trúc đồ thị nói "AI CÓ THỂ là nguyên nhân", thời gian nói "AI ĐỘNG TRƯỚC".
W_STRUCTURAL, W_TEMPORAL = 0.6, 0.4

# W2-D3 conditional skipping: graph+temporal đã đủ chắc thì KHÔNG gọi LLM —
# cost 0, latency 0, hallucination surface 0. Giảm ~90% LLM call ở các sự cố quen.
SKIP_LLM_SCORE = 0.9

# Map INC lịch sử (local_matcher) -> incident_class chuẩn (rca_guardrail.RCA_CLASSES)
_INC_CLASS = {
    "INC-1": "connection_pool_exhaustion",
    "INC-2": "state_loss_spof",
    "INC-3": "deploy_readiness_gap",
}


def score_candidates(
    primary_service: str,
    candidates: list[str],
    first_seen: dict[str, float],
) -> list[tuple[str, float, str]]:
    """score = 0.6×structural + 0.4×temporal. Structural: direct anomalous downstream = 1.0.
    Temporal: sớm nhất trong nhóm = 1.0, tuyến tính xuống; candidate chỉ động SAU primary = 0.0
    (hệ quả không thể đi trước nguyên nhân — chống retry-storm rank nạn nhân làm thủ phạm).
    Thiếu mốc first-seen → 0.5 trung tính (không thưởng không phạt).
    Trả [(service, score, timing_note)] giảm dần theo score."""
    p_ts = first_seen.get(primary_service)
    known = sorted(
        ((c, first_seen[c]) for c in candidates if c in first_seen), key=lambda x: x[1])
    order = {c: i for i, (c, _) in enumerate(known)}
    n = len(known)

    out: list[tuple[str, float, str]] = []
    for c in candidates:
        structural = 1.0
        ts = first_seen.get(c)
        if ts is None or p_ts is None:
            temporal, note = 0.5, "chưa có mốc first-seen — timing trung tính"
        elif ts > p_ts:
            temporal, note = 0.0, (
                f"{c} chỉ động SAU {primary_service} — nghiêng về victim (retry storm), "
                f"không phải nguyên nhân")
        else:
            temporal = 1.0 - (order[c] / (n - 1)) if n > 1 else 1.0
            note = f"{c} động trước/cùng lúc {primary_service} (thứ tự nhân quả hợp lệ)"
        out.append((c, round(W_STRUCTURAL * structural + W_TEMPORAL * temporal, 2), note))

    out.sort(key=lambda x: -x[1])
    return out


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
    # C4.6 — deterministic offline diagnosis (matched incident + safe suggested action),
    # always populated so a pack is actionable even when the LLM diagnostician is down.
    local_diagnosis: dict = field(default_factory=dict)
    # RAG grounding: [(relevance_score, playbook_chunk)] từ Bedrock KB, đã qua heuristic W2-D2.
    kb_context: list[tuple[float, str]] = field(default_factory=list)
    # Verdict LLM ĐÃ QUA guardrail (rca_guardrail) — method="graph-fallback" nếu bị loại.
    llm_verdict: dict = field(default_factory=dict)

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
        if self.local_diagnosis:
            ld = self.local_diagnosis
            lines += [
                "## 5. Chẩn đoán offline (fallback khi LLM chết — C4.6)",
                f"- Khớp sự cố: **{ld.get('matched_incident', 'None')}** "
                f"(nguồn: {ld.get('source', 'local-fallback')})",
                f"- Hành động đề xuất (an toàn, vẫn cần approve C6): **{ld.get('proposed_action', 'none')}**"
                + (f" — `{ld['action_command']}`" if ld.get('action_command') else ""),
                f"- Phân tích: {ld.get('analysis', '')}",
                *([f"- Dẫn chứng: {'; '.join(ld['citations'])}"] if ld.get("citations") else []),
                "",
            ]
        if self.llm_verdict:
            v = self.llm_verdict
            lines += [
                "### Verdict LLM (đã qua guardrail — rca_guardrail)",
                f"- Root cause: **{v.get('root_cause_service')}** · class `{v.get('incident_class')}` "
                f"· confidence {v.get('confidence')} · method `{v.get('method')}`",
                *[f"- Hành động: {a}" for a in v.get("actions", [])],
                *[f"- Dẫn chứng: {c}" for c in v.get("citations", [])],
                *([f"- ⚠ Guardrail loại verdict LLM: {'; '.join(v['violations'])}"]
                  if v.get("violations") else []),
                "",
            ]
        if self.kb_context:
            lines += [
                "## 6. Tri thức lịch sử (Bedrock KB — RAG grounding)",
                *[f"- (điểm {s:.1f}) {t[:200]}" for s, t in self.kb_context],
                "",
            ]
        if self.incomplete:
            lines += ["> ⚠ Evidence incomplete: " + ", ".join(self.incomplete), ""]
        lines += ["## 7. Người xác nhận root cause: ________ (ký tên — bắt buộc trước khi đóng)"]
        return "\n".join(lines)

    def write(self, root: str | Path | None = None) -> Path:
        """C3 — persist the DRAFT pack to incidents/<id>/evidence-pack.md so it survives the
        engine dying (the file, not the process, is the deliverable) and goes to git next to
        that incident's actions.jsonl. Returns the path written."""
        base = Path(root) if root else _INCIDENTS_ROOT
        safe = "".join(c for c in self.incident_id if c.isalnum() or c in "-_")
        path = base / safe / "evidence-pack.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")
        log.info("evidence pack written: %s", path)
        return path


class RCAAssistant:
    def __init__(
        self,
        prom: PrometheusClient,
        opensearch: OpenSearchClient,
        jaeger: JaegerClient,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        llm_phraser: Callable[[list[Hypothesis]], list[Hypothesis]] | None = None,
        kb_retriever=None,
        llm_diagnoser: Callable[[dict], dict] | None = None,
    ):
        self._prom = prom
        self._os = opensearch
        self._jaeger = jaeger
        self._clock = clock
        self._llm_phraser = llm_phraser
        # Optional RAG grounding: bất kỳ object nào có async .retrieve(query, top_k).
        self._kb = kb_retriever
        # Optional LLM diagnostician: nhận context dict, trả raw dict — LUÔN đi qua
        # rca_guardrail trước khi vào pack (hallucination không có đường tắt).
        self._llm_diagnoser = llm_diagnoser

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

        # C4.6 — deterministic offline diagnosis. Uses the culprit (deepest anomalous
        # downstream, else primary) + any gathered log signatures. Always safe (INC-2→none).
        services_in_incident = []
        if incident.primary:
            services_in_incident.append(incident.primary.service)
        # Extract services from correlated signals
        for sig in incident.correlated_signals:
            parts = sig.split()
            if parts:
                if parts[0] == "[anomaly]":
                    for p in parts:
                        cleaned_p = p.strip("[],:()")
                        if cleaned_p in DEPENDENCY_MAP or cleaned_p == "valkey-cart":
                            services_in_incident.append(cleaned_p)
                else:
                    services_in_incident.append(parts[0])

        services_in_incident = list(set(services_in_incident))

        # Find leaf-most culprit using dependency graph traversal
        culprit = primary.service
        if services_in_incident:
            curr = services_in_incident[0]
            visited = set()
            while curr not in visited:
                visited.add(curr)
                deps = DEPENDENCY_MAP.get(curr, [])
                next_node = next((d for d in deps if d in services_in_incident and d not in visited), None)
                if next_node is None:
                    break
                curr = next_node
            culprit = curr

        log_templates = [{"message": line.lstrip("- ")} for line in pack.logs_note.splitlines()
                         if line.strip() and not line.startswith("no ")]
        pack.local_diagnosis = match_incident_locally(
            culprit_service=culprit, log_templates=log_templates,
        ).to_dict()

        cluster = set(services_in_incident) | {primary.service, *incident.blast_radius}

        # RAG grounding (W2-D2): top-K playbook lịch sử từ Bedrock KB, chấm heuristic,
        # ngưỡng 0.2. KB chậm/chết → incomplete, pack vẫn ship (C3).
        if self._kb is not None:
            try:
                pack.kb_context = await retrieve_scored(
                    self._kb,
                    query=f"{primary.service} {primary.sli} {primary.severity.value} "
                          f"{' '.join(incident.correlated_signals[:3])}",
                    cluster_services=cluster,
                    severity=primary.severity.value,
                )
            except TelemetryError:
                pack.incomplete.append("kb (bedrock slow/blind)")

        # LLM diagnostician (optional) — raw output KHÔNG BAO GIỜ vào pack trực tiếp:
        # guardrail validate (root ∈ cluster, class ∈ enum, confidence [0,1], actions,
        # citations); vi phạm → fallback top-1 graph candidate (chaos failure-mode #4).
        if self._llm_diagnoser is not None:
            top_score = pack.hypotheses[0].rank_score if pack.hypotheses else 0.0
            if top_score >= SKIP_LLM_SCORE:
                # Conditional skipping (W2-D3): verdict deterministic từ graph + lịch sử,
                # không tốn token, không có bề mặt hallucinate.
                ld = pack.local_diagnosis
                pack.llm_verdict = RCAVerdict(
                    root_cause_service=culprit,
                    incident_class=_INC_CLASS.get(ld.get("matched_incident", ""), "other"),
                    confidence=round(top_score, 2),
                    actions=(ld.get("proposed_action") or "manual investigation",),
                    citations=(
                        f"graph+temporal score {top_score} ≥ {SKIP_LLM_SCORE} — skip LLM",
                        *ld.get("citations", []),
                    ),
                    method="graph-high-confidence",
                ).to_dict()
            else:
                try:
                    raw = self._llm_diagnoser({
                        "primary": {"service": primary.service, "sli": primary.sli,
                                    "severity": primary.severity.value},
                        "cluster_services": sorted(cluster),
                        "hypotheses": [h.text for h in pack.hypotheses],
                        "kb_context": [t for _, t in pack.kb_context],
                    })
                except Exception:
                    raw = None
                pack.llm_verdict = validate_llm_verdict(
                    raw, cluster_services=cluster, fallback_candidate=culprit,
                ).to_dict()

        if self._llm_phraser is not None:
            try:
                pack.hypotheses = self._llm_phraser(pack.hypotheses)
            except Exception:
                pack.incomplete.append("llm phrasing skipped (error) — dùng local_diagnosis")
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
            scored = score_candidates(
                primary.service, anomalous_downstream, incident.first_seen)
            culprit, score, timing_note = scored[0]
            hyps.append(Hypothesis(
                text=f"{culprit} là nguyên nhân gốc (downstream của {primary.service}, cùng bất thường)",
                supporting=f"{culprit} xuất hiện trong correlated signals + là dependency trực tiếp; {timing_note}",
                contradicting=(
                    f"nếu {culprit} khỏe mà {primary.service} vẫn vỡ thì loại giả thuyết này"
                    + ("" if score >= 0.8 else
                       f"; timing yếu (score {score}) — cân nhắc {culprit} là victim của retry storm")
                ),
                verify=f"kiểm p95/error của {culprit} quanh mốc {primary.service} bắt đầu vỡ",
                rank_score=score,
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
