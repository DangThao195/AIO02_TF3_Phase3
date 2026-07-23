"""
graph/main_graph.py — Shopping Copilot LangGraph v3.4

Topology:
  START → input_guard → task_graph_builder → plan_validity_gate
        → tool_executor → reflection → replan_gate
        → (replan → task_graph_builder) or (continue → response_verifier)
        → response_verifier → hallucination_guard
        → answer_generator / fallback_generator → answer_generator → END
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.graph.state import ShoppingState
from src.graph.edges import (
    route_after_input_guard,
    route_after_plan_validity_gate,
    route_after_reflection,
    route_after_hallucination_guard,
    route_after_tool_executor,
)
from src.graph.nodes import (
    input_guard_node,
    task_graph_builder_node,
    tool_executor_node,
    confirmation_node,
    reflection_node,
    response_verifier_node,
    hallucination_guard_node,
    fallback_generator_node,
    answer_generator_node,
)
from src.graph.gates import (
    plan_validity_gate_node,
    replan_gate_node,
)

logger = logging.getLogger("graph.main_graph")
_IO_LOG = logging.getLogger("graph.io")

# ── Node I/O logging helpers ──────────────────────────────────────


def _summarize_input(node_name: str, state: dict) -> str:
    """Build compact input summary for a node, tailored per node type."""
    info = {}

    msgs = state.get("messages", [])
    if msgs:
        last = msgs[-1]
        text = (last.content if hasattr(last, "content") else str(last))[:120]
        info["msg"] = text.replace("\n", " ")

    if node_name in ("task_graph_builder", "plan_validity_gate",
                     "reflection", "response_verifier"):
        if state.get("tool_results"):
            info["tool_results"] = str(list(state["tool_results"].keys()))
        if state.get("planner_memory"):
            mem = state["planner_memory"]
            info["memory"] = str({k: v for k, v in mem.items()
                                  if k not in ("mentioned_products",)})

    if node_name in ("reflection", "response_verifier", "hallucination_guard",
                     "fallback_generator", "tool_executor"):
        if state.get("errors"):
            info["errors"] = len(state["errors"])
        if state.get("tool_results"):
            info["tool_results"] = str(list(state["tool_results"].keys()))

    if node_name in ("task_graph_builder", "plan_validity_gate", "tool_executor"):
        plan = state.get("plan")
        if plan:
            info["plan_nodes"] = len(plan.get("nodes", []))
            if plan.get("goal"):
                info["plan_goal"] = plan["goal"][:80]

    if node_name in ("reflection",):
        if state.get("replan_count") is not None:
            info["replan_count"] = state["replan_count"]
        if state.get("pending_action"):
            info["pending"] = state["pending_action"].get("action", "?")

    if node_name == "confirmation":
        pa = state.get("pending_action")
        if pa:
            info["pending_action"] = pa.get("action", "?")
        if state.get("confirmed"):
            info["confirmed"] = state["confirmed"]

    if node_name in ("plan_validity_gate", "replan_gate"):
        if state.get("gate_decisions"):
            info["gate_decisions"] = str(state["gate_decisions"])
        if state.get("current_goal"):
            info["goal"] = state["current_goal"][:80]

    if node_name in ("response_verifier", "hallucination_guard",
                     "answer_generator", "fallback_generator"):
        fa = state.get("final_answer", "")
        if fa:
            info["final_answer"] = fa[:80].replace("\n", " ")

    if node_name == "hallucination_guard":
        cs = state.get("complexity_score")
        if cs is not None:
            info["complexity_score"] = f"{cs:.2f}"

    if not info:
        info["state_keys"] = str(list(state.keys()))

    return str(info)


def _summarize_output(node_name: str, result: dict) -> str:
    """Build compact output summary from a node's return dict."""
    info = {}
    for k, v in result.items():
        if k == "node_durations":
            continue
        if k == "final_answer" and isinstance(v, str):
            info[k] = v[:120].replace("\n", " ")
        elif k == "errors" and isinstance(v, list):
            info[k] = f"{len(v)} errors"
        elif k == "tool_results" and isinstance(v, dict):
            info[k] = str(list(v.keys()))
        elif k == "plan" and isinstance(v, dict):
            info[k] = f"{len(v.get('nodes', []))} nodes, goal={v.get('goal','')[:40]}"
        elif k == "guardrail_violations" and isinstance(v, list):
            info[k] = f"{len(v)} violations"
        elif k == "reflection_issues" and isinstance(v, list):
            info[k] = f"{len(v)} issues"
        elif k == "gate_decisions" and isinstance(v, dict):
            info[k] = str(v)
        elif k == "pending_action" and isinstance(v, dict):
            info[k] = v.get("action", "?")
        elif k == "planner_memory" and isinstance(v, dict):
            info[k] = str({kk: str(vv)[:60] for kk, vv in v.items()
                           if kk not in ("mentioned_products",)})
        elif k in ("confidence", "plan_confidence") and isinstance(v, (int, float)):
            info[k] = f"{v:.2f}"
        elif k in ("current_goal", "planner_reasoning",
                   "reflection_result", "hallucination_detected",
                   "groundedness_score", "complexity_score", "fallback_used",
                   "replan_count", "retry_count", "plan_step_index"):
            if isinstance(v, float):
                info[k] = f"{v:.2f}"
            else:
                info[k] = str(v)[:60]
        elif isinstance(v, (str, int, float, bool)):
            info[k] = v
        elif isinstance(v, dict):
            info[k] = str({kk: str(vv)[:60]
                          for kk, vv in list(v.items())[:5]})
        elif isinstance(v, list):
            info[k] = f"[{len(v)} items]"
        else:
            info[k] = type(v).__name__
    return str(info)


