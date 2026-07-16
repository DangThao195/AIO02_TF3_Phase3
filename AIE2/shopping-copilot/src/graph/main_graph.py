"""
graph/main_graph.py — Main LangGraph StateGraph builder.

build_graph() tạo và compile graph với:
  - InputGuard node (L1 + L2a + L2b)
  - IntentClassifier + EntityExtractor
  - Router node
  - 7 workflow subgraphs (search, review, recommend, cart, shipping, agent, sequential)
  - AnswerGenerator node (L5 + format)

Xem thiết kế đầy đủ: docs/design/langgraph_design.md
"""

from __future__ import annotations

import os
import time
import logging
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.graph.state import ShoppingState
from src.graph.nodes.input_guard import InputGuard
from src.graph.nodes.router import Router
from src.graph.nodes.intent_classifier import IntentClassifier
from src.graph.nodes.entity_extractor import EntityExtractor
from src.graph.nodes.resolve_product import ResolveProductNode
from src.graph.nodes.response_editor import ResponseEditor
from src.graph.nodes.answer_generator import AnswerGenerator
from src.graph.edges import (
    route_after_input_guard,
    route_to_workflow,
)
from src.graph.workflows.agent import create_agent_workflow
from src.graph.workflows.search import create_search_workflow
from src.graph.workflows.review import create_review_workflow
from src.graph.workflows.recommend import create_recommend_workflow
from src.graph.workflows.cart import create_cart_workflow
from src.graph.workflows.shipping import create_shipping_workflow
from src.graph.workflows.sequential import create_sequential_workflow

if TYPE_CHECKING:
    pass

logger = logging.getLogger("graph.main_graph")


# ──────────────────────────────────────────────────────────────────
# build_graph()
# ──────────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Tạo và compile main LangGraph StateGraph.

    Returns:
        Compiled graph (CompiledStateGraph) với MemorySaver checkpointer.
        Dùng graph.ainvoke(inputs, config={"configurable": {"thread_id": session_id}}).
    """
    builder = StateGraph(ShoppingState)

    # ── Phase 2: Real nodes ──
    builder.add_node("input_guard", InputGuard())
    builder.add_node("intent_classifier", IntentClassifier())
    builder.add_node("entity_extractor", EntityExtractor())
    builder.add_node("resolve_product", ResolveProductNode())
    builder.add_node("router", Router())
    builder.add_node("response_editor", ResponseEditor())
    builder.add_node("answer_generator", AnswerGenerator())

    # ── Workflow nodes ──
    builder.add_node("agent_workflow", create_agent_workflow())
    builder.add_node("search_workflow", create_search_workflow())
    builder.add_node("review_workflow", create_review_workflow())
    builder.add_node("recommend_workflow", create_recommend_workflow())
    builder.add_node("cart_workflow", create_cart_workflow())
    builder.add_node("shipping_workflow", create_shipping_workflow())
    builder.add_node("sequential_workflow", create_sequential_workflow())

    # ── Edges ──
    builder.add_edge(START, "input_guard")

    # InputGuard: nếu có violation → kết thúc ngay (final_answer đã có trong state)
    builder.add_conditional_edges(
        "input_guard",
        route_after_input_guard,
        {
            "blocked": "response_editor",  # final_answer đã có trong state
            "pass": "intent_classifier",
        }
    )

    builder.add_edge("intent_classifier", "entity_extractor")
    builder.add_edge("entity_extractor", "resolve_product")
    builder.add_edge("resolve_product", "router")

    # Router → workflow (Phase 2: tất cả workflows sẵn sàng)
    builder.add_conditional_edges(
        "router",
        route_to_workflow,
        {
            "agent":      "agent_workflow",
            "search":     "search_workflow",
            "review":     "review_workflow",
            "recommend":  "recommend_workflow",
            "cart":       "cart_workflow",
            "shipping":   "shipping_workflow",
            "sequential": "sequential_workflow",
        }
    )

    # Tất cả workflows → response_editor → answer_generator
    _all_workflows = [
        "agent_workflow",
        "search_workflow",
        "review_workflow",
        "recommend_workflow",
        "cart_workflow",
        "shipping_workflow",
        "sequential_workflow",
    ]
    for wf in _all_workflows:
        builder.add_edge(wf, "response_editor")

    builder.add_edge("response_editor", "answer_generator")
    builder.add_edge("answer_generator", END)

    # Blocked path (input guard violation) → vẫn qua response_editor
    # để đảm bảo luồng đồng nhất

    # ── Compile với MemorySaver checkpoint ──
    # MemorySaver: in-memory checkpoint cho Phase 1-2
    # Phase 3 production: chuyển sang PostgresSaver
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    logger.info("[MAIN_GRAPH] Graph compiled (Phase 3 — Pure LangGraph)")
    return graph
