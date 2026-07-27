"""
graph/nodes/response_generator.py — Response Generator (merged)

Thay thế response_verifier + fallback_generator cũ.

2 modes:
  - "template": tool results khớp pattern → build từ rich template (safe, giữ data)
  - "llm":      phức tạp, không khớp template → dùng draft từ answer_synthesizer

Flow:
  1. Template-first: match tool results với 9 pattern
  2. Nếu match → build answer từ template giàu data, mode="template"
  3. Nếu không match và not safe_mode → giữ LLM draft, mode="llm"
  4. Nếu không match và safe_mode → generic fallback, mode="template"
"""

from __future__ import annotations

import json
import logging
import random
import re
import time

logger = logging.getLogger("graph.response_generator")

_TEMPLATES: dict[str, list[str]] = {
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
    "filter_result": [
        "Tôi tìm thấy {total} sản phẩm phù hợp: {product_list}.",
        "Có {total} kết quả: {product_list}.",
        "Kết quả ({total} sản phẩm): {product_list}.",
    ],
    "filter_empty": [
        "Không tìm thấy sản phẩm nào phù hợp với yêu cầu của bạn.",
        "Rất tiếc, không có sản phẩm nào khớp với yêu cầu này.",
    ],
    "safe_fallback": [
        "Xin lỗi, tôi không thể xử lý yêu cầu này. Bạn có thể thử diễn đạt lại hoặc hỏi về sản phẩm khác được không?",
        "Tôi chưa hiểu rõ yêu cầu của bạn. Vui lòng thử diễn đạt lại.",
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


def _build_from_templates(state: dict) -> tuple[str, str]:
    """
    Template-first decision tree.
    Returns: (final_answer, mode)
    """
    tool_results = state.get("tool_results") or {}
    pending = state.get("pending_action")
    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""

    # Pending action → confirm template (giữ product_name, quantity)
    if pending:
        item = pending.get("args", {})
        product_name = item.get("product_name", item.get("product_id", "sản phẩm"))
        quantity = item.get("quantity", 1)
        return (
            random.choice(_TEMPLATES["confirm"]).format(
                quantity=quantity, product_name=product_name
            ),
            "template",
        )

    # Guardrail violations
    if state.get("guardrail_violations"):
        return "", "template"

    tool_keys = set(tool_results.keys())

    # cart only
    if tool_keys == {"get_cart_tool"}:
        r = tool_results.get("get_cart_tool", {})
        if r.get("status") == "empty" or not r.get("items"):
            return random.choice(_TEMPLATES["cart_empty"]), "template"
        items_text = _format_product_list(r.get("items", []))
        return (
            random.choice(_TEMPLATES["cart"]).format(
                count=r.get("item_count", 0),
                items=items_text,
                total=r.get("subtotal", "$0.00"),
            ),
            "template",
        )

    # shipping only
    if tool_keys == {"get_shipping_quote_tool"}:
        r = tool_results.get("get_shipping_quote_tool", {})
        if r.get("status") == "success":
            return (
                random.choice(_TEMPLATES["shipping"]).format(
                    destination=r.get("destination", "địa chỉ"),
                    cost=r.get("cost", "N/A"),
                    days=r.get("days", "?"),
                ),
                "template",
            )

    # currency only
    if tool_keys == {"convert_currency_tool"}:
        r = tool_results.get("convert_currency_tool", {})
        if r.get("status") == "success":
            return (
                random.choice(_TEMPLATES["currency"]).format(
                    amount=r.get("amount", 0),
                    from_c=r.get("from", "USD"),
                    converted=r.get("converted", 0),
                    to_c=r.get("to", "VND"),
                    rate=r.get("rate", "N/A"),
                ),
                "template",
            )
        if r.get("status") == "error":
            msg = r.get("message", "Dịch vụ quy đổi tiền tệ tạm thời không khả dụng.")
            return f"Xin lỗi, {msg} Vui lòng thử lại sau.", "template"

    # reviews only
    if tool_keys == {"get_product_reviews_tool"}:
        r = tool_results.get("get_product_reviews_tool", {})
        if r.get("total_reviews", 0) == 0:
            return random.choice(_TEMPLATES["reviews_none"]), "template"
        reviews = r.get("reviews", [])
        top_review = f"\"{reviews[0].get('body', '')}\" — {reviews[0].get('username', '')}" if reviews else ""
        return (
            random.choice(_TEMPLATES["reviews"]).format(
                avg=r.get("average_score", 0),
                total=r.get("total_reviews", 0),
                top_review=top_review,
            ),
            "template",
        )

    # search only
    if tool_keys == {"search_products_v2"}:
        r = tool_results.get("search_products_v2", {})
        total = r.get("total", 0)
        products = r.get("products", [])
        if total == 0:
            return random.choice(_TEMPLATES["search_none"]), "template"
        product_list = _format_product_list(products, max_count=5)
        if product_list:
            return f"Tôi tìm thấy **{total}** sản phẩm phù hợp:\n{product_list}.", "template"
        return (
            random.choice(_TEMPLATES["search_single"]).format(
                count=total, product_list=""
            ),
            "template",
        )

    # categories only
    if tool_keys == {"get_categories"}:
        r = tool_results.get("get_categories", {})
        cats = r.get("categories", [])
        if cats:
            return f"Trong cửa hàng có {len(cats)} danh mục sản phẩm: {', '.join(cats)}.", "template"
        return "Không tìm thấy danh mục sản phẩm nào.", "template"

    # all products only
    if tool_keys == {"get_all_products"}:
        r = tool_results.get("get_all_products", {})
        total = r.get("total", 0) or len(r.get("products", []))
        if total == 0:
            return random.choice(_TEMPLATES["search_none"]), "template"
        product_list = _format_product_list(r.get("products", []), max_count=20)
        return f"Hiện tại cửa hàng có {total} sản phẩm: {product_list}.", "template"

    # best reviewed
    if tool_keys == {"get_best_reviewed_products_tool"}:
        r = tool_results.get("get_best_reviewed_products_tool", {})
        products = r.get("products", [])
        if not products:
            return "Không tìm thấy sản phẩm nào trong danh sách đánh giá cao.", "template"
        lines = []
        for p in products[:5]:
            name = p.get("name", "")
            score = p.get("avg_score", "")
            price = p.get("price", "")
            lines.append(f"**{name}** ({score}/5, {price})")
        return "Sản phẩm được đánh giá cao nhất: " + "; ".join(lines), "template"

    # worst reviewed
    if tool_keys == {"get_worst_reviewed_products_tool"}:
        r = tool_results.get("get_worst_reviewed_products_tool", {})
        products = r.get("products", [])
        if not products:
            return "Không tìm thấy sản phẩm nào trong danh sách đánh giá thấp.", "template"
        lines = []
        for p in products[:5]:
            name = p.get("name", "")
            score = p.get("avg_score", "")
            price = p.get("price", "")
            lines.append(f"**{name}** ({score}/5, {price})")
        return "Sản phẩm đánh giá thấp nhất: " + "; ".join(lines), "template"

    # product details
    if "get_product_details_tool" in tool_keys:
        details_r = tool_results.get("get_product_details_tool", {})
        product = details_r.get("product", details_r)
        if product and product.get("name"):
            name = product.get("name", "")
            price = product.get("price", "")
            desc = product.get("description", "")
            return f"**{name}** — giá {price}. {desc}", "template"
        if product and product.get("product"):
            p = product["product"]
            name = p.get("name", "")
            price = p.get("price", "")
            desc = p.get("description", "")
            return f"**{name}** — giá {price}. {desc}", "template"
        return "Không tìm thấy thông tin sản phẩm.", "template"

    # add_to_cart
    if "add_to_cart_tool" in tool_keys:
        cart_r = tool_results.get("add_to_cart_tool", {})
        if cart_r.get("status") == "pending":
            return "Vui lòng xác nhận để thêm sản phẩm vào giỏ hàng.", "template"
        return "Không thể thêm sản phẩm vào giỏ hàng.", "template"

    # recommendations
    if "get_recommendations_tool" in tool_keys:
        rec_r = tool_results.get("get_recommendations_tool", {})
        recs = rec_r.get("recommendations", [])
        if recs:
            rec_list = _format_product_list(recs, max_count=5)
            return f"Có {len(recs)} sản phẩm được gợi ý liên quan:\n{rec_list}.", "template"
        return "Không tìm thấy sản phẩm gợi ý liên quan.", "template"

    # category_filter only
    if tool_keys == {"category_filter"}:
        r = tool_results.get("category_filter", {})
        products = r.get("products", [])
        if not products:
            return random.choice(_TEMPLATES["filter_empty"]), "template"
        product_list = _format_product_list(products, max_count=10)
        return (
            random.choice(_TEMPLATES["filter_result"]).format(
                total=r.get("total", len(products)),
                product_list=product_list,
            ),
            "template",
        )

    # price_filter only
    if tool_keys == {"price_filter"}:
        r = tool_results.get("price_filter", {})
        products = r.get("products", [])
        if not products:
            return random.choice(_TEMPLATES["filter_empty"]), "template"
        product_list = _format_product_list(products, max_count=10)
        return (
            random.choice(_TEMPLATES["filter_result"]).format(
                total=r.get("total", len(products)),
                product_list=product_list,
            ),
            "template",
        )

    # semantic_filter only
    if tool_keys == {"semantic_filter"}:
        r = tool_results.get("semantic_filter", {})
        products = r.get("products", [])
        if not products:
            return random.choice(_TEMPLATES["filter_empty"]), "template"
        product_list = _format_product_list(products, max_count=10)
        return (
            random.choice(_TEMPLATES["filter_result"]).format(
                total=r.get("total", len(products)),
                product_list=product_list,
            ),
            "template",
        )

    # multi_filter only
    if tool_keys == {"multi_filter"}:
        r = tool_results.get("multi_filter", {})
        products = r.get("products", [])
        if not products:
            return random.choice(_TEMPLATES["filter_empty"]), "template"
        product_list = _format_product_list(products, max_count=10)
        chain = r.get("filter_chain", [])
        chain_desc = ""
        if chain:
            steps = [f"{s['filter'].get('type','?')}({s['total']})" for s in chain]
            chain_desc = f" (qua {' → '.join(steps)})"
        answer = random.choice(_TEMPLATES["filter_result"]).format(
            total=r.get("total", len(products)),
            product_list=product_list,
        )
        return answer + chain_desc, "template"

    # out of scope
    if "respond_out_of_scope_tool" in tool_keys:
        oos_r = tool_results.get("respond_out_of_scope_tool", {})
        if isinstance(oos_r, dict):
            reply = oos_r.get("response") or oos_r.get("message") or oos_r.get("reply", "")
            if reply:
                return reply, "template"
            reason = oos_r.get("reason", "general")
            if reason == "greeting":
                return "Xin chào! Tôi là trợ lý mua sắm của TechX Corp. Tôi có thể giúp bạn tìm kiếm sản phẩm, xem đánh giá, hoặc thêm hàng vào giỏ.", "template"
            if reason == "personal_info":
                return "Tôi không thể cung cấp hoặc tra cứu thông tin cá nhân như số điện thoại hay thông tin riêng tư của khách hàng.", "template"
            return "Câu hỏi này nằm ngoài phạm vi hỗ trợ mua sắm của tôi. Tôi có thể giúp bạn tìm kiếm sản phẩm hoặc quản lý giỏ hàng.", "template"

    # No template matched
    return "", ""


async def response_generator_node(state: dict) -> dict:
    """
    Response Generator: template-first decision tree → LLM path (if complex & not safe mode).

    Output: {final_answer, complexity_score, response_mode, node_durations}
    """
    t0 = time.time()
    safe_mode = state.get("safe_mode", False)

    # Step 1: Template-first
    answer, mode = _build_from_templates(state)

    # Step 2: Nếu template match → return ngay, không cần guard (mode=template auto-PASS)
    if mode == "template" and answer:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "final_answer": answer,
            "complexity_score": 0.0,
            "response_mode": "template",
            "node_durations": {"response_generator": duration_ms},
        }

    # Step 3: Nếu có draft từ answer_synthesizer (LLM) → giữ draft, mode=llm
    draft = state.get("final_answer", "")
    if draft and not safe_mode:
        complexity = _compute_complexity(state)
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "final_answer": draft,
            "complexity_score": complexity,
            "response_mode": "llm",
            "node_durations": {"response_generator": duration_ms},
        }

    # Step 4: No template match, no draft, or safe_mode → generic fallback
    if not answer:
        answer = random.choice(_TEMPLATES["safe_fallback"])

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "final_answer": answer,
        "complexity_score": 0.0,
        "response_mode": "template",
        "node_durations": {"response_generator": duration_ms},
    }
