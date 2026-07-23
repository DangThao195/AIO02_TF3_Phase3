"""
graph/state.py — ShoppingState v3.2

TypedDict state cho LangGraph StateGraph.
Tất cả fields dùng total=False (optional) để LangGraph merge partial updates.

Reducers:
    - merge_tool_results: chỉ nhận key chưa tồn tại (idempotent)
    - accumulate_errors: append list
    - accumulate_tool_history: append, giới hạn 6 turns
    - merge_node_durations: cộng dồn ms theo node
"""

from __future__ import annotations

from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage


# ── Reducers ────────────────────────────────────────────────────

def merge_tool_results(existing: dict, update: dict) -> dict:
    """
    Merge tool_results: reset khi __reset__ flag, giữ nguyên key cũ nếu không có key mới.
    __reset__ được dùng để clear state giữa các turn (từ main.py api_chat).
    """
    if not existing:
        result = dict(update)
    elif "__reset__" in update:
        result = {k: v for k, v in update.items() if k != "__reset__"}
    else:
        result = dict(existing)
        for k, v in update.items():
            result[k] = v
    return {k: v for k, v in result.items() if not k.startswith("__")}


def accumulate_errors(existing: list, update: Any) -> list:
    """
    Append errors. update có thể là list hoặc dict đơn lẻ.
    __reset__ trong list sẽ clear toàn bộ errors (cho turn mới).
    """
    if isinstance(update, list) and "__reset__" in update:
        return []
    if not existing:
        existing = []
    if isinstance(update, list):
        return existing + update
    elif isinstance(update, dict):
        return existing + [update]
    return existing


def accumulate_tool_history(existing: list, update: Any) -> list:
    """
    Append tool history, giới hạn 6 turns gần nhất.
    """
    if not existing:
        existing = []
    if isinstance(update, list):
        combined = existing + update
    elif isinstance(update, dict):
        combined = existing + [update]
    else:
        return existing
    return combined[-6:]


def merge_node_durations(existing: dict, update: dict) -> dict:
    """
    Merge node_durations: cộng dồn ms theo node key trong cùng turn.
    __reset__ flag sẽ clear toàn bộ durations (cho turn mới).
    """
    if "__reset__" in update:
        return {}
    if not existing:
        return dict(update)
    merged = dict(existing)
    for k, v in update.items():
        merged[k] = merged.get(k, 0) + v
    return merged


def _last_wins(existing: Any, update: Any) -> Any:
    """Simple last-write-wins reducer cho các field thông thường."""
    return update if update is not None else existing


# ── ShoppingState v3.2 ────────────────────────────────────────────

class ShoppingState(TypedDict, total=False):
    """
    State cho Shopping Copilot v3.2 LangGraph.

    Tất cả fields optional (total=False) — LangGraph merge partial dicts.
    Annotated fields có reducers đặc biệt; còn lại dùng last-write-wins.
    """

    # ── Conversation ──────────────────────────────────────────────
    messages: list[BaseMessage]         # Chat history (LangGraph quản lý)
    session_id: str
    user_id: str
    trace_id: str

    # ── Planner fields ────────────────────────────────────────────
    plan: dict                          # DAGPlan: {nodes: [...], edges: [...]}
    plan_step_index: int
    current_goal: str
    planner_reasoning: str
    plan_confidence: float              # 0.0–1.0
    entities: dict                      # Extracted entities from input (product_name, category, price)

    # ── Tool Execution fields ─────────────────────────────────────
    tool_results: Annotated[dict, merge_tool_results]
    tool_history: Annotated[list, accumulate_tool_history]
    dependency_graph: dict
    retry_count: int

    # ── Response / Hallucination fields ──────────────────────────
    complexity_score: float             # 0.0–1.0
    final_answer: str
    groundedness_score: float           # 0.0–1.0
    hallucination_detected: bool
    fallback_used: bool

    # ── Gate fields ───────────────────────────────────────────────
    gate_decisions: dict                # {gate_name: {decision, reason}}
    semantic_hallucination_detected: bool
    replan_count: int

    # ── Reflection fields ─────────────────────────────────────────
    reflection_result: str              # "pass" | "replan"
    reflection_issues: list             # danh sách vấn đề phát hiện

    # ── Planner Memory (cross-turn context) ───────────────────────
    planner_memory: dict
    # planner_memory schema:
    #   last_search: str           — query lần tìm kiếm trước
    #   last_product_id: str       — product_id sản phẩm vừa xem
    #   last_product_name: str     — tên sản phẩm vừa xem
    #   last_results_ids: list     — list[str] top 5 IDs từ search
    #   mentioned_products: list   — tất cả product_id đã mention
    #   current_cart_items: int    — số lượng item trong giỏ
    #   last_goal: str             — mục tiêu của lượt trước

    # ── Confirmation / Write flow ──────────────────────────────────
    pending_action: Optional[dict]      # {action, params, token, message}
    confirmed: bool

    # ── Guardrails ────────────────────────────────────────────────
    guardrail_violations: list          # [{type, detail, tier}]

    # ── Observability ─────────────────────────────────────────────
    errors: Annotated[list, accumulate_errors]
    node_durations: Annotated[dict, merge_node_durations]
