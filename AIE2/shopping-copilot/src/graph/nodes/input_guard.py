"""
graph/nodes/input_guard.py — InputGuard node.

Ánh xạ 3 lớp guardrail đầu vào vào 1 node LangGraph:
  L1: Rate Limiter      ← rate_limiter.check_rate_limit()
  L2a: Regex Filter     ← check_input()
  L2b: Bedrock Guard    ← check_input_bedrock()

Nếu vi phạm → ghi vào guardrail_violations + set final_answer → graph route về END.
Nếu pass → graph tiếp tục sang intent_classifier.
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING

from src.guardrails.rate_limiter import rate_limiter
from src.guardrails.input_filter import check_input, check_input_bedrock

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.input_guard")


class InputGuard:
    """
    Node thực hiện 3 lớp kiểm tra đầu vào theo thứ tự:
    L1 (Rate) → L2a (Regex) → L2b (Bedrock).

    Trả về state với guardrail_violations nếu bị block,
    hoặc state không đổi nếu pass.
    """

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()
        violations = []

        # ── Lấy thông tin user và tin nhắn ──
        user_id = state.get("user_id", "anonymous")
        messages = state.get("messages", [])
        if not messages:
            logger.warning("[INPUT_GUARD] Không có messages trong state")
            return {"node_durations": {"InputGuard": self._ms(t0)}}

        # Lấy nội dung tin nhắn cuối cùng của user
        last_message = messages[-1]
        if hasattr(last_message, "content"):
            user_text = last_message.content
        else:
            user_text = str(last_message)

        logger.info("[INPUT_GUARD] Kiểm tra | user=%s | msg=%.80s", user_id, user_text)

        # ── L1: Rate Limiter ──
        rate_result = rate_limiter.check_rate_limit(user_id)
        if not rate_result.is_allowed:
            logger.warning("[INPUT_GUARD] L1 BLOCK | user=%s | reason=%s", user_id, rate_result.blocked_reason)
            violations.append({
                "guardrail": "L1",
                "type": "RATE_LIMIT",
                "detail": rate_result.blocked_reason,
            })
            return {
                "guardrail_violations": violations,
                "final_answer": rate_result.blocked_reason,
                "node_durations": {"InputGuard": self._ms(t0)},
            }

        logger.debug("[INPUT_GUARD] L1 PASS | remaining=%d req/min", rate_result.remaining_minute)

        # ── L2a: Regex Input Filter ──
        regex_result = check_input(user_text)
        if not regex_result.is_safe:
            detail = regex_result.blocked_reason or "Tin nhắn bị chặn bởi bộ lọc đầu vào."
            logger.warning("[INPUT_GUARD] L2a BLOCK | user=%s | reason=%s", user_id, detail)
            violations.append({
                "guardrail": "L2a",
                "type": "REGEX_BLOCK",
                "detail": detail,
            })
            return {
                "guardrail_violations": violations,
                "final_answer": detail,
                "node_durations": {"InputGuard": self._ms(t0)},
            }

        logger.debug("[INPUT_GUARD] L2a PASS")

        # ── L2b: Bedrock Guardrail ──
        bedrock_result = check_input_bedrock(user_text)
        if not bedrock_result.is_safe:
            detail = bedrock_result.blocked_reason or "Yêu cầu bị từ chối bởi chính sách bảo mật."
            logger.warning("[INPUT_GUARD] L2b BLOCK | user=%s | reason=%s", user_id, detail)
            violations.append({
                "guardrail": "L2b",
                "type": "BEDROCK_BLOCK",
                "detail": detail,
            })
            return {
                "guardrail_violations": violations,
                "final_answer": detail,
                "node_durations": {"InputGuard": self._ms(t0)},
            }

        logger.debug("[INPUT_GUARD] L2b PASS | All guardrails passed")

        return {
            "guardrail_violations": [],
            "node_durations": {"InputGuard": self._ms(t0)},
        }

    @staticmethod
    def _ms(t0_ns: int) -> int:
        return (time.monotonic_ns() - t0_ns) // 1_000_000
