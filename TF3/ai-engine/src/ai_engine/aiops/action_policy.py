"""Action policy — ánh xạ incident → đề xuất remediation đúng theo service (C6).

Thay nhánh 'if checkout' cứng trong server.tick() bằng một BẢNG tra cứu theo service impacted.
Mỗi entry là action ĐÚNG cho loại sự cố của service đó, theo AIOPS-INCIDENT-CATALOG + RULES §8:

  - checkout / frontend / kafka  → SCALE (giãn tải — bài học INC-1, xử flood/quá tải)
  - cart                          → None (INC-2: single-replica, KHÔNG auto-restart, mất giỏ)
  - ad / recommendation           → CACHE_FLUSH / degrade (phụ trợ)

Chính sách trả về None nghĩa là "chỉ alert + RCA, KHÔNG tự đề xuất mutate" — an toàn mặc định.
Mọi action trả về vẫn đi qua safety gate + human approve + verify-loop (không tự chạy).
Tách khỏi server.py để unit-test được không cần cluster/Slack.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..common.schemas import ActionType


# Ngưỡng confidence W2-D2 điều phối auto-vs-manual. Mọi route đều KHÔNG tự chạy —
# auto-queue nghĩa là đề xuất được đẩy thẳng vào hàng chờ approve (giảm MTTR),
# không phải bỏ qua approve.
AUTO_QUEUE_THRESHOLD = 0.85
INVESTIGATE_THRESHOLD = 0.60


class RemediationRoute(str, Enum):
    AUTO_QUEUE = "auto-queue"      # >0.85: đề xuất action + đẩy Slack approve ngay
    INVESTIGATE = "investigate"    # 0.6–0.85: on-call điều tra với evidence pack
    ESCALATE = "escalate"          # <0.6: chuyển senior SRE — bằng chứng chưa đủ


def route_for_confidence(confidence: float) -> RemediationRoute:
    """Phân tầng theo confidence của incident/verdict (RCA top-3 >80% là gold standard —
    đừng auto ở vùng mù). Điểm biên: 0.85 → investigate, 0.6 → investigate."""
    if confidence > AUTO_QUEUE_THRESHOLD:
        return RemediationRoute.AUTO_QUEUE
    if confidence >= INVESTIGATE_THRESHOLD:
        return RemediationRoute.INVESTIGATE
    return RemediationRoute.ESCALATE


# ── Risk Assessment (sơ đồ: Dry-run + Blast Radius → Low/Medium/High) ──
# Đây là mắt xích G1 của SELF-HEALING-CHECKLIST: gộp 3 yếu tố thành một mức rủi ro
# quyết định nhánh Execute (tự động) / Human Approval / Reject.

class RiskLevel(str, Enum):
    LOW = "low"        # → Execute tự động (vẫn dry-run + verify + rollback)
    MEDIUM = "medium"  # → Human Approval (Slack card)
    HIGH = "high"      # → Reject (chỉ alert, không mutate)


class RiskDecision(str, Enum):
    EXECUTE = "execute"
    APPROVAL = "approval"
    REJECT = "reject"


# Service tier-1: chạm vào là ảnh hưởng doanh thu trực tiếp → không bao giờ Low.
TIER1_SERVICES = frozenset({"checkout", "payment", "cart", "frontend", "frontend-proxy"})

# Chỉ các action idempotent / dễ đảo mới đủ điều kiện auto-execute ở mức Low.
# SCALE-up và CACHE_FLUSH đảo được sạch; RESTART/BREAKER_FORCE/TOGGLE luôn ≥ Medium.
LOW_RISK_ACTIONS = frozenset({ActionType.SCALE, ActionType.CACHE_FLUSH})

# Blast radius quá rộng thì dù action nhẹ cũng phải có người nhìn.
BLAST_MEDIUM_MIN = 2   # ≥2 service trong vùng ảnh hưởng → tối thiểu Medium
BLAST_HIGH_MIN = 5     # ≥5 service → High (từ chối tự động, cần điều tra rộng)


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    decision: RiskDecision
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"level": self.level.value, "decision": self.decision.value,
                "reasons": list(self.reasons)}


def assess_risk(
    proposal: ActionProposal,
    *,
    blast_radius: list[str],
    dry_run_ok: bool,
    confidence: float = 1.0,
) -> RiskAssessment:
    """Gộp dry-run + blast radius + service tier + loại action + confidence → Low/Med/High.

    Luật (từ nghiêm tới nhẹ, gặp luật nào khớp trước theo mức cao nhất):
      - dry-run FAIL          → HIGH/Reject (action còn không apply thử được thì không chạy)
      - blast ≥ 5 service     → HIGH/Reject (blast quá rộng, cần điều tra)
      - action không idempotent (restart/breaker/toggle) → MEDIUM/Approval
      - service tier-1        → MEDIUM/Approval (doanh thu — luôn cần người ở vòng đầu)
      - blast ≥ 2 service     → MEDIUM/Approval
      - confidence < 0.85     → MEDIUM/Approval (chưa đủ chắc để tự chạy)
      - còn lại (nhẹ, hẹp, idempotent, chắc) → LOW/Execute tự động
    """
    reasons: list[str] = []
    svc = proposal.target.split("/")[-1]
    n_blast = len({*blast_radius})

    if not dry_run_ok:
        return RiskAssessment(RiskLevel.HIGH, RiskDecision.REJECT,
                              ("dry-run thất bại — action không apply được, từ chối",))
    if n_blast >= BLAST_HIGH_MIN:
        return RiskAssessment(RiskLevel.HIGH, RiskDecision.REJECT,
                              (f"blast radius {n_blast} service ≥ {BLAST_HIGH_MIN} — quá rộng để tự xử",))

    if proposal.action not in LOW_RISK_ACTIONS:
        reasons.append(f"action '{proposal.action.value}' không idempotent (khó đảo)")
    if svc in TIER1_SERVICES:
        reasons.append(f"'{svc}' là tier-1 (ảnh hưởng doanh thu trực tiếp)")
    if n_blast >= BLAST_MEDIUM_MIN:
        reasons.append(f"blast radius {n_blast} service ≥ {BLAST_MEDIUM_MIN}")
    if confidence < AUTO_QUEUE_THRESHOLD:
        reasons.append(f"confidence {confidence:.2f} < {AUTO_QUEUE_THRESHOLD} — chưa đủ chắc để tự chạy")

    if reasons:
        return RiskAssessment(RiskLevel.MEDIUM, RiskDecision.APPROVAL, tuple(reasons))
    return RiskAssessment(
        RiskLevel.LOW, RiskDecision.EXECUTE,
        (f"action nhẹ+idempotent ('{proposal.action.value}'), blast {n_blast} service, "
         f"service ngoài tier-1, confidence {confidence:.2f} — đủ an toàn để tự phục hồi",))


@dataclass(frozen=True)
class ActionProposal:
    action: ActionType
    target: str
    parameters: dict
    rationale: str
    risk_note: str
    rollback_plan: str


# Service (đã chuẩn hóa) -> hàm dựng đề xuất. None = không auto-propose (chỉ alert/RCA).
def _scale(dep: str, to: int, frm: int, why: str) -> ActionProposal:
    return ActionProposal(
        action=ActionType.SCALE,
        target=f"deployment/{dep}",
        parameters={"replicas": to, "replicas_from": frm},
        rationale=why,
        risk_note=f"Tăng pod {dep} {frm}→{to}: thêm tài nguyên/kết nối; rollback = scale về {frm}.",
        rollback_plan=f"kubectl scale deployment/{dep} --replicas={frm} -n techx-tf3",
    )


def propose_for(service: str, *, incident_id: str = "") -> ActionProposal | None:
    """Trả về đề xuất action cho service impacted, hoặc None nếu không nên auto-mutate.

    None áp dụng cho: cart (INC-2 SPOF — restart mất giỏ), llm/email/unknown (xử ở tầng khác
    hoặc cần người). Đây là mặc định AN TOÀN: thà chỉ cảnh báo còn hơn đề xuất action vô ích."""
    s = service.lower().split("/")[-1]

    if s == "checkout":
        return _scale("checkout", to=4, frm=2,
                      why="Checkout SLO burn-rate cao (INC-1: cạn DB pool khi tải). Scale để containment.")
    if s in ("frontend", "frontend-proxy"):
        # loadGeneratorFloodHomepage / imageSlowLoad / latency p95 vỡ
        return _scale("frontend", to=4, frm=2,
                      why="Frontend quá tải (flood/latency p95 vỡ). Scale để hấp thụ tải, giữ p95 <1s.")
    if s == "kafka":
        # kafkaQueueProblems: lag spike — scale consumer để tiêu lag
        return _scale("kafka-consumer", to=3, frm=1,
                      why="Kafka lag spike (consumer chậm). Scale consumer để tiêu lag, giảm blast.")

    # cart: INC-2 — single-replica, restart/scale sai cách làm mất giỏ. KHÔNG auto-propose.
    # ad/recommendation/email/llm/unknown: xử ở tầng khác (degrade/guardrail) hoặc cần người.
    return None
