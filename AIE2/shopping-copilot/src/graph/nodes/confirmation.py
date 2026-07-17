"""
graph/nodes/confirmation.py — ConfirmationNode.

Xử lý xác nhận hành động ghi (add to cart) trong CartWorkflow.

Dùng interrupt() để suspend graph khi cần xác nhận.

Flow:
  1. Generate HMAC token + pending_action
  2. interrupt({"pending_action": pending_action}) → graph suspend
     - pending_action được gửi về client qua __interrupt__ trong result
     - API đọc và trả về Frontend → user thấy nút Xác nhận
  3. User bấm Xác nhận → /api/confirm gọi Command(resume={"confirmed": True})
     - Node re-executes từ đầu
     - interrupt() trả về resume data (confirmed=True) thay vì raise
     - Node trả về {"confirmed": True}
     - Conditional edge route_confirmation → "confirmed" → add_to_cart
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING

from langgraph.types import interrupt

from src.guardrails.confirmation import request_confirmation

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.confirmation")


class ConfirmationNode:
    """
    Node kiểm tra và yêu cầu xác nhận trước khi thực hiện write action.

    Dùng interrupt() để suspend graph — checkpoint lưu state tại thời điểm
    interrupt. API đọc pending_action từ __interrupt__ trong result.

    Khi resume qua /api/confirm với Command(resume={"confirmed": True}):
      - Node re-executes từ đầu
      - interrupt() trả về resume data (confirmed=True) thay vì raise
      - Node trả về {"confirmed": True}
      - Conditional edge route_confirmation thấy confirmed=True → "confirmed"
    """

    def __init__(self, action_type: str = "AddItem"):
        self.action_type = action_type

    def _build_action_params(self, state: "ShoppingState") -> dict:
        entities = state.get("entities", {})
        return {
            "user_id": state.get("user_id", "anonymous"),
            "product_id": state.get("current_product_id", ""),
            "product_name": entities.get("product_name", "sản phẩm"),
            "quantity": entities.get("quantity", 1),
        }

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        action_params = self._build_action_params(state)
        product_name = action_params.get("product_name", "sản phẩm")
        quantity = action_params.get("quantity", 1)

        logger.info(
            "[CONFIRMATION] Requesting confirmation | product=%s | qty=%d | session=%s",
            product_name, quantity, state.get("session_id", "")
        )

        try:
            confirmation_result = request_confirmation(
                action=self.action_type,
                user_id=action_params["user_id"],
                action_params=action_params,
            )

            pending_action = {
                "token": confirmation_result.confirmation_token,
                "message": (
                    f"🛒 Bạn có chắc muốn thêm **{quantity}x {product_name}** vào giỏ hàng? "
                    f"Nhấn xác nhận để tiếp tục."
                ),
                "action": self.action_type,
                "params": action_params,
            }

        except Exception as e:
            logger.error("[CONFIRMATION] Error generating token: %s", e)
            return {
                "errors": [{"node": "Confirmation", "error": str(e)[:200]}],
                "node_durations": {"Confirmation": _ms(t0)},
            }

        # Capture tool errors từ subgraph state để debugger hiển thị
        tool_results = state.get("tool_results", {})
        tool_errors = {}
        for key, val in tool_results.items():
            tool_name = key.split(":")[0]
            if val.get("error"):
                tool_errors[tool_name] = val["error"]
            elif isinstance(val.get("result"), str):
                r = val["result"].lower()[:30]
                if "lỗi" in r or "error" in r or "unavail" in r or "grc" in r:
                    tool_errors[tool_name] = val["result"][:200]

        # On first call: interrupt() raises GraphInterrupt → graph suspends
        # On resume via Command(resume=...): interrupt() returns resume_data
        resume_data = interrupt({
            "pending_action": pending_action,
            "tool_errors": tool_errors,
        })

        logger.info(
            "[CONFIRMATION] Confirmed via resume | resume_data=%s",
            str(resume_data)[:100]
        )

        return {
            "confirmed": True,
            "node_durations": {"Confirmation": _ms(t0)},
        }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000
