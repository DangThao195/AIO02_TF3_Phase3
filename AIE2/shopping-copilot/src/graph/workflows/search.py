"""
graph/workflows/search.py — SearchWorkflow subgraph.

Flow:
  START
    ↓
  search_products   ← search_products_v2 tool
    ↓ (conditional: zero/one/many results)
  zero → semantic_search  ← fallback: bỏ filter, tìm rộng hơn
  one  → END              ← đủ kết quả
  many → ask_user         ← hỏi user chọn (Phase 1: tự chọn top result)
    ↓
  aggregate               ← format kết quả vào final_answer
    ↓
  END

"""

from __future__ import annotations

import json
import time
import logging
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, START, END

from src.graph.state import ShoppingState
from src.graph.nodes.tool_executor import ToolExecutor
from src.graph.edges import route_search_results

if TYPE_CHECKING:
    pass

logger = logging.getLogger("graph.workflows.search")


# ──────────────────────────────────────────────────────────────────
# Helper nodes
# ──────────────────────────────────────────────────────────────────

def _search_args_builder(state: ShoppingState) -> dict:
    """Build args cho search_products_v2 từ state."""
    entities = state.get("entities", {})
    args: dict = {}

    product_name = entities.get("product_name", "")
    category = entities.get("category", "")

    # Ưu tiên product_name, fallback sang category, fallback raw message
    query = product_name or category
    if not query:
        messages = state.get("messages", [])
        for msg in reversed(messages):
            text = msg.content if hasattr(msg, "content") else str(msg)
            if isinstance(text, str) and text.strip():
                query = text.strip()
                break

    if query:
        args["query"] = query

    if entities.get("price_min") is not None:
        args["price_min"] = entities["price_min"]
    if entities.get("price_max") is not None:
        args["price_max"] = entities["price_max"]

    return args


async def _parse_search_results(state: ShoppingState) -> dict:
    """
    Parse tool_results từ search_products node,
    populate candidate_products cho conditional edge.
    """
    t0 = time.monotonic_ns()
    tool_results = state.get("tool_results", {})

    # Tìm kết quả search_products_v2 mới nhất
    search_result = None
    for key, val in tool_results.items():
        if key.startswith("search_products_v2:"):
            search_result = val
            break

    if not search_result:
        return {
            "candidate_products": [],
            "node_durations": {"ParseSearch": _ms(t0)},
        }

    raw = search_result.get("result", "")
    products = []

    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                products = data.get("products", [])
                if not products and data.get("status") == "category":
                    # Kết quả là danh mục, không phải sản phẩm cụ thể
                    cats = data.get("categories", [])
                    # Encode categories như "products" để flow tiếp tục
                    products = [{"name": c, "type": "category"} for c in cats]
            elif isinstance(data, list):
                products = data
        except (json.JSONDecodeError, AttributeError):
            # Raw string không phải JSON → giữ nguyên, 1 "result"
            if raw and "không tìm thấy" not in raw.lower():
                products = [{"name": "result", "description": raw}]
    elif isinstance(raw, dict):
        products = raw.get("products", [])
    elif isinstance(raw, list):
        products = raw

    return {
        "candidate_products": products,
        "node_durations": {"ParseSearch": _ms(t0)},
    }


