"""
graph/nodes/answer_generator.py — AnswerGenerator node.

Node cuối trong main graph. Thực hiện:
  L5: Output Filter (PII redaction)
  ResponseFormatter (markdown restructure)
  L6: Token usage tracking

Input:  state["final_answer"] (set bởi workflow)
Output: state["final_answer"] (filtered + formatted)
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING

from src.guardrails.output_filter import filter_output
from src.guardrails.rate_limiter import rate_limiter

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.answer_generator")


class AnswerGenerator:
    """
    Node xử lý câu trả lời cuối cùng trước khi trả về client:
    1. L5: Output Filter — redact PII (email, phone, IP, ...)
    2. ResponseFormatter — cấu trúc lại thành markdown
    3. L6: Record token usage (nếu có trong tool_results)
    """

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        final_answer = state.get("final_answer", "")
        user_id = state.get("user_id", "anonymous")
        session_id = state.get("session_id", "")

        # Nếu không có final_answer (workflow lỗi) → trả lỗi chung
        if not final_answer:
            errors = state.get("errors", [])
            if errors:
                last_error = errors[-1]
                final_answer = f"Có lỗi xảy ra khi xử lý yêu cầu: {last_error.get('error', 'Unknown error')[:150]}"
            else:
                final_answer = "Xin lỗi, tôi không thể xử lý yêu cầu của bạn lúc này."

        # ── L5: Output Filter (PII) ──
        try:
            output_result = filter_output(final_answer)
            filtered = output_result.filtered_response
            redacted_count = len(output_result.redacted_items) if hasattr(output_result, "redacted_items") else 0
            if redacted_count > 0:
                logger.info(
                    "[ANSWER_GEN] L5 redacted %d items | session=%s",
                    redacted_count, session_id
                )
            final_answer = filtered
        except Exception as e:
            logger.error("[ANSWER_GEN] L5 filter error: %s", e)
            # Giữ nguyên nếu filter lỗi

        # ── ResponseFormatter ──
        try:
            from src.agent.response_formatter import format_response
            formatted = format_response(final_answer)
            if formatted:
                final_answer = formatted
                logger.debug("[ANSWER_GEN] Formatted to markdown | session=%s", session_id)
        except Exception as e:
            logger.debug("[ANSWER_GEN] ResponseFormatter error (non-fatal): %s", e)

        # ── L6: Token usage tracking ──
        # Phase 2: token tracking đơn giản (estimate)
        # Phase 3: lấy từ usage_metadata của LLM response
        try:
            estimated_tokens = max(1, len(final_answer) // 4)  # rough estimate
            rate_limiter.record_token_usage(user_id, estimated_tokens)
        except Exception as e:
            logger.debug("[ANSWER_GEN] Token tracking error (non-fatal): %s", e)

        ms = (time.monotonic_ns() - t0) // 1_000_000
        logger.info(
            "[ANSWER_GEN] Done | session=%s | answer_len=%d | %dms",
            session_id, len(final_answer), ms
        )

        return {
            "final_answer": final_answer,
            "node_durations": {"AnswerGenerator": ms},
        }
