"""RCA LLM guardrail — validate mọi verdict LLM trước khi cho vào Evidence Pack.

Bài học W3-D2 (chaos failure-mode #4): LLM hallucination trả về root cause "hợp lý"
với confidence 0.9+ là cách đốt thời gian điều tra nhanh nhất. Chống bằng validate
CỨNG, fail → fallback deterministic (top-1 graph candidate), không bao giờ raise:

  1. root_cause_service PHẢI thuộc cluster services của incident (không bịa service).
  2. incident_class PHẢI thuộc enum cố định (không bịa loại sự cố mới).
  3. confidence PHẢI ∈ [0, 1].
  4. actions PHẢI khác rỗng (verdict không kèm việc-cần-làm là verdict vô dụng).
  5. citations PHẢI khác rỗng — grounded confidence: mỗi kết luận phải trỏ được vào
     bằng chứng (metric anomaly / log signature / topology). Citation rỗng = reject.

Mọi verdict (kể cả fallback) mang `method` để audit trail biết đường ra kết luận.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Enum loại sự cố: base từ ghi chú W2-D2 + các lớp TF3 từ INCIDENT_HISTORY.md INC-1..8.
RCA_CLASSES: frozenset[str] = frozenset({
    "connection_pool_exhaustion",   # INC-1
    "state_loss_spof",              # INC-2
    "deploy_readiness_gap",         # INC-3
    "rate_limit",                   # INC-4 (Bedrock 429)
    "consumer_lag",                 # INC-5 (Kafka)
    "memory_leak",                  # INC-6
    "circuit_breaker_stuck",        # INC-7
    "cold_start",                   # INC-8
    "slow_query",
    "rebalance_storm",
    "deadlock",
    "network_partition",
    "bad_deploy",
    "config_push",
    "tls_expiry",
    "ddos",
    "other",
})


@dataclass(frozen=True)
class RCAVerdict:
    root_cause_service: str
    incident_class: str
    confidence: float
    actions: tuple[str, ...]
    citations: tuple[str, ...]
    method: str  # "llm" | "graph-fallback"
    violations: tuple[str, ...] = field(default=())  # lý do fallback (rỗng nếu LLM pass)

    def to_dict(self) -> dict:
        return {
            "root_cause_service": self.root_cause_service,
            "incident_class": self.incident_class,
            "confidence": self.confidence,
            "actions": list(self.actions),
            "citations": list(self.citations),
            "method": self.method,
            "violations": list(self.violations),
        }


def _fallback(candidate: str, violations: list[str]) -> RCAVerdict:
    """Top-1 graph candidate, class 'other', confidence thấp — luôn an toàn, luôn có."""
    return RCAVerdict(
        root_cause_service=candidate,
        incident_class="other",
        confidence=0.5,
        actions=("manual investigation — LLM verdict bị guardrail loại",),
        citations=(f"graph top-1 candidate: {candidate}",),
        method="graph-fallback",
        violations=tuple(violations),
    )


def validate_llm_verdict(
    raw: dict | None,
    *,
    cluster_services: set[str],
    fallback_candidate: str,
) -> RCAVerdict:
    """Validate raw LLM output. BẤT KỲ vi phạm nào → fallback (không sửa hộ LLM,
    không raise). `raw=None` (LLM chết/timeout) cũng đi đường fallback."""
    if not isinstance(raw, dict):
        return _fallback(fallback_candidate, ["llm unavailable or non-dict output"])

    violations: list[str] = []

    root = str(raw.get("root_cause_service", "") or "")
    if root not in cluster_services:
        violations.append(f"root '{root}' not in cluster {sorted(cluster_services)}")

    klass = str(raw.get("incident_class", "") or "")
    if klass not in RCA_CLASSES:
        violations.append(f"class '{klass}' not in RCA_CLASSES enum")

    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = -1.0
    if not (0.0 <= confidence <= 1.0):
        violations.append(f"confidence {raw.get('confidence')!r} outside [0,1]")

    actions = [str(a) for a in (raw.get("actions") or []) if str(a).strip()]
    if not actions:
        violations.append("actions empty")

    citations = [str(c) for c in (raw.get("citations") or []) if str(c).strip()]
    if not citations:
        violations.append("citations empty — grounded confidence yêu cầu evidence linkage")

    if violations:
        return _fallback(fallback_candidate, violations)

    return RCAVerdict(
        root_cause_service=root,
        incident_class=klass,
        confidence=round(confidence, 2),
        actions=tuple(actions),
        citations=tuple(citations),
        method="llm",
    )
