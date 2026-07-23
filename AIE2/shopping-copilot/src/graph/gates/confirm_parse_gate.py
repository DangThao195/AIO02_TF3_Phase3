"""graph/gates/confirm_parse_gate.py — Confirm Parse Gate"""

from __future__ import annotations
import time
from src.graph.gates.gate_node import gate_node


async def confirm_parse_gate_node(state: dict) -> dict:
    """Parse natural-language user reply to determine if it's a confirmation."""
    t0 = time.time()
    messages = state.get("messages", [])
    user_reply = messages[-1].content if messages and hasattr(messages[-1], "content") else ""

    from src.llm.prompt import GATE_QUESTIONS
    question = GATE_QUESTIONS["confirm_parse_gate"].format(user_reply=user_reply)

    result = await gate_node(question=question, gate_name="confirm_parse_gate",
                              want_reason=False, timeout=2.0)

    gate_decisions = dict(state.get("gate_decisions") or {})
    gate_decisions["confirm_parse_gate"] = {"decision": result.decision}

    return {
        "confirmed": result.decision,
        "gate_decisions": gate_decisions,
        "node_durations": {"confirm_parse_gate": int((time.time() - t0) * 1000)},
    }
