"""Shopping Copilot agent executor (AIE2-TF3).

Implements the safety envelope the task requires:
  - max_iterations = 3  (protect page latency / SLO — no runaway reasoning loops)
  - input filter BEFORE the model (prompt-injection / system-leak / PII)
  - tool allowlist + confirmation gate (excessive-agency guard)
  - try/except fallback around the LLM call (friendly reply, never hang the app)

It is framework-agnostic by design: `llm_step` and `run_tool` are injected. To back it with
LangChain, pass a LangChain AgentExecutor's step fn as `llm_step` — the safety envelope here
wraps whatever planner you use. (Keeping LangChain out of the hard dependency list means the
engine still installs + tests without a heavy runtime; see build_langchain_executor note.)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from ..aie.input_filter import Threat, scan_user_question
from .system_prompt import REFUSAL, SYSTEM_PROMPT
from .tools import ToolCall, ToolDenied, authorize, confirmation_prompt

log = logging.getLogger("ai_engine.agent")

MAX_ITERATIONS = 3
FRIENDLY_FALLBACK = ("Xin lỗi, hệ thống trợ lý đang bận. Bạn vẫn có thể duyệt sản phẩm và "
                     "đọc đánh giá bình thường. Vui lòng thử lại sau giây lát.")


@dataclass
class AgentTurn:
    """One step the planner proposes: either a tool call or a final answer."""

    final_answer: str | None = None
    tool_call: ToolCall | None = None


@dataclass
class AgentResult:
    answer: str
    used_tools: list[str] = field(default_factory=list)
    pending_confirmation: str | None = None
    refused: bool = False
    degraded: bool = False


class ShoppingCopilot:
    def __init__(
        self,
        llm_step: Callable[[str, list[dict]], AgentTurn],
        run_tool: Callable[[ToolCall], str],
        max_iterations: int = MAX_ITERATIONS,
    ):
        self._llm_step = llm_step
        self._run_tool = run_tool
        self._max_iterations = max_iterations

    def handle(self, user_message: str) -> AgentResult:
        # Determine max iterations dynamically: compare intent gets 5, others default to constructor value
        max_iters = self._max_iterations
        if self._max_iterations == MAX_ITERATIONS:  # only apply dynamic logic if default was used
            message_lower = user_message.lower()
            compare_keywords = ["so sánh", "compare", "khác gì", "tốt hơn", "so với", "vs"]
            if any(kw in message_lower for kw in compare_keywords):
                max_iters = 5

        scan = scan_user_question(user_message)
        if Threat.SYSTEM_LEAK in scan.threats or Threat.PROMPT_INJECTION in scan.threats:
            log.warning("agent refused suspicious input: %s", scan.details)
            return AgentResult(answer=REFUSAL, refused=True)

        transcript: list[dict] = [{"role": "user", "content": user_message}]

        try:
            for _ in range(max_iters):
                turn = self._llm_step(SYSTEM_PROMPT, transcript)

                if turn.final_answer is not None:
                    return AgentResult(answer=turn.final_answer, used_tools=self._used(transcript))

                if turn.tool_call is not None:
                    result = self._handle_tool(turn.tool_call, transcript)
                    if result is not None:
                        return result


            return AgentResult(answer=REFUSAL, degraded=True)
        except Exception:
            log.exception("agent failed; serving friendly fallback")
            return AgentResult(answer=FRIENDLY_FALLBACK, degraded=True)

    def _handle_tool(self, call: ToolCall, transcript: list[dict]) -> AgentResult | None:
        try:
            spec = authorize(call)
        except ToolDenied as exc:
            msg = str(exc)
            if "requires human confirmation" in msg:

                return AgentResult(answer="", pending_confirmation=confirmation_prompt(call),
                                   used_tools=self._used(transcript))
            log.warning("tool denied: %s", msg)
            return AgentResult(answer=REFUSAL, refused=True)

        observation = self._run_tool(call)
        transcript.append({"role": "tool", "name": spec.name, "content": observation})
        return None

    @staticmethod
    def _used(transcript: list[dict]) -> list[str]:
        return [m["name"] for m in transcript if m.get("role") == "tool"]


