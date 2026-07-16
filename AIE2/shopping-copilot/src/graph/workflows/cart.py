"""
graph/workflows/cart.py — CartWorkflow subgraph.

Flow:
  START
    ↓
  route_intent   ← view_cart vs add_item
    ↓ (conditional)
  view_cart → get_cart → END
  add_item  → check_product_id  ← kiểm tra current_product_id từ state
              ↓ (conditional: found/not_found)
              found → stock_check  ← check_cart_item_tool
                      ↓ (conditional: in_stock/out_of_stock)
                      in_stock    → confirmation → confirmed → add_to_cart → aggregate → END
                                    → pending → END
                                    → denied → END
                      out_of_stock → END
              not_found → END (thông báo không tìm thấy sản phẩm)
    ↓
  END

"""

from __future__ import annotations

import json
import time
import logging

from langgraph.graph import StateGraph, START, END

from src.graph.state import ShoppingState
from src.graph.nodes.tool_executor import ToolExecutor
from src.graph.nodes.confirmation import ConfirmationNode
from src.graph.edges import route_product_id_found, route_stock_result, route_confirmation

logger = logging.getLogger("graph.workflows.cart")


# ──────────────────────────────────────────────────────────────────
# Helper nodes
# ──────────────────────────────────────────────────────────────────

def _check_product_id(state: ShoppingState) -> dict:
    """
    Kiểm tra current_product_id đã được resolve từ main graph.
    Conditional edge route_product_id_found sẽ quyết định continue/skip.
    """
    return {}


async def _get_cart_node(state: ShoppingState) -> dict:
    """
    Xem giỏ hàng: gọi get_cart_tool.
    Dùng khi intent là "xem giỏ" chứ không phải "thêm vào giỏ".
    """
    t0 = time.monotonic_ns()
    user_id = state.get("user_id", "anonymous")

    from src.tools import get_cart_tool
    try:
        result = await get_cart_tool.ainvoke({"user_id": user_id})

        if isinstance(result, str):
            try:
                data = json.loads(result)
                items = data.get("items", [])
            except Exception:
                items = []
        elif isinstance(result, dict):
            items = result.get("items", [])
        else:
            items = []

        if not items:
            answer = "🛒 Giỏ hàng của bạn đang **trống**."
        else:
            lines = [f"🛒 **Giỏ hàng của bạn** ({len(items)} sản phẩm):\n"]
            total = 0.0
            for i, item in enumerate(items, 1):
                name = item.get("name", item.get("product_id", "Unknown"))
                qty = item.get("quantity", 1)
                price_str = item.get("price", "0.00")
                try:
                    price_val = float(price_str) * qty
                    total += price_val
                    price_display = f"${price_val:.2f}"
                except Exception:
                    price_display = price_str
                lines.append(f"{i}. **{name}** × {qty} — {price_display}")
            lines.append(f"\n**Tổng cộng: ${total:.2f}**")
            answer = "\n".join(lines)

        return {
            "final_answer": answer,
            "node_durations": {"GetCart": _ms(t0)},
        }
    except Exception as e:
        return {
            "final_answer": f"Không thể lấy thông tin giỏ hàng: {str(e)[:100]}",
            "node_durations": {"GetCart": _ms(t0)},
        }


def _stock_check_args_builder(state: ShoppingState) -> dict:
    """Build args cho check_cart_item_tool."""
    product_id = state.get("current_product_id", "")
    user_id = state.get("user_id", "anonymous")
    entities = state.get("entities", {})
    return {
        "product_id": product_id,
        "user_id": user_id,
        "quantity": entities.get("quantity", 1),
    }


def _add_to_cart_args_builder(state: ShoppingState) -> dict:
    """Build args cho add_to_cart_tool."""
    product_id = state.get("current_product_id", "")
    user_id = state.get("user_id", "anonymous")
    entities = state.get("entities", {})
    return {
        "product_id": product_id,
        "user_id": user_id,
        "quantity": entities.get("quantity", 1),
    }


async def _handle_out_of_stock(state: ShoppingState) -> dict:
    """Thông báo hết hàng hoặc không tìm thấy sản phẩm."""
    entities = state.get("entities", {})
    product_name = entities.get("product_name", "sản phẩm")
    resolved_name = state.get("resolved_product_name") or product_name
    return {
        "final_answer": (
            f"❌ Sản phẩm **{resolved_name}** hiện đang **hết hàng** hoặc không tồn tại. "
            f"Bạn có muốn tôi tìm sản phẩm tương tự không?"
        ),
    }


