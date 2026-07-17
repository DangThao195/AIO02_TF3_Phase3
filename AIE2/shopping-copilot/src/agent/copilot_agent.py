from __future__ import annotations

import uuid
from typing import Any, Dict, List


class CopilotAgent:
    """Thin wrapper around the LangGraph app used by CLI tests and benchmarks."""

    def __init__(self):
        self._graph = None
        self._steps: List[Dict[str, Any]] = []

    def _get_graph(self):
        if self._graph is None:
            from src.main import _get_graph

            self._graph = _get_graph()
        return self._graph

    async def chat(self, session_id: str, user_id: str, user_message: str) -> Dict[str, Any]:
        from langchain_core.messages import HumanMessage
        from src.main import _build_steps

        graph = self._get_graph()
        config = {"configurable": {"thread_id": session_id}}

        try:
            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content=user_message)],
                    "session_id": session_id,
                    "user_id": user_id,
                    "trace_id": str(uuid.uuid4()),
                },
                config=config,
            )
        except Exception as e:
            self._steps = []
            return {
                "status": "error",
                "reply": f"Lỗi hệ thống: {str(e)[:200]}",
                "session_id": session_id,
                "steps": [],
            }

        steps = []
        for step in _build_steps(result):
            if hasattr(step, "model_dump"):
                steps.append(step.model_dump())
            elif hasattr(step, "dict"):
                steps.append(step.dict())
            elif isinstance(step, dict):
                steps.append(step)
            else:
                steps.append({"action": str(step)})
        self._steps = steps

        violations = result.get("guardrail_violations", [])
        if violations:
            violation = violations[0]
            return {
                "status": "error",
                "reply": violation.get("detail", "Yêu cầu bị từ chối."),
                "session_id": session_id,
                "steps": steps,
            }

        interrupts = result.get("__interrupt__", [])
        if interrupts:
            interrupt_value = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            if isinstance(interrupt_value, dict):
                pending_action = interrupt_value.get("pending_action")
                if pending_action:
                    return {
                        "status": "pending",
                        "reply": pending_action.get("message", "Vui lòng xác nhận hành động."),
                        "token": pending_action.get("token"),
                        "session_id": session_id,
                        "steps": steps,
                    }

        return {
            "status": "ok",
            "reply": result.get("final_answer", ""),
            "session_id": session_id,
            "steps": steps,
        }
