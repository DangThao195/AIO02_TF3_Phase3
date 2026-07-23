"""
graph/nodes/fallback_generator.py — FallbackGenerator

Tạo câu trả lời an toàn từ template khi HallucinationGuard phát hiện lỗi.
Priority: pending_action → single tool → multi tool ghép.
"""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger("graph.fallback_generator")

# ── Fallback templates per tool type ─────────────────────────────

_TEMPLATES: dict[str, list[str]] = {
    "get_cart_tool": [
        "Giỏ hàng của bạn có {count} sản phẩm. Tổng tiền: {subtotal}.",
        "Bạn đang có {count} mặt hàng trong giỏ, tổng cộng {subtotal}.",
        "Giỏ hàng: {count} sản phẩm — {subtotal}.",
    ],
    "get_cart_empty": [
        "Giỏ hàng của bạn hiện đang trống.",
        "Chưa có sản phẩm nào trong giỏ hàng.",
    ],
    "search_products_v2": [
        "Tôi tìm thấy {total} sản phẩm phù hợp với yêu cầu của bạn.",
        "Có {total} kết quả tìm kiếm cho yêu cầu của bạn.",
        "Tìm thấy {total} sản phẩm.",
    ],
    "search_products_v2_empty": [
        "Không tìm thấy sản phẩm phù hợp với yêu cầu của bạn.",
        "Rất tiếc, không có kết quả nào khớp với tìm kiếm này.",
    ],
    "get_product_reviews_tool": [
        "Sản phẩm có điểm đánh giá trung bình {avg}/5 từ {total} khách hàng.",
        "Đánh giá: {avg}/5 sao ({total} reviews).",
    ],
    "get_product_reviews_tool_empty": [
        "Sản phẩm này chưa có đánh giá nào.",
        "Chưa có khách hàng nào đánh giá sản phẩm này.",
    ],
    "convert_currency_tool": [
        "{amount} {from_c} tương đương khoảng {converted} {to_c}.",
        "Kết quả quy đổi: {amount} {from_c} = {converted} {to_c}.",
    ],
    "get_shipping_quote_tool": [
        "Phí vận chuyển đến địa chỉ của bạn: {cost}.",
        "Chi phí giao hàng: {cost} (khoảng {days} ngày).",
    ],
    "get_recommendations_tool": [
        "Có {total} sản phẩm được gợi ý liên quan.",
        "Tìm thấy {total} sản phẩm gợi ý cho bạn.",
    ],
    "add_to_cart_tool": [
        "Vui lòng xác nhận để thêm sản phẩm vào giỏ hàng.",
        "Cần xác nhận hành động thêm vào giỏ hàng.",
    ],
    "confirm": [
        "Vui lòng xác nhận hành động này.",
        "Bạn có muốn tiếp tục không? Vui lòng xác nhận.",
    ],
    "error": [
        "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.",
        "Không thể lấy thông tin lúc này. Vui lòng thử lại.",
    ],
}


def _render(tool_name: str, result: dict) -> str:
    """Render fallback template for a single tool."""
    # Confirm / pending
    if result.get("status") == "pending":
        return random.choice(_TEMPLATES["confirm"])

    # Cart
    if tool_name == "get_cart_tool":
        if result.get("status") == "empty" or not result.get("items"):
            return random.choice(_TEMPLATES["get_cart_empty"])
        return random.choice(_TEMPLATES["get_cart_tool"]).format(
            count=result.get("item_count", 0),
            subtotal=result.get("subtotal", "$0.00"),
        )

    # Search
    if tool_name == "search_products_v2":
        total = result.get("total", 0)
        if total == 0:
            return random.choice(_TEMPLATES["search_products_v2_empty"])
        return random.choice(_TEMPLATES["search_products_v2"]).format(total=total)

    # Reviews
    if tool_name == "get_product_reviews_tool":
        if result.get("total_reviews", 0) == 0:
            return random.choice(_TEMPLATES["get_product_reviews_tool_empty"])
        return random.choice(_TEMPLATES["get_product_reviews_tool"]).format(
            avg=result.get("average_score", 0),
            total=result.get("total_reviews", 0),
        )

    # Currency
    if tool_name == "convert_currency_tool":
        return random.choice(_TEMPLATES["convert_currency_tool"]).format(
            amount=result.get("amount", ""),
            from_c=result.get("from", "USD"),
            converted=result.get("converted", ""),
            to_c=result.get("to", "VND"),
        )

    # Shipping
    if tool_name == "get_shipping_quote_tool":
        return random.choice(_TEMPLATES["get_shipping_quote_tool"]).format(
            cost=result.get("cost", "N/A"),
            days=result.get("days", "?"),
        )

    # Recommendations
    if tool_name == "get_recommendations_tool":
        return random.choice(_TEMPLATES["get_recommendations_tool"]).format(
            total=result.get("total", len(result.get("recommendations", [])))
        )

    # Add to cart
    if tool_name == "add_to_cart_tool":
        return random.choice(_TEMPLATES["add_to_cart_tool"])

    # Error fallback
    if result.get("status") == "error":
        return random.choice(_TEMPLATES["error"])

    return random.choice(_TEMPLATES["error"])


async def fallback_generator_node(state: dict) -> dict:
    """
    FallbackGenerator — safe template response when hallucination detected.
    Output: {final_answer, fallback_used, node_durations}
    """
    t0 = time.time()

    tool_results = state.get("tool_results") or {}
    pending = state.get("pending_action")

    # Priority: pending action
    if pending:
        final_answer = random.choice(_TEMPLATES["confirm"])
    elif not tool_results:
        final_answer = random.choice(_TEMPLATES["error"])
    elif len(tool_results) == 1:
        tool_name, result = next(iter(tool_results.items()))
        r = result if isinstance(result, dict) else {}
        final_answer = _render(tool_name, r)
    else:
        # Multi-tool: render each and join
        parts = []
        for tool_name, result in tool_results.items():
            r = result if isinstance(result, dict) else {}
            rendered = _render(tool_name, r)
            parts.append(rendered)
        final_answer = " ".join(parts)

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[fallback_generator] generated safe response (%dms)", duration_ms)

    return {
        "final_answer": final_answer,
        "fallback_used": True,
        "node_durations": {"fallback_generator": duration_ms},
    }