async def _semantic_search_fallback(state: ShoppingState) -> dict:
    """
    Fallback khi search chính trả 0 results.
    Tìm rộng hơn: bỏ filter giá, dùng query ngắn hơn.
    """
    t0 = time.monotonic_ns()
    entities = state.get("entities", {})
    product_name = entities.get("product_name", entities.get("category", ""))

    # Fallback sang raw message nếu entities rỗng
    if not product_name:
        messages = state.get("messages", [])
        for msg in reversed(messages):
            text = msg.content if hasattr(msg, "content") else str(msg)
            if isinstance(text, str) and text.strip():
                product_name = text.strip()
                break

    logger.info("[SEARCH] Semantic fallback | query=%s", product_name)

    if not product_name:
        return {
            "final_answer": "Không tìm thấy sản phẩm nào phù hợp với yêu cầu của bạn.",
            "node_durations": {"SemanticSearch": _ms(t0)},
        }

    from src.tools import search_products_v2
    try:
        # Tìm rộng hơn: chỉ dùng query, bỏ giá
        result = await search_products_v2.ainvoke({"query": product_name})

        raw = result if isinstance(result, str) else json.dumps(result)
        try:
            data = json.loads(raw)
            products = data.get("products", [])
        except Exception:
            products = []

        if not products:
            answer = f"Xin lỗi, không tìm thấy sản phẩm nào liên quan đến **{product_name}**."
        else:
            lines = [f"Tôi không tìm thấy kết quả chính xác, nhưng có một số sản phẩm tương tự:"]
            for i, p in enumerate(products[:5], 1):
                name = p.get("name", "Unknown")
                price = _format_price(p)
                lines.append(f"{i}. **{name}** — {price}")
            answer = "\n".join(lines)

        return {
            "candidate_products": products[:5],
            "final_answer": answer,
            "node_durations": {"SemanticSearch": _ms(t0)},
        }
    except Exception as e:
        logger.error("[SEARCH] Semantic fallback error: %s", e)
        return {
            "final_answer": f"Không tìm thấy sản phẩm '{product_name}'.",
            "node_durations": {"SemanticSearch": _ms(t0)},
        }


async def _aggregate_search_results(state: ShoppingState) -> dict:
    """
    Format danh sách candidate_products thành final_answer markdown.
    """
    t0 = time.monotonic_ns()
    products = state.get("candidate_products", [])
    entities = state.get("entities", {})
    query = entities.get("product_name", entities.get("category", ""))

    if not products:
        return {
            "final_answer": "Không tìm thấy sản phẩm phù hợp.",
            "node_durations": {"AggregateSearch": _ms(t0)},
        }

    # Nếu chỉ 1 sản phẩm
    if len(products) == 1:
        p = products[0]
        name = p.get("name", "Unknown")
        price = _format_price(p)
        desc = p.get("description", "")
        answer = f"### {name}\n**Giá:** {price}"
        if desc:
            answer += f"\n\n{desc[:300]}"
        return {
            "final_answer": answer,
            "node_durations": {"AggregateSearch": _ms(t0)},
        }

    # Nhiều sản phẩm
    lines = [f"Tìm thấy **{len(products)}** sản phẩm" + (f" cho '{query}'" if query else "") + ":"]
    for i, p in enumerate(products[:10], 1):
        name = p.get("name", "Unknown")
        price = _format_price(p)
        lines.append(f"{i}. **{name}** — {price}")

    return {
        "final_answer": "\n".join(lines),
        "node_durations": {"AggregateSearch": _ms(t0)},
    }


def _format_price(product: dict) -> str:
    """Format giá từ product dict."""
    units = product.get("price_units", 0)
    nanos = product.get("price_nanos", 0)
    if units or nanos:
        return f"${units}.{nanos // 10_000_000:02d}"
    raw_price = product.get("price", 0)
    if isinstance(raw_price, (int, float)) and raw_price > 0:
        return f"${raw_price:.2f}"
    return "Liên hệ"


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# SearchWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_search_workflow():
    """
    Tạo SearchWorkflow subgraph (compiled).

    Nodes:
      search_products  — gọi search_products_v2 tool
      parse_results    — parse JSON, set candidate_products
      semantic_search  — fallback khi 0 results
      aggregate        — format kết quả → final_answer

    Conditional edges dựa trên số candidate_products.
    """
    builder = StateGraph(ShoppingState)

    # ── Nodes ──
    builder.add_node(
        "search_products",
        ToolExecutor("search_products_v2", args_builder=_search_args_builder)
    )
    builder.add_node("parse_results", _parse_search_results)
    builder.add_node("semantic_search", _semantic_search_fallback)
    builder.add_node("aggregate", _aggregate_search_results)

    # ── Edges ──
    builder.add_edge(START, "search_products")
    builder.add_edge("search_products", "parse_results")

    # Conditional: dựa trên candidate_products count
    builder.add_conditional_edges(
        "parse_results",
        route_search_results,
        {
            "zero": "semantic_search",  # 0 results → fallback
            "one":  "aggregate",        # 1 result → aggregate trực tiếp
            "many": "aggregate",        # N results → aggregate (hiển thị danh sách)
        }
    )

    builder.add_edge("semantic_search", END)
    builder.add_edge("aggregate", END)

    return builder.compile()
