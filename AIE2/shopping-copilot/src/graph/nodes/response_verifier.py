"""
graph/nodes/response_verifier.py — Template-First Response Verifier

Thuật toán:
1. Tính complexity score
2. Template-First decision tree (9 paths)
3. LLM path khi complexity > 0.5
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

logger = logging.getLogger("graph.response_verifier")

# ── Templates ─────────────────────────────────────────────────────

TEMPLATES: dict[str, list[str]] = {
    "cart": [
        "Giỏ hàng của bạn có {count} món: {items}. Tổng cộng {total}.",
        "Bạn đang có {count} sản phẩm trong giỏ: {items}. Tổng tiền: {total}.",
        "Giỏ hàng hiện tại gồm {count} mặt hàng: {items}. Tổng: {total}.",
    ],
    "cart_empty": [
        "Giỏ hàng của bạn hiện đang trống.",
        "Bạn chưa có sản phẩm nào trong giỏ hàng.",
        "Giỏ hàng trống. Bạn có muốn tìm kiếm sản phẩm nào không?",
    ],
    "shipping": [
        "Phí vận chuyển đến {destination}: {cost}, giao trong {days} ngày.",
        "Chi phí ship đến {destination} là {cost}. Thời gian giao hàng khoảng {days} ngày.",
        "Vận chuyển đến {destination}: {cost} ({days} ngày làm việc).",
    ],
    "currency": [
        "{amount} {from_c} tương đương {converted} {to_c} (tỷ giá {rate}).",
        "{amount} {from_c} = {converted} {to_c}. Tỷ giá hiện tại: 1 {from_c} = {rate} {to_c}.",
        "Quy đổi: {amount} {from_c} → {converted} {to_c} (tỷ giá tham khảo: {rate}).",
    ],
    "reviews": [
        "Sản phẩm được đánh giá {avg}/5 sao từ {total} đánh giá. {top_review}",
        "Điểm trung bình: {avg}/5 ({total} đánh giá). {top_review}",
        "Khách hàng đánh giá {avg}/5 sao ({total} reviews). {top_review}",
    ],
    "reviews_none": [
        "Sản phẩm này chưa có đánh giá nào.",
        "Chưa có khách hàng nào đánh giá sản phẩm này.",
        "Hiện tại chưa có đánh giá nào cho sản phẩm này.",
    ],
    "confirm": [
        "Vui lòng xác nhận: thêm {quantity} {product_name} vào giỏ hàng.",
        "Bạn muốn thêm {quantity} {product_name} vào giỏ? Vui lòng xác nhận.",
        "Xác nhận thêm {quantity} **{product_name}** vào giỏ hàng?",
    ],
    "search_single": [
        "Tôi tìm thấy {count} sản phẩm: {product_list}.",
        "Có {count} sản phẩm phù hợp: {product_list}.",
        "Kết quả tìm kiếm ({count} sản phẩm): {product_list}.",
    ],
    "search_none": [
        "Tôi không tìm thấy sản phẩm nào phù hợp với yêu cầu của bạn.",
        "Không có sản phẩm nào khớp với tìm kiếm này.",
        "Rất tiếc, không tìm thấy sản phẩm phù hợp. Bạn có thể thử từ khóa khác?",
    ],
}


def _format_product_list(products: list, max_count: int = 5) -> str:
    if not products:
        return ""
    shown = products[:max_count]
    parts = []
    for p in shown:
        name = p.get("name", "")
        price = p.get("price", "")
        parts.append(f"**{name}** ({price})" if price else f"**{name}**")
    result = ", ".join(parts)
    extra = len(products) - max_count
    if extra > 0:
        result += f" và {extra} sản phẩm khác"
    return result


def _compute_complexity(state: dict) -> float:
    score = 0.0
    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""
    word_count = len(query.split())
    if word_count > 20:
        score += 0.2
    elif word_count > 10:
        score += 0.1

    tool_results = {k: v for k, v in (state.get("tool_results") or {}).items() if not k.startswith("__")}
    tool_count = len(tool_results)
    score += min(tool_count * 0.1, 0.3)

    # Result size
    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        total = r.get("total", 0) or len(r.get("products", [])) or len(r.get("items", []))
        if total > 10:
            score += 0.2
        elif total > 5:
            score += 0.1
        break

    if state.get("pending_action"):
        score += 0.1

    return min(score, 1.0)


def _format_tool_results_text(tool_results: dict) -> str:
    lines = []
    for tool_name, result in tool_results.items():
        if tool_name.startswith("__"):
            continue
        r = result if isinstance(result, dict) else {"raw": str(result)[:200]}
        lines.append(f"[{tool_name}]: {json.dumps(r, ensure_ascii=False)[:400]}")
    return "\n".join(lines)


async def response_verifier_node(state: dict) -> dict:
    """
    Template-First Response Verifier.
    Output: {final_answer, complexity_score, node_durations}
    """
    t0 = time.time()

    # ── Skip conditions ──
    if state.get("guardrail_violations"):
        return {"node_durations": {"response_verifier": int((time.time() - t0) * 1000)}}
    if state.get("fallback_used"):
        return {"node_durations": {"response_verifier": int((time.time() - t0) * 1000)}}

    tool_results = state.get("tool_results") or {}
    pending = state.get("pending_action")

    if not tool_results and not pending:
        import re
        messages = state.get("messages", [])
        query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""
        if re.search(r"^(xin chào|chào|hello|hi|hey)\b", query.strip(), re.I):
            final_answer = "Xin chào! Tôi là trợ lý mua sắm của TechX Corp. Tôi có thể giúp bạn tìm kiếm sản phẩm, xem đánh giá, hoặc thêm hàng vào giỏ."
        else:
            final_answer = "Vui lòng cho tôi biết bạn cần tìm kiếm hay thực hiện thao tác gì?"
        return {
            "final_answer": final_answer,
            "complexity_score": 0.0,
            "node_durations": {"response_verifier": int((time.time() - t0) * 1000)},
        }

    complexity = _compute_complexity(state)
    tool_keys = set(tool_results.keys())

    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""

    final_answer = ""

    # ── Template-First Decision Tree ──

    # Pending action → confirm template
    if pending:
        item = pending.get("args", {})
        product_name = item.get("product_name", item.get("product_id", "sản phẩm"))
        quantity = item.get("quantity", 1)
        final_answer = random.choice(TEMPLATES["confirm"]).format(
            quantity=quantity, product_name=product_name
        )

    # cart only
    elif tool_keys == {"get_cart_tool"}:
        r = tool_results.get("get_cart_tool", {})
        if r.get("status") == "empty" or not r.get("items"):
            final_answer = random.choice(TEMPLATES["cart_empty"])
        else:
            items_text = _format_product_list(r.get("items", []))
            final_answer = random.choice(TEMPLATES["cart"]).format(
                count=r.get("item_count", 0),
                items=items_text,
                total=r.get("subtotal", "$0.00"),
            )

    # shipping only
    elif tool_keys == {"get_shipping_quote_tool"}:
        r = tool_results.get("get_shipping_quote_tool", {})
        if r.get("status") == "success":
            final_answer = random.choice(TEMPLATES["shipping"]).format(
                destination=r.get("destination", "địa chỉ"),
                cost=r.get("cost", "N/A"),
                days=r.get("days", "?"),
            )

    # currency only
    elif tool_keys == {"convert_currency_tool"}:
        r = tool_results.get("convert_currency_tool", {})
        if r.get("status") == "success":
            final_answer = random.choice(TEMPLATES["currency"]).format(
                amount=r.get("amount", 0),
                from_c=r.get("from", "USD"),
                converted=r.get("converted", 0),
                to_c=r.get("to", "VND"),
                rate=r.get("rate", "N/A"),
            )

    # reviews only
    elif tool_keys == {"get_product_reviews_tool"}:
        r = tool_results.get("get_product_reviews_tool", {})
        if r.get("total_reviews", 0) == 0:
            final_answer = random.choice(TEMPLATES["reviews_none"])
        else:
            reviews = r.get("reviews", [])
            top_review = f"\"{reviews[0].get('body', '')}\" — {reviews[0].get('username', '')}" if reviews else ""
            final_answer = random.choice(TEMPLATES["reviews"]).format(
                avg=r.get("average_score", 0),
                total=r.get("total_reviews", 0),
                top_review=top_review,
            )

    # search only
    elif tool_keys == {"search_products_v2"}:
        r = tool_results.get("search_products_v2", {})
        total = r.get("total", 0)
        if total == 0:
            final_answer = random.choice(TEMPLATES["search_none"])
        elif total <= 3:
            product_list = _format_product_list(r.get("products", []))
            final_answer = random.choice(TEMPLATES["search_single"]).format(
                count=total, product_list=product_list
            )
        # else → LLM path below

    # ── LLM path ──
    if not final_answer:
        try:
            from src.llm.llm import get_llm_client
            from src.llm.prompt import VERIFIER_PROMPT

            llm = get_llm_client()
            tool_results_text = _format_tool_results_text(tool_results)

            # Dynamic temperature
            if complexity < 0.2:
                temp = 0.1
            elif complexity < 0.5:
                temp = 0.3
            elif complexity < 0.8:
                temp = 0.4
            else:
                temp = 0.6

            resp = llm.invoke(
                VERIFIER_PROMPT.format(user_query=query, tool_results_text=tool_results_text),
                temperature=temp,
                max_tokens=1200,
            )
            final_answer = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning("[response_verifier] LLM failed: %s", e)
            # Fallback: raw results summary
            final_answer = _format_tool_results_text(tool_results)[:500]

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "final_answer": final_answer,
        "complexity_score": complexity,
        "node_durations": {"response_verifier": duration_ms},
    }