def _log_node_io(node_name: str, func):
    """Wrap a node function to log input summary and output summary."""
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapper(state: dict) -> dict:
            _IO_LOG.debug("[NODE:%s] INPUT %s", node_name,
                          _summarize_input(node_name, state))
            t0 = time.time()
            try:
                result = await func(state)
            except Exception as e:
                _IO_LOG.error("[NODE:%s] ERROR %s (%dms)", node_name,
                              str(e)[:300], int((time.time() - t0) * 1000))
                raise
            dur_ms = int((time.time() - t0) * 1000)
            _IO_LOG.debug("[NODE:%s] OUTPUT %s (%dms)", node_name,
                          _summarize_output(node_name, result), dur_ms)
            return result
        return wrapper

    @functools.wraps(func)
    def wrapper(state: dict) -> dict:
        _IO_LOG.debug("[NODE:%s] INPUT %s", node_name,
                      _summarize_input(node_name, state))
        t0 = time.time()
        try:
            result = func(state)
        except Exception as e:
            _IO_LOG.error("[NODE:%s] ERROR %s (%dms)", node_name,
                          str(e)[:300], int((time.time() - t0) * 1000))
            raise
        dur_ms = int((time.time() - t0) * 1000)
        _IO_LOG.debug("[NODE:%s] OUTPUT %s (%dms)", node_name,
                      _summarize_output(node_name, result), dur_ms)
        return result
    return wrapper


def build_graph() -> StateGraph:
    """
    Build và compile LangGraph StateGraph cho Shopping Copilot v3.4.

    Returns:
        Compiled graph với MemorySaver checkpoint.
    """
    # Import all tools to trigger ToolRegistry registration
    import src.tools  # noqa: F401

    graph = StateGraph(ShoppingState)

    # ── Register nodes (wrapped with I/O logging) ────────────────
    graph.add_node("input_guard",        _log_node_io("input_guard",        input_guard_node))
    graph.add_node("task_graph_builder", _log_node_io("task_graph_builder", task_graph_builder_node))
    graph.add_node("plan_validity_gate", _log_node_io("plan_validity_gate", plan_validity_gate_node))
    graph.add_node("tool_executor",      _log_node_io("tool_executor",      tool_executor_node))
    graph.add_node("reflection",         _log_node_io("reflection",         reflection_node))
    graph.add_node("response_verifier",  _log_node_io("response_verifier",  response_verifier_node))
    graph.add_node("hallucination_guard", _log_node_io("hallucination_guard", hallucination_guard_node))
    graph.add_node("fallback_generator", _log_node_io("fallback_generator", fallback_generator_node))
    graph.add_node("answer_generator",   _log_node_io("answer_generator",   answer_generator_node))
    graph.add_node("replan_gate",        _log_node_io("replan_gate",        replan_gate_node))
    graph.add_node("confirmation",       _log_node_io("confirmation",       confirmation_node))

    # ── Entry point ──────────────────────────────────────────────
    graph.set_entry_point("input_guard")

    # ── Edges ────────────────────────────────────────────────────

    # input_guard → task_graph_builder OR end (blocked)
    graph.add_conditional_edges(
        "input_guard",
        route_after_input_guard,
        {
            "task_graph_builder": "task_graph_builder",
            "blocked": "answer_generator",
        },
    )

    # task_graph_builder → plan_validity_gate
    graph.add_edge("task_graph_builder", "plan_validity_gate")

    # plan_validity_gate → tool_executor OR response_verifier (no-tool plan)
    graph.add_conditional_edges(
        "plan_validity_gate",
        route_after_plan_validity_gate,
        {
            "tool_executor": "tool_executor",
            "response_verifier": "response_verifier",
        },
    )

    # tool_executor → confirmation OR reflection (conditional on pending_action)
    graph.add_conditional_edges(
        "tool_executor",
        route_after_tool_executor,
        {
            "confirmation": "confirmation",
            "reflection": "reflection",
        },
    )

    # reflection → replan_gate OR response_verifier
    graph.add_conditional_edges(
        "reflection",
        route_after_reflection,
        {
            "replan_gate": "replan_gate",
            "response_verifier": "response_verifier",
        },
    )

    # replan_gate → task_graph_builder OR response_verifier
    from src.graph.edges import route_after_replan_gate
    graph.add_conditional_edges(
        "replan_gate",
        route_after_replan_gate,
        {
            "task_graph_builder": "task_graph_builder",
            "response_verifier": "response_verifier",
        },
    )

    # response_verifier → hallucination_guard
    graph.add_edge("response_verifier", "hallucination_guard")

    # hallucination_guard → answer_generator OR fallback_generator
    graph.add_conditional_edges(
        "hallucination_guard",
        route_after_hallucination_guard,
        {
            "answer_generator": "answer_generator",
            "fallback_generator": "fallback_generator",
        },
    )

    # fallback_generator → answer_generator
    graph.add_edge("fallback_generator", "answer_generator")

    # confirmation → response_verifier (sau khi user confirm write)
    graph.add_edge("confirmation", "response_verifier")

    # answer_generator → END
    graph.add_edge("answer_generator", END)

    # ── Compile with MemorySaver (session checkpoint) ────────────
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer, interrupt_before=[])

    logger.info("[main_graph] Graph compiled: %d nodes", len(graph.nodes))
    return compiled
