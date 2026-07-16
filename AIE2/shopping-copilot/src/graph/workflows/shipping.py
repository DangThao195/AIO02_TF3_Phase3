"""
graph/workflows/shipping.py — ShippingWorkflow subgraph.

Flow:
  START
    ↓
  route_shipping   ← xác định sub-intent (currency_only / shipping_quote)
    ↓ (conditional)
  currency_only → END (convert currency)
  shipping_quote → get_currency → get_quote → aggregate → END

current_product_id đã được resolve tập trung bởi ResolveProductNode
trước khi workflow này chạy.

"""

from __future__ import annotations

import json
import time
import logging

from langgraph.graph import StateGraph, START, END

from src.graph.state import ShoppingState
from src.graph.nodes.tool_executor import ToolExecutor

logger = logging.getLogger("graph.workflows.shipping")


# ──────────────────────────────────────────────────────────────────
# Helper nodes
# ──────────────────────────────────────────────────────────────────

def _currency_args_builder(state: ShoppingState) -> dict:
    """Build args cho convert_currency_tool."""
    entities = state.get("entities", {})
    return {
        "from_currency": "USD",
        "to_currency": entities.get("currency", "VND"),
        "amount": entities.get("amount", 1.0),
    }


def _shipping_args_builder(state: ShoppingState) -> dict:
    """Build args cho get_shipping_quote_tool."""
    entities = state.get("entities", {})
    product_id = state.get("current_product_id", "")
    args: dict = {}
    if product_id:
        args["product_id"] = product_id
    if entities.get("destination"):
        args["destination"] = entities["destination"]
    if entities.get("quantity"):
        args["quantity"] = entities["quantity"]
    return args


async def _route_shipping_intent(state: ShoppingState) -> str:
    """Xác định sub-intent: currency_only hay shipping_quote."""
    entities = state.get("entities", {})
    messages = state.get("messages", [])
    last_msg = messages[-1].content if messages else ""

    # Chỉ convert currency (không hỏi shipping)
    currency_keywords = ["quy đổi", "convert", "đổi tiền", "tỷ giá", "exchange rate"]
    if entities.get("currency") and any(kw in last_msg.lower() for kw in currency_keywords):
        return "currency_only"

    return "shipping_quote"


async def _currency_only_node(state: ShoppingState) -> dict:
    """Chỉ quy đổi tiền tệ, không hỏi shipping."""
    t0 = time.monotonic_ns()
    entities = state.get("entities", {})
    currency = entities.get("currency", "VND")
    amount = entities.get("amount", 1.0)

    from src.tools import convert_currency_tool
    try:
        result = await convert_currency_tool.ainvoke({
            "from_currency": "USD",
            "to_currency": currency,
            "amount": amount,
        })
        return {
            "final_answer": str(result)[:500],
            "node_durations": {"CurrencyOnly": _ms(t0)},
        }
    except Exception as e:
        return {
            "final_answer": f"Không thể quy đổi tỷ giá lúc này: {str(e)[:100]}",
            "node_durations": {"CurrencyOnly": _ms(t0)},
        }


async def _aggregate_shipping(state: ShoppingState) -> dict:
    """Format shipping quote + currency thành final_answer."""
    t0 = time.monotonic_ns()
    tool_results = state.get("tool_results", {})
    entities = state.get("entities", {})
    product_name = entities.get("product_name", "sản phẩm")

    # Tìm shipping quote
    shipping_raw = None
    currency_raw = None
    for key, val in tool_results.items():
        if key.startswith("get_shipping_quote_tool:"):
            shipping_raw = val.get("result")
        elif key.startswith("convert_currency_tool:"):
            currency_raw = val.get("result")

    lines = [f"### 🚚 Thông tin vận chuyển cho **{product_name}**\n"]

    if shipping_raw:
        if isinstance(shipping_raw, str):
            try:
                data = json.loads(shipping_raw)
                fee = data.get("shipping_fee", data.get("fee", ""))
                eta = data.get("estimated_days", data.get("eta", ""))
                carrier = data.get("carrier", "")
                if fee:
                    lines.append(f"**Phí ship:** {fee}")
                if eta:
                    lines.append(f"**Thời gian giao:** {eta} ngày")
                if carrier:
                    lines.append(f"**Đơn vị vận chuyển:** {carrier}")
            except Exception:
                lines.append(shipping_raw[:300])
        else:
            lines.append(str(shipping_raw)[:300])
    else:
        lines.append("_(Không có thông tin phí vận chuyển)_")

    if currency_raw:
        lines.append(f"\n**Tỷ giá:** {str(currency_raw)[:200]}")

    return {
        "final_answer": "\n".join(lines),
        "node_durations": {"AggregateShipping": _ms(t0)},
    }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# ShippingWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_shipping_workflow():
    """Tạo ShippingWorkflow subgraph (compiled)."""
    builder = StateGraph(ShoppingState)

    # current_product_id đã được resolve bởi ResolveProductNode trong main graph
    # Không cần GetProductIDNode ở đây nữa

    builder.add_node("currency_only", _currency_only_node)
    builder.add_node(
        "get_currency",
        ToolExecutor("convert_currency_tool", args_builder=_currency_args_builder)
    )
    builder.add_node(
        "get_quote",
        ToolExecutor("get_shipping_quote_tool", args_builder=_shipping_args_builder)
    )
    builder.add_node("aggregate", _aggregate_shipping)

    # ── Edges ──
    builder.add_conditional_edges(
        START,
        _route_shipping_intent,
        {
            "currency_only": "currency_only",
            "shipping_quote": "get_currency",  # convert currency trước, rồi get quote
        }
    )

    builder.add_edge("currency_only", END)
    builder.add_edge("get_currency", "get_quote")
    builder.add_edge("get_quote", "aggregate")
    builder.add_edge("aggregate", END)

    return builder.compile()