async def _handle_denied(state: ShoppingState) -> dict:
    """Thông báo user đã từ chối."""
    return {"final_answer": "✅ Đã huỷ thao tác thêm vào giỏ hàng."}


async def _aggregate_add_to_cart(state: ShoppingState) -> dict:
    """Format kết quả add_to_cart thành final_answer."""
    t0 = time.monotonic_ns()
    tool_results = state.get("tool_results", {})
    entities = state.get("entities", {})
    product_name = entities.get("product_name", "sản phẩm")
    resolved_name = state.get("resolved_product_name") or product_name
    quantity = entities.get("quantity", 1)

    # Tìm kết quả add_to_cart
    for key, val in tool_results.items():
        if key.startswith("add_to_cart_tool:"):
            result_raw = val.get("result", "")
            err = val.get("error")

            if err:
                return {
                    "final_answer": f"❌ Không thể thêm vào giỏ: {err[:100]}",
                    "node_durations": {"AddToCart": _ms(t0)},
                }

            # Thành công
            return {
                "final_answer": (
                    f"✅ Đã thêm **{quantity}x {resolved_name}** vào giỏ hàng thành công!\n\n"
                    f"Dùng lệnh 'xem giỏ hàng' để kiểm tra."
                ),
                "node_durations": {"AddToCart": _ms(t0)},
            }

    return {
        "final_answer": "✅ Đã thêm vào giỏ hàng.",
        "node_durations": {"AddToCart": _ms(t0)},
    }


def _route_cart_intent(state: ShoppingState) -> str:
    """
    Route theo cart sub-intent:
    - view_cart: xem giỏ hàng
    - add_item: thêm sản phẩm
    """
    messages = state.get("messages", [])
    if not messages:
        return "view_cart"

    last_msg = messages[-1]
    text = (last_msg.content if hasattr(last_msg, "content") else str(last_msg)).lower()

    # Detect "xem giỏ hàng"
    view_keywords = ["xem giỏ", "giỏ hàng của", "trong giỏ", "check cart", "view cart", "giỏ trống không"]
    if any(kw in text for kw in view_keywords):
        return "view_cart"

    return "add_item"


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# CartWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_cart_workflow():
    """Tạo CartWorkflow subgraph (compiled)."""
    builder = StateGraph(ShoppingState)

    # ── Nodes ──
    builder.add_node("route_intent", lambda s: {})  # stateless router
    builder.add_node("get_cart", _get_cart_node)
    builder.add_node("check_product_id", _check_product_id)
    builder.add_node(
        "stock_check",
        ToolExecutor("check_cart_item_tool", args_builder=_stock_check_args_builder)
    )
    builder.add_node("out_of_stock", _handle_out_of_stock)
    builder.add_node("confirmation", ConfirmationNode(action_type="AddItem"))
    builder.add_node("denied", _handle_denied)
    builder.add_node(
        "add_to_cart",
        ToolExecutor("add_to_cart_tool", args_builder=_add_to_cart_args_builder)
    )
    builder.add_node("aggregate", _aggregate_add_to_cart)

    # ── Edges ──
    builder.add_edge(START, "route_intent")

    # Route: view_cart vs add_item
    builder.add_conditional_edges(
        "route_intent",
        _route_cart_intent,
        {
            "view_cart": "get_cart",
            "add_item": "check_product_id",
        }
    )

    builder.add_edge("get_cart", END)

    # Check product_id: found → stock_check, not found → out_of_stock
    builder.add_conditional_edges(
        "check_product_id",
        route_product_id_found,
        {
            "continue": "stock_check",
            "skip": "out_of_stock",
        }
    )

    # Stock check: in_stock vs out_of_stock
    builder.add_conditional_edges(
        "stock_check",
        route_stock_result,
        {
            "in_stock": "confirmation",
            "out_of_stock": "out_of_stock",
        }
    )

    builder.add_edge("out_of_stock", END)

    # Confirmation: confirmed/pending/denied
    builder.add_conditional_edges(
        "confirmation",
        route_confirmation,
        {
            "confirmed": "add_to_cart",
            "pending": END,    # Dừng lại, chờ user confirm qua /api/confirm
            "denied": "denied",
        }
    )

    builder.add_edge("denied", END)
    builder.add_edge("add_to_cart", "aggregate")
    builder.add_edge("aggregate", END)

    return builder.compile()
