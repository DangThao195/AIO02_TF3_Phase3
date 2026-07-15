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
