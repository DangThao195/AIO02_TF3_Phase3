"""
graph/workflows/sequential.py — SequentialWorkflow subgraph.

Xử lý các request chứa nhiều intent cùng lúc, ví dụ:
  "Tìm iPhone 15 và thêm vào giỏ hàng"
  "Xem review rồi gợi ý sản phẩm tương tự"

Strategy (Phase 2):
  - Detect pending_workflows từ intent_source (đã được IntentClassifier set)
  - Chạy từng workflow tuần tự
  - Kết hợp kết quả vào final_answer

Phase 2 implementation: đơn giản — chạy 2 workflow bằng nested graph calls.
Phase 3: dùng Map-Reduce pattern.
"""

from __future__ import annotations

import time
import logging

from langgraph.graph import StateGraph, START, END

from src.graph.state import ShoppingState

logger = logging.getLogger("graph.workflows.sequential")


# ──────────────────────────────────────────────────────────────────
# SequentialWorkflow node
# ──────────────────────────────────────────────────────────────────

async def _sequential_dispatcher(state: ShoppingState) -> dict:
    """
    Chạy nhiều workflows tuần tự dựa trên pending_workflows.

    Phase 2: đơn giản — gọi từng workflow factory và invoke.
    Kết quả từng workflow được gộp vào workflow_results.
    """
    t0 = time.monotonic_ns()
    pending = state.get("pending_workflows", [])

    if not pending:
        # Fallback: parse từ intent + entities
        pending = _infer_workflows_from_state(state)

    if not pending:
        return {
            "final_answer": "Tôi không xác định được yêu cầu của bạn. Vui lòng thử lại.",
            "node_durations": {"Sequential": _ms(t0)},
        }

    logger.info("[SEQUENTIAL] Running workflows: %s", pending)

    results = []
    combined_answer_parts = []

    for workflow_name in pending:
        try:
            sub_result = await _run_single_workflow(workflow_name, state)
            answer = sub_result.get("final_answer", "")
            if answer:
                combined_answer_parts.append(answer)
            results.append({"workflow": workflow_name, "answer": answer})
            logger.info("[SEQUENTIAL] %s done | answer_len=%d", workflow_name, len(answer))
        except Exception as e:
            logger.error("[SEQUENTIAL] %s failed: %s", workflow_name, e)
            results.append({"workflow": workflow_name, "error": str(e)[:100]})

    # Kết hợp answers
    if len(combined_answer_parts) == 1:
        final_answer = combined_answer_parts[0]
    elif combined_answer_parts:
        sections = []
        for i, (wf, ans) in enumerate(zip(pending, combined_answer_parts)):
            sections.append(f"### {_workflow_display_name(wf)}\n{ans}")
        final_answer = "\n\n---\n\n".join(sections)
    else:
        final_answer = "Đã xử lý yêu cầu nhưng không có kết quả."

    return {
        "final_answer": final_answer,
        "workflow_results": results,
        "node_durations": {"Sequential": _ms(t0)},
    }


async def _run_single_workflow(workflow_name: str, state: ShoppingState) -> dict:
    """Gọi một workflow subgraph với state hiện tại."""
    from src.graph.workflows.search import create_search_workflow
    from src.graph.workflows.review import create_review_workflow
    from src.graph.workflows.recommend import create_recommend_workflow
    from src.graph.workflows.cart import create_cart_workflow
    from src.graph.workflows.shipping import create_shipping_workflow

    _WORKFLOW_FACTORIES = {
        "search":    create_search_workflow,
        "review":    create_review_workflow,
        "recommend": create_recommend_workflow,
        "cart":      create_cart_workflow,
        "shipping":  create_shipping_workflow,
    }

    factory = _WORKFLOW_FACTORIES.get(workflow_name)
    if factory is None:
        raise ValueError(f"Unknown workflow: {workflow_name}")

    workflow = factory()
    result = await workflow.ainvoke(state)
    return result


def _infer_workflows_from_state(state: ShoppingState) -> list[str]:
    """
    Infer danh sách workflows từ tin nhắn khi pending_workflows chưa được set.
    Simple keyword matching cho Phase 2.
    """
    messages = state.get("messages", [])
    if not messages:
        return []

    last_msg = messages[-1]
    text = (last_msg.content if hasattr(last_msg, "content") else str(last_msg)).lower()

    workflows = []

    keyword_map = {
        "search":    ["tìm", "search", "find", "giá"],
        "review":    ["review", "đánh giá", "nhận xét"],
        "recommend": ["gợi ý", "recommend", "tương tự"],
        "cart":      ["giỏ", "cart", "thêm", "mua"],
        "shipping":  ["giao hàng", "ship", "vận chuyển"],
    }

    for wf, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            workflows.append(wf)

    # Giới hạn 2 workflow (tránh quá nhiều tool calls)
    return workflows[:2]


def _workflow_display_name(wf: str) -> str:
    names = {
        "search":    "🔍 Kết quả tìm kiếm",
        "review":    "⭐ Đánh giá",
        "recommend": "🎯 Gợi ý",
        "cart":      "🛒 Giỏ hàng",
        "shipping":  "🚚 Vận chuyển",
    }
    return names.get(wf, wf.capitalize())


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


# ──────────────────────────────────────────────────────────────────
# SequentialWorkflow subgraph factory
# ──────────────────────────────────────────────────────────────────

def create_sequential_workflow():
    """Tạo SequentialWorkflow subgraph (compiled)."""
    builder = StateGraph(ShoppingState)

    builder.add_node("dispatcher", _sequential_dispatcher)

    builder.add_edge(START, "dispatcher")
    builder.add_edge("dispatcher", END)

    return builder.compile()
