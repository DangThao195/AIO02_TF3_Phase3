"""
graph/nodes/confirmation.py — ConfirmationNode.

Xử lý xác nhận hành động ghi (add to cart) trong CartWorkflow.

Flow:
  1. Kiểm tra state["confirmed"] — nếu True (resume từ checkpoint) → pass-through
  2. Nếu chưa confirmed → generate HMAC token + set pending_action + interrupt
  3. User confirm qua /api/confirm → graph resume với confirmed=True → add to cart

Dùng LangGraph checkpoint/interrupt mechanism.
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING

from src.guardrails.confirmation import request_confirmation

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.confirmation")


class ConfirmationNode:
    """
    Node kiểm tra và yêu cầu xác nhận trước khi thực hiện write action.

    Khi cần confirm:
    - Generate HMAC token
    - Set state["pending_action"] với token + message
    - Route sang "pending" edge → graph dừng tại đây

    Khi đã confirmed (resume):
    - state["confirmed"] = True
    - Route sang "confirmed" edge → tiếp tục add_to_cart
    """

    def __init__(self, action_type: str = "AddItem"):
        self.action_type = action_type

    def _build_action_params(self, state: "ShoppingState") -> dict:
        """Build action params từ state để store trong token."""
        entities = state.get("entities", {})
        return {
            "user_id": state.get("user_id", "anonymous"),
            "product_id": state.get("current_product_id", ""),
            "product_name": entities.get("product_name", "sản phẩm"),
            "quantity": entities.get("quantity", 1),
        }

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        # Nếu đã confirmed (resume từ checkpoint) → pass-through
        if state.get("confirmed", False):
            logger.info("[CONFIRMATION] Already confirmed — pass-through")
            return {
                "node_durations": {"Confirmation": _ms(t0)},
            }

        # Build action data
        action_params = self._build_action_params(state)
        product_name = action_params.get("product_name", "sản phẩm")
        quantity = action_params.get("quantity", 1)

        logger.info(
            "[CONFIRMATION] Requesting confirmation | product=%s | qty=%d | session=%s",
            product_name, quantity, state.get("session_id", "")
        )

        # Generate confirmation token
        try:
            confirmation_result = request_confirmation(
                action=self.action_type,
                user_id=action_params["user_id"],
                params=action_params,
            )

            pending_action = {
                "token": confirmation_result.token,
                "message": (
                    f"🛒 Bạn có chắc muốn thêm **{quantity}x {product_name}** vào giỏ hàng? "
                    f"Nhấn xác nhận để tiếp tục."
                ),
                "action": self.action_type,
                "params": action_params,
            }

            return {
                "pending_action": pending_action,
                "confirmed": False,
                "node_durations": {"Confirmation": _ms(t0)},
            }

        except Exception as e:
            logger.error("[CONFIRMATION] Error generating token: %s", e)
            return {
                "errors": [{"node": "Confirmation", "error": str(e)[:200]}],
                "node_durations": {"Confirmation": _ms(t0)},
            }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000
