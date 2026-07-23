"""
graph/nodes/input_guard.py — Input Guard Node (L1 + L2a + L2b)

Chạy đầu tiên trong graph: rate limit + regex filter + Bedrock guardrail.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("graph.input_guard")


async def input_guard_node(state: dict) -> dict:
    """
    Input Guard: L1 rate limit + L2 input filter.
    Output: {guardrail_violations, final_answer?, node_durations}
    """
    t0 = time.time()

    messages = state.get("messages", [])
    user_id = state.get("user_id", "anonymous")
    query = ""
    if messages:
        last = messages[-1]
        query = last.content if hasattr(last, "content") else str(last)

    violations = []

    # ── L1: Rate Limiter ──
    try:
        from src.guardrails.rate_limiter import rate_limiter
        result = rate_limiter.check_rate_limit(user_id)
        if not result.is_allowed:
            violations.append({
                "type": "RATE_LIMIT",
                "detail": result.blocked_reason,
                "tier": "L1",
            })
    except Exception as e:
        logger.warning("[input_guard] rate_limiter error: %s", e)

    # ── L2a: Regex input filter ──
    if not violations and query:
        try:
            from src.guardrails.input_filter import check_input
            result = check_input(query)
            if not result.is_safe:
                violations.append({
                    "type": result.blocked_tier or "REGEX",
                    "detail": result.blocked_reason,
                    "tier": "L2a",
                })
        except Exception as e:
            logger.warning("[input_guard] input_filter error: %s", e)

    # ── L2b: Bedrock Guardrail (optional) ──
    if not violations and query:
        try:
            from src.guardrails.input_filter import check_input_bedrock
            result = check_input_bedrock(query)
            if not result.is_safe:
                violations.append({
                    "type": "BEDROCK",
                    "detail": result.blocked_reason,
                    "tier": "L2b",
                })
        except Exception as e:
            logger.debug("[input_guard] bedrock guardrail skip: %s", e)

    duration_ms = int((time.time() - t0) * 1000)

    output: dict = {
        "guardrail_violations": violations,
        "node_durations": {"input_guard": duration_ms},
    }

    if violations:
        output["final_answer"] = violations[0]["detail"]

    return output
