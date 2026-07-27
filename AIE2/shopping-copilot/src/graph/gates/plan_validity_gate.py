"""graph/gates/plan_validity_gate.py — Plan Validity Gate"""

from __future__ import annotations
import json
import time
from src.graph.gates.gate_node import gate_node


async def plan_validity_gate_node(state: dict) -> dict:
    t0 = time.time()
    plan = state.get("plan") or {}
    nodes = plan.get("nodes", [])

    if len(nodes) <= 1:
        gate_decisions = dict(state.get("gate_decisions") or {})
        gate_decisions["plan_validity_gate"] = {"decision": True, "reason": "single-node plan skip"}
        return {
            "gate_decisions": gate_decisions,
            "node_durations": {"plan_validity_gate": int((time.time() - t0) * 1000)},
        }

    from src.llm.prompt import GATE_QUESTIONS
    from src.tools.registry import ToolRegistry

    available_tools = ", ".join(sorted(ToolRegistry.get_all_specs().keys()))
    question = GATE_QUESTIONS["plan_validity_gate"].format(
        intent=plan.get("goal", ""),
        entities=json.dumps({"nodes": len(nodes)}, ensure_ascii=False),
        plan_json=json.dumps({"nodes": nodes[:4]}, ensure_ascii=False),
        available_tools=available_tools,
    )

    result = await gate_node(question=question, gate_name="plan_validity_gate",
                              want_reason=True, timeout=15.0)

    gate_decisions = dict(state.get("gate_decisions") or {})
    gate_decisions["plan_validity_gate"] = {"decision": result.decision, "reason": result.reason}

    return {
        "gate_decisions": gate_decisions,
        "node_durations": {"plan_validity_gate": int((time.time() - t0) * 1000)},
    }
