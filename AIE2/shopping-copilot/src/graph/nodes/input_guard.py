"""
graph/nodes/input_guard.py — Input Guard Node (L1 + L2a + L2b + L2c)

Chạy đầu tiên trong graph: rate limit + regex filter + Bedrock guardrail + action guard.
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger("graph.input_guard")


# ── L2c: Action Guard — các hành động bị cấm tuyệt đối ──
_DISALLOWED_ACTION_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (regex, action_name, refusal_message)
    (re.compile(r"(?:xóa|clear|empty|xoá|bỏ)\s*(?:toàn\s*bộ\s*)?(?:giỏ\s*hàng|cart|sản\s*phẩm)", re.I),
     "EmptyCart",
     "Xin lỗi, tôi không thể xóa giỏ hàng của bạn. Tôi chỉ hỗ trợ tìm kiếm sản phẩm và thêm sản phẩm vào giỏ hàng."),
    (re.compile(r"(?:checkout|thanh\s*toán|place\s*order|đặt\s*hàng|mua\s*luôn|tiến\s*hành\s*đơn)", re.I),
     "PlaceOrder",
     "Xin lỗi, tôi không thể tự động thanh toán hay đặt hàng. Tôi chỉ hỗ trợ tìm kiếm sản phẩm và thêm sản phẩm vào giỏ hàng."),
    (re.compile(r"(?:chuyển|transfer|gửi)\s*(?:toàn\s*bộ\s*)?(?:các\s*)?(?:sản\s*phẩm|hàng|giỏ\s*hàng|của\s*tôi)\s*(?:trong\s*giỏ\s*)?(?:cho|sang|đến|to)\s*(?:user|người\s*dùng|tài\s*khoản)\s+khác", re.I),
     "TransferCart",
     "Xin lỗi, tôi không thể chuyển sản phẩm hay giỏ hàng cho tài khoản khác. Tôi chỉ hỗ trợ tìm kiếm sản phẩm và thêm sản phẩm vào giỏ hàng."),
    (re.compile(r"(?:xác\s*nhận\s*đơn|xác\s*nhận\s*(?:hàng|order)|confirm\s*order)\s*(?:giúp|cho|với)", re.I),
     "ConfirmOrder",
     "Xin lỗi, tôi không thể xác nhận đơn hàng. Tôi chỉ hỗ trợ tìm kiếm sản phẩm và thêm sản phẩm vào giỏ hàng."),
]


async def input_guard_node(state: dict) -> dict:
    """
    Input Guard: L1 rate limit + L2 input filter + L2c action guard.
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

    # ── L2c: Action Guard — chặn hành động bị cấm ──
    if not violations and query:
        for pattern, action, refusal in _DISALLOWED_ACTION_PATTERNS:
            if pattern.search(query):
                logger.info("[input_guard] Action guard blocked | action=%s | query=%.60s", action, query)
                violations.append({
                    "type": f"ACTION_BLOCKED_{action}",
                    "detail": refusal,
                    "tier": "L2c",
                })
                break

    duration_ms = int((time.time() - t0) * 1000)

    output: dict = {
        "guardrail_violations": violations,
        "node_durations": {"input_guard": duration_ms},
    }

    if violations:
        output["final_answer"] = violations[0]["detail"]

    return output
