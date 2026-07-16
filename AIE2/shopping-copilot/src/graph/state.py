"""
graph/state.py — ShoppingState TypedDict cho LangGraph StateGraph.

State được chia sẻ qua tất cả nodes trong graph.
Dùng Annotated reducers để LangGraph tự merge các field list/dict.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# ──────────────────────────────────────────────────────────────────
# Reducer functions
# ──────────────────────────────────────────────────────────────────

def merge_tool_results(
    existing: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Reducer: merge tool_results dict, không ghi đè kết quả đã có."""
    result = existing.copy()
    for k, v in updates.items():
        if k not in result:  # Chỉ nhận kết quả đầu tiên cho mỗi call_id
            result[k] = v
    return result


def accumulate_errors(existing: list, updates: list) -> list:
    """Reducer: append errors vào danh sách hiện có."""
    return existing + updates


def merge_node_durations(existing: dict, updates: dict) -> dict:
    """Reducer: merge node duration dict (cộng dồn nếu node chạy lại)."""
    result = existing.copy()
    for node, ms in updates.items():
        result[node] = result.get(node, 0) + ms
    return result


# ──────────────────────────────────────────────────────────────────
# ShoppingState
# ──────────────────────────────────────────────────────────────────

class ShoppingState(TypedDict, total=False):
    """
    State chia sẻ toàn bộ LangGraph cho Shopping Copilot.

    Dùng total=False để cho phép khởi tạo partial state (không cần
    khai báo tất cả fields khi invoke).
    """

    # ── Core message history ──
    # add_messages reducer tự merge, không ghi đè
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Intent & Entities ──
    intent: str           # search | review | recommend | cart | shipping | sequential | agent
    intent_source: str    # regex | llm | default
    entities: dict        # {"product_name": "iPhone 15", "quantity": 2, ...}

    # ── Workflow state ──
    current_product_id: Optional[str]    # Product ID đang xử lý (set bởi ResolveProductNode)
    resolved_product_name: Optional[str]  # Tên sản phẩm chính xác từ DB (set bởi ResolveProductNode)
    candidate_products: list             # Danh sách sản phẩm từ search/recommend
    tool_results: Annotated[dict, merge_tool_results]  # {f"{tool_name}:{call_id}": result}
    final_answer: str                    # Câu trả lời cuối cùng

    # ── Sequential workflow (mixing) ──
    pending_workflows: list              # ["recommend", "cart"] — chạy tuần tự
    current_workflow_index: int          # Workflow thứ mấy đang chạy
    workflow_results: list               # Kết quả từng workflow

    # ── Session ──
    session_id: str
    user_id: str
    trace_id: str                        # UUID cho tracing

    # ── Confirmation ──
    pending_action: Optional[dict]       # {"token": "...", "action": "AddItem", "params": {...}}
    confirmed: bool                      # User đã confirm chưa (resume từ checkpoint)

    # ── Error & Retry ──
    errors: Annotated[list, accumulate_errors]  # [{"node": "...", "error": "...", ...}]
    retry_count: int                     # Tổng số lần retry toàn cục
    node_retry_counts: dict              # {"ToolExecutor:search_products_v2": 2}

    # ── Guardrail ──
    guardrail_violations: list           # [{"guardrail": "L2a", "type": "JAILBREAK", "detail": ...}]

    # ── Telemetry ──
    node_durations: Annotated[dict, merge_node_durations]  # {"InputGuard": 12, ...} (ms)


# ──────────────────────────────────────────────────────────────────
# Default state factory (khởi tạo với giá trị mặc định hợp lý)
# ──────────────────────────────────────────────────────────────────

def default_state() -> ShoppingState:
    """Trả về ShoppingState với tất cả fields có giá trị mặc định."""
    return ShoppingState(
        messages=[],
        intent="agent",
        intent_source="default",
        entities={},
        current_product_id=None,
        resolved_product_name=None,
        candidate_products=[],
        tool_results={},
        final_answer="",
        pending_workflows=[],
        current_workflow_index=0,
        workflow_results=[],
        session_id="",
        user_id="anonymous",
        trace_id="",
        pending_action=None,
        confirmed=False,
        errors=[],
        retry_count=0,
        node_retry_counts={},
        guardrail_violations=[],
        node_durations={},
    )
