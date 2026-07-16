"""
graph/workflows/recommend.py — RecommendWorkflow subgraph.

Flow:
  START
    ↓
  check_product_id   ← kiểm tra current_product_id từ state (đã resolve tập trung)
    ↓ (conditional: found/not_found)
  found → get_recommendations  ← get_recommendations_tool
        → aggregate            ← format → final_answer
  not_found → search_fallback  ← tìm kiếm thay thế
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
from src.graph.edges import route_product_id_found

logger = logging.getLogger("graph.workflows.recommend")


# ──────────────────────────────────────────────────────────────────
# Helper nodes
# ──────────────────────────────────────────────────────────────────

def _check_product_id(state: ShoppingState) -> dict:
    """
    Kiểm tra current_product_id đã được resolve từ main graph.
    current_product_id đã được set bởi ResolveProductNode.
    Conditional edge route_product_id_found sẽ quyết định continue/skip.
    """
    return {}


def _recommend_args_builder(state: ShoppingState) -> dict:
    """Build args cho get_recommendations_tool."""
    product_id = state.get("current_product_id", "")
    return {"product_id": product_id} if product_id else {}


async def _search_fallback_for_recommend(state: ShoppingState) -> dict:
    """
    Khi không tìm được product_id → thử search trực tiếp (fallback).
    """
    t0 = time.monotonic_ns()
    entities = state.get("entities", {})
    product_name = entities.get("product_name", entities.get("category", ""))

    if not product_name:
        return {
            "final_answer": "Vui lòng cho tôi biết bạn muốn gợi ý sản phẩm nào?",
        }

    from src.tools import search_products_v2
    try:
        result = await search_products_v2.ainvoke({"query": product_name})
        raw = result if isinstance(result, str) else json.dumps(result)
        try:
            data = json.loads(raw)
            products = data.get("products", [])
        except Exception:
            products = []

        if not products:
            return {
                "final_answer": f"Không tìm thấy sản phẩm **{product_name}** để gợi ý.",
            }

        lines = [f"Không tìm thấy chính xác **{product_name}**, nhưng đây là một số sản phẩm tương tự:"]
        for i, p in enumerate(products[:5], 1):
            name = p.get("name", "Unknown")
            desc = p.get("description", "")[:100]
            lines.append(f"{i}. **{name}**" + (f" — {desc}" if desc else ""))

        return {"final_answer": "\n".join(lines)}
    except Exception as e:
        logger.error("[RECOMMEND] Search fallback error: %s", e)
        return {
            "final_answer": f"Không thể tìm gợi ý cho **{product_name}** lúc này.",
        }


async def _aggregate_recommendations(state: ShoppingState) -> dict:
    """Format recommendations thành final_answer."""
    t0 = time.monotonic_ns()
    tool_results = state.get("tool_results", {})
    entities = state.get("entities", {})
    product_name = entities.get("product_name", "sản phẩm")

    # Tìm kết quả recommendations
    recs_raw = None
    for key, val in tool_results.items():
        if key.startswith("get_recommendations_tool:"):
            recs_raw = val.get("result")
            if val.get("direct"):
                return {"node_durations": {"AggregateRecommend": _ms(t0)}}
            break

    if recs_raw is None:
        return {
            "final_answer": f"Không tìm thấy gợi ý nào cho **{product_name}**.",
            "node_durations": {"AggregateRecommend": _ms(t0)},
        }

    # Parse JSON
    recommendations = []
    if isinstance(recs_raw, str):
        try:
            data = json.loads(recs_raw)
            recommendations = data if isinstance(data, list) else data.get("products", data.get("recommendations", []))
        except Exception:
            return {
                "final_answer": f"**Gợi ý cho {product_name}:**\n\n{recs_raw[:800]}",
                "node_durations": {"AggregateRecommend": _ms(t0)},
            }
    elif isinstance(recs_raw, list):
        recommendations = recs_raw

    if not recommendations:
        return {
            "final_answer": f"Chưa có gợi ý nào cho **{product_name}**.",
            "node_durations": {"AggregateRecommend": _ms(t0)},
        }

    lines = [f"### 🎯 Sản phẩm gợi ý dựa trên **{product_name}**\n"]
    for i, p in enumerate(recommendations[:5], 1):
        if isinstance(p, dict):
            name = p.get("name", "Unknown")
            price_units = p.get("price_units", 0)
            price_nanos = p.get("price_nanos", 0)
            price = f"${price_units}.{price_nanos // 10_000_000:02d}" if (price_units or price_nanos) else "Liên hệ"
            desc = p.get("description", "")[:150]
            lines.append(f"**{i}. {name}** — {price}")
            if desc:
                lines.append(f"   _{desc}_")
            lines.append("")
        else:
            lines.append(f"**{i}.** {str(p)[:200]}")

    return {
        "final_answer": "\n".join(lines),
        "node_durations": {"AggregateRecommend": _ms(t0)},
    }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# RecommendWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_recommend_workflow():
    """Tạo RecommendWorkflow subgraph (compiled)."""
    builder = StateGraph(ShoppingState)

    builder.add_node("check_product_id", _check_product_id)
    builder.add_node("search_fallback", _search_fallback_for_recommend)
    builder.add_node(
        "get_recommendations",
        ToolExecutor("get_recommendations_tool", args_builder=_recommend_args_builder)
    )
    builder.add_node("aggregate", _aggregate_recommendations)

    builder.add_edge(START, "check_product_id")

    builder.add_conditional_edges(
        "check_product_id",
        route_product_id_found,
        {
            "continue": "get_recommendations",
            "skip": "search_fallback",
        }
    )

    builder.add_edge("search_fallback", END)
    builder.add_edge("get_recommendations", "aggregate")
    builder.add_edge("aggregate", END)

    return builder.compile()
