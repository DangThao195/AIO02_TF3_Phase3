"""Local incident matcher — C4.6 offline fallback for the RCA/diagnosis path.

When Bedrock (or any LLM) is unreachable, the engine must STILL produce a defensible
diagnosis + a *safe* proposed action rather than going dark. This is a deterministic,
hard-coded pattern matcher over the known TF3 incident signatures (INC-1/2/3 from
onboarding/INCIDENT_HISTORY.md). Adapted from Capstone03's `match_incident_locally`,
but bound to THIS repo's safety rules:

  - The proposed action is only ever a *suggestion*; it still passes through the C6
    RemediationEngine safety gate + human approval. Nothing here executes.
  - INC-2 (single-replica cart/valkey SPOF) → action MUST be "none". Restarting the
    pod destroys cart state (INC-2 lesson). This is enforced here AND in the safety gate.
  - Output shape matches what the LLM diagnostician returns, so the caller is identical
    whether the LLM answered or we fell back — one code path, no drift.

This is the C4 "local fallback matcher when LLM dies" the checklist flagged as MISSING.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IncidentSignature:
    """One known incident and how to recognise it offline.

    `culprit_markers` match the impacted/culprit service name; `log_markers` match error
    log signatures. Either channel can trigger the match (topology OR log evidence).
    """

    incident_id: str
    culprit_markers: tuple[str, ...]
    log_markers: tuple[str, ...]
    proposed_action: str
    action_command: str
    analysis: str


# Ordered most-specific first. Derived from onboarding/INCIDENT_HISTORY.md.
INCIDENT_PATTERNS: tuple[IncidentSignature, ...] = (
    IncidentSignature(
        incident_id="INC-2",
        culprit_markers=("cart", "valkey"),
        log_markers=("valkey", "oom", "memory limit", "connection refused", "readiness"),
        proposed_action="none",  # HARD: never auto-restart a single-replica stateful pod
        action_command="",
        analysis=(
            "Cart/Valkey single-replica SPOF (INC-2). Đây KHÔNG phải OOM thuần — restart pod "
            "sẽ xoá sạch state giỏ hàng. Không tự động restart. Cảnh báo SRE để thêm replica / "
            "bật persistence trước. Chỉ containment, không mutate."
        ),
    ),
    IncidentSignature(
        incident_id="INC-1",
        culprit_markers=("product-catalog", "postgres", "postgresql", "catalog"),
        log_markers=("pool", "connection slots", "max connections", "too many clients"),
        proposed_action="scale",
        action_command="kubectl -n techx-tf3 scale deployment/product-catalog --replicas=2",
        analysis=(
            "Cạn DB connection pool ở product-catalog (INC-1). Tải cao + latency tăng dần "
            "trước khi error. Scale để giãn tải/pool; theo dõi saturation sau khi scale."
        ),
    ),
    IncidentSignature(
        incident_id="INC-3",
        culprit_markers=("fraud", "fraud-detection"),
        log_markers=("eventstream", "status code 4", "deadline exceeded", "grpc"),
        proposed_action="scale",
        action_command="kubectl -n techx-tf3 scale deployment/fraud-detection --replicas=2",
        analysis=(
            "fraud-detection ↔ flagd EventStream timeout gRPC status 4 (INC-3). Thường là "
            "flagd giải phóng memory. Cache-flush/containment; không tắt flag (RULES §8)."
        ),
    ),
)


@dataclass
class LocalDiagnosis:
    matched_incident: str
    proposed_action: str
    action_command: str
    analysis: str
    source: str = "local-fallback"  # marks the pack so on-call knows the LLM was down
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "matched_incident": self.matched_incident,
            "proposed_action": self.proposed_action,
            "action_command": self.action_command,
            "analysis": self.analysis,
            "source": self.source,
            "citations": self.citations,
        }


def match_incident_locally(
    *,
    culprit_service: str,
    log_templates: list[dict] | None = None,
    trace_id: str | None = None,
) -> LocalDiagnosis:
    """Deterministic offline diagnosis. `log_templates` items look like
    {"template": "...", "count": N} (Drain3 output) or {"message": "..."}.

    Returns a LocalDiagnosis whose action is always safe-by-construction (INC-2 → none).
    Never raises; unknown patterns get a conservative "none" verdict + raw evidence.
    """
    culprit = (culprit_service or "").lower()
    templates = log_templates or []
    log_text = " ".join(
        (t.get("template") or t.get("message") or "").lower() for t in templates
    )

    for sig in INCIDENT_PATTERNS:
        hit_culprit = any(m in culprit for m in sig.culprit_markers)
        hit_log = any(m in log_text for m in sig.log_markers)
        if hit_culprit or hit_log:
            citations = []
            if trace_id:
                citations.append(f"Jaeger trace {trace_id} bắt đầu từ {culprit_service}")
            if hit_log:
                matched = next((m for m in sig.log_markers if m in log_text), "")
                citations.append(f"Log signature khớp mẫu '{matched}' (Drain3)")
            citations.append(f"Đối chiếu lịch sử: khớp {sig.incident_id}")
            return LocalDiagnosis(
                matched_incident=sig.incident_id,
                proposed_action=sig.proposed_action,
                action_command=sig.action_command,
                analysis=sig.analysis,
                citations=citations,
            )

    return LocalDiagnosis(
        matched_incident="None",
        proposed_action="none",
        action_command="",
        analysis=(
            f"LLM không kết nối được và không khớp sự cố lịch sử nào. Bất thường trên "
            f"'{culprit_service}'. Giữ ở mức quan sát/containment, chờ người xác minh — "
            f"không tự động mutate khi thiếu bằng chứng."
        ),
        citations=[f"trace {trace_id}"] if trace_id else [],
    )
