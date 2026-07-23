"""
graph/edges.py — Edge routing functions cho LangGraph v3.4
"""

from __future__ import annotations


def route_after_input_guard(state: dict) -> str:
    violations = state.get("guardrail_violations") or []
    if violations:
        return "blocked"
    return "task_graph_builder"


def route_after_plan_validity_gate(state: dict) -> str:
    gate = (state.get("gate_decisions") or {}).get("plan_validity_gate", {})
    decision = gate.get("decision", True)
    nodes = (state.get("plan") or {}).get("nodes", [])
    if not nodes:
        return "response_verifier"
    return "tool_executor" if decision else "response_verifier"


def route_after_reflection(state: dict) -> str:
    result = state.get("reflection_result", "pass")
    if result == "replan":
        return "replan_gate"
    return "response_verifier"


def route_after_hallucination_guard(state: dict) -> str:
    if state.get("hallucination_detected") or state.get("semantic_hallucination_detected"):
        return "fallback_generator"
    return "answer_generator"


def route_after_replan_gate(state: dict) -> str:
    """Replan Gate: YES → task_graph_builder, NO → response_verifier."""
    gate = (state.get("gate_decisions") or {}).get("replan_gate", {})
    decision = gate.get("decision", False)
    return "task_graph_builder" if decision else "response_verifier"


def route_after_tool_executor(state: dict) -> str:
    """Tool Executor: pending_action → confirmation, else → reflection."""
    pending = state.get("pending_action")
    if pending:
        return "confirmation"
    return "reflection"
