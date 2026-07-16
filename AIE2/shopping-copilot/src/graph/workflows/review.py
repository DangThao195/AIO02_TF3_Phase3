"""
graph/workflows/review.py — ReviewWorkflow subgraph.

Flow:
  START
    ↓
  check_product_id   ← kiểm tra current_product_id từ state (đã resolve tập trung)
    ↓ (conditional: found/not_found)
  found → get_reviews  ← get_product_reviews_tool
        → aggregate    ← format reviews → final_answer
  not_found → END (final_answer = "Không tìm thấy sản phẩm")
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
from src.graph.edges import route_product_id_found

if TYPE_CHECKING:
    pass

logger = logging.getLogger("graph.workflows.review")


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


def _reviews_args_builder(state: ShoppingState) -> dict:
    """Build args cho get_product_reviews_tool."""
    product_id = state.get("current_product_id", "")
    return {"product_id": product_id} if product_id else {}


async def _handle_not_found(state: ShoppingState) -> dict:
    """Xử lý khi không tìm thấy product_id."""
    entities = state.get("entities", {})
    product_name = entities.get("product_name", "sản phẩm này")
    resolved_name = state.get("resolved_product_name") or product_name
    return {
        "final_answer": (
            f"❌ Không tìm thấy sản phẩm **{resolved_name}** trong hệ thống. "
            f"Vui lòng kiểm tra lại tên sản phẩm."
        ),
    }


async def _aggregate_reviews(state: ShoppingState) -> dict:
    """
    Parse và format reviews thành final_answer.
    """
    t0 = time.monotonic_ns()
    tool_results = state.get("tool_results", {})
    entities = state.get("entities", {})
    product_name = entities.get("product_name", "sản phẩm")

    # Tìm kết quả reviews
    reviews_raw = None
    for key, val in tool_results.items():
        if key.startswith("get_product_reviews_tool:"):
            reviews_raw = val.get("result")
            # Nếu direct flag (truthfulness guard đã set final_answer)
            if val.get("direct"):
                return {"node_durations": {"AggregateReviews": _ms(t0)}}
            break

    if reviews_raw is None:
        return {
            "final_answer": f"Không có đánh giá nào cho **{product_name}**.",
            "node_durations": {"AggregateReviews": _ms(t0)},
        }

    # Parse JSON nếu cần
    reviews = []
    if isinstance(reviews_raw, str):
        try:
            data = json.loads(reviews_raw)
            reviews = data if isinstance(data, list) else data.get("reviews", [])
        except Exception:
            # Plain text response
            return {
                "final_answer": f"**Đánh giá về {product_name}:**\n\n{reviews_raw[:1000]}",
                "node_durations": {"AggregateReviews": _ms(t0)},
            }
    elif isinstance(reviews_raw, list):
        reviews = reviews_raw
    elif isinstance(reviews_raw, dict):
        reviews = reviews_raw.get("reviews", [])

    if not reviews:
        return {
            "final_answer": f"Chưa có đánh giá nào cho **{product_name}**.",
            "node_durations": {"AggregateReviews": _ms(t0)},
        }

    # Format reviews
    lines = [f"### Đánh giá về **{product_name}** ({len(reviews)} đánh giá)\n"]
    total_rating = 0
    count = 0

    for i, r in enumerate(reviews[:5], 1):
        if isinstance(r, dict):
            rating = r.get("rating", r.get("score", 0))
            comment = r.get("comment", r.get("text", r.get("review", str(r))))
            user = r.get("user", r.get("reviewer", "Người dùng ẩn danh"))
            stars = "⭐" * min(int(rating), 5) if rating else ""
            lines.append(f"**{i}. {user}** {stars}")
            lines.append(f"> {str(comment)[:300]}\n")
            if rating:
                total_rating += float(rating)
                count += 1
        else:
            lines.append(f"**{i}.** {str(r)[:200]}\n")

    if count > 0:
        avg = total_rating / count
        lines.insert(1, f"*Điểm trung bình: ⭐ {avg:.1f}/5*\n")

    return {
        "final_answer": "\n".join(lines),
        "node_durations": {"AggregateReviews": _ms(t0)},
    }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# ReviewWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_review_workflow():
    """
    Tạo ReviewWorkflow subgraph (compiled).

    Nodes:
      get_product_id  — lookup product_id
      not_found       — trả lỗi nếu không tìm thấy
      get_reviews     — gọi get_product_reviews_tool
      aggregate       — format reviews → final_answer
    """
    builder = StateGraph(ShoppingState)

    builder.add_node("check_product_id", _check_product_id)
    builder.add_node("not_found", _handle_not_found)
    builder.add_node(
        "get_reviews",
        ToolExecutor("get_product_reviews_tool", args_builder=_reviews_args_builder)
    )
    builder.add_node("aggregate", _aggregate_reviews)

    # ── Edges ──
    builder.add_edge(START, "check_product_id")

    builder.add_conditional_edges(
        "check_product_id",
        route_product_id_found,
        {
            "continue": "get_reviews",
            "skip": "not_found",
        }
    )

    builder.add_edge("not_found", END)
    builder.add_edge("get_reviews", "aggregate")
    builder.add_edge("aggregate", END)

    return builder.compile()
