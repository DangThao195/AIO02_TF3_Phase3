"""
graph/edges.py — Conditional edge functions cho LangGraph StateGraph.

Mỗi function nhận state → trả về string tên node tiếp theo.
"""

from __future__ import annotations

import logging

from src.graph.state import ShoppingState

logger = logging.getLogger("graph.edges")


# ──────────────────────────────────────────────────────────────────
# Main routing: Router → workflow
# ──────────────────────────────────────────────────────────────────

def route_to_workflow(state: "ShoppingState") -> str:
    """
    Router → workflow conditional edge.

    Đọc intent từ state, route thẳng tới workflow tương ứng.
    Mọi workflow luôn active (Phase 3 — pure LangGraph).
    """
    intent = state.get("intent", "agent")
    logger.debug("[ROUTER] intent=%s → %s_workflow", intent, intent)
    return intent  # → {intent}_workflow node


# ──────────────────────────────────────────────────────────────────
# SearchWorkflow edges
# ──────────────────────────────────────────────────────────────────

def route_search_results(state: "ShoppingState") -> str:
    """
    SearchProducts node → conditional edge.
    Dựa trên số lượng candidate_products:
    - 0 results → "zero" (→ semantic_search fallback)
    - 1 result  → "one"  (→ END, đủ kết quả)
    - N results → "many" (→ ask_user)
    """
    products = state.get("candidate_products", [])
    count = len(products)
    if count == 0:
        return "zero"
    if count == 1:
        return "one"
    return "many"


# ──────────────────────────────────────────────────────────────────
# CartWorkflow edges
# ──────────────────────────────────────────────────────────────────

def route_stock_result(state: "ShoppingState") -> str:
    """
    StockCheck node → conditional edge.
    Đọc kết quả stock check từ tool_results.
    """
    # Tool executor set kết quả vào tool_results với key "check_cart_item_tool:..."
    tool_results = state.get("tool_results", {})
    for key, val in tool_results.items():
        if key.startswith("check_cart_item_tool:"):
            result = val.get("result", "")
            if isinstance(result, str) and "out_of_stock" in result.lower():
                return "out_of_stock"
            break
    # Mặc định: còn hàng → tiến đến confirmation
    return "in_stock"


def route_confirmation(state: "ShoppingState") -> str:
    """
    Confirmation node → conditional edge.
    - pending_action còn tồn tại + confirmed=False → "pending" (chờ user)
    - confirmed=True → "confirmed"
    - không có pending_action → "denied" (user từ chối hoặc lỗi)
    """
    pending = state.get("pending_action")
    confirmed = state.get("confirmed", False)

    if confirmed:
        return "confirmed"
    if pending:
        return "pending"
    return "denied"


# ──────────────────────────────────────────────────────────────────
# ReviewWorkflow / RecommendWorkflow edges
# ──────────────────────────────────────────────────────────────────

def route_product_id_found(state: "ShoppingState") -> str:
    """
    GetProductID node → conditional edge.
    Nếu tìm được product_id → "continue", không → "skip".
    """
    if state.get("current_product_id"):
        return "continue"
    return "skip"


# ──────────────────────────────────────────────────────────────────
# InputGuard edge
# ──────────────────────────────────────────────────────────────────

def route_after_input_guard(state: "ShoppingState") -> str:
    """
    InputGuard node → conditional edge.
    Nếu có guardrail violation → "blocked" (→ END ngay).
    Không có → "pass" (→ intent_classifier).
    """
    violations = state.get("guardrail_violations", [])
    if violations:
        return "blocked"
    return "pass"
