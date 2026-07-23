"""
graph/nodes/answer_generator.py — Answer Generator Node (L5 output filter + final format)

Chạy sau response_verifier hoặc fallback_generator.
Áp dụng L5 output filter để redact PII trước khi trả về user.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("graph.answer_generator")


async def answer_generator_node(state: dict) -> dict:
    """
    Answer Generator: L5 output filter + final response.
    Output: {final_answer, node_durations}
    """
    t0 = time.time()

    final_answer = state.get("final_answer", "")

    # Nếu chưa có final_answer (edge case), tạo từ tool_results
    if not final_answer:
        violations = state.get("guardrail_violations") or []
        if violations:
            final_answer = violations[0].get("detail", "Yêu cầu bị từ chối.")
        else:
            final_answer = "Tôi không có thông tin để trả lời câu hỏi này."

    # ── L5: Output Filter — redact PII ──
    try:
        from src.guardrails.output_filter import filter_output
        result = filter_output(final_answer)
        final_answer = result.filtered_response
        if result.redacted_items:
            logger.info("[answer_generator] Redacted: %s", result.redacted_items)
    except Exception as e:
        logger.warning("[answer_generator] output_filter error: %s", e)

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "final_answer": final_answer,
        "node_durations": {"answer_generator": duration_ms},
    }
