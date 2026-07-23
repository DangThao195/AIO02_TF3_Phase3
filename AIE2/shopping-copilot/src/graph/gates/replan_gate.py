"""graph/gates/replan_gate.py — Replan Gate"""

from __future__ import annotations
import json
import time
from src.graph.gates.gate_node import gate_node


async def replan_gate_node(state: dict) -> dict:
    t0 = time.time()
    goal = state.get("current_goal", "")
    tool_results = state.get("tool_results") or {}
    errors = state.get("errors") or []

    # Summarize results for gate context
    results_summary = json.dumps(
        {k: (v if isinstance(v, dict) else {"raw": str(v)[:100]}) for k, v in list(tool_results.items())[:3]},
        ensure_ascii=False
    )[:400]

    from src.llm.prompt import GATE_QUESTIONS
    question = GATE_QUESTIONS["replan_gate"].format(
        goal=goal,
        results_summary=results_summary,
        errors=str(errors[:3]),
    )

    result = await gate_node(question=question, gate_name="replan_gate",
                              want_reason=True, timeout=2.0)

    gate_decisions = dict(state.get("gate_decisions") or {})
    gate_decisions["replan_gate"] = {"decision": result.decision, "reason": result.reason}

    return {
        "gate_decisions": gate_decisions,
        "node_durations": {"replan_gate": int((time.time() - t0) * 1000)},
    }
