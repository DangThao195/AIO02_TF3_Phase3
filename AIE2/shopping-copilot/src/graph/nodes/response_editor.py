"""
graph/nodes/response_editor.py — ResponseEditor node.

Node tổng hợp câu trả lời cuối cùng từ tool results + user query,
đặt giữa workflow output và AnswerGenerator (response formatter).

Input:
  - state["messages"]            (user query gốc)
  - state["final_answer"]        (draft từ workflow aggregate)
  - state["tool_results"]        (kết quả tool call để grounding)
  - state["entities"]            (thông tin đã extract)
  - state["resolved_product_name"]

Output:
  - state["final_answer"]        (câu trả lời đã được LLM tổng hợp)
"""

from __future__ import annotations

import json
import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.response_editor")


_EDITOR_PROMPT = """\
Bạn là nhân viên bán hàng của TechX Corp, đang trò chuyện trực tiếp với khách hàng.
Nhiệm vụ của bạn là thuật lại thông tin nhận được bằng lời nói tự nhiên, như đang nói chuyện bình thường.

QUY TẮC:
1. Chỉ dùng thông tin có trong dữ liệu được cung cấp — KHÔNG thêm chi tiết không có.
2. Nói như đang trò chuyện trực tiếp: câu từ tự nhiên, ngắn gọn, có ngữ điệu nói.
3. KHÔNG dùng markdown, không in đậm, không gạch đầu dòng, không emoji.
4. KHÔNG đề cập product_id, tool, API, hay bất kỳ mã kỹ thuật nào.
5. Giữ nguyên giá cả, tên sản phẩm, số lượng — không làm sai lệch thông tin.
6. Nếu không có thông tin hoặc có lỗi, nói thẳng "Tôi không tìm thấy..." thay vì bịa.
7. Xưng hô: "tôi" — "bạn", lịch sự nhưng gần gũi.

Khách hàng hỏi: {user_query}

Tôi nhận được thông tin sau:
{tool_results_text}

Dự thảo trả lời để tham khảo: {draft}

Tôi sẽ trả lời khách hàng:"""


class ResponseEditor:
    """
    Node tổng hợp câu trả lời từ tool results.
    Gọi LLM để tạo câu trả lời tự nhiên, grounded vào dữ liệu thật.

    Nếu tool_results rỗng hoặc draft quá ngắn (< 20 chars),
    giữ nguyên draft để tránh hallucination.
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from src.llm.llm import llm_model
            self._llm = llm_model
        return self._llm

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        messages = state.get("messages", [])
        draft = state.get("final_answer", "")
        tool_results = state.get("tool_results", {})

        # Extract user query gốc
        user_query = ""
        for msg in reversed(messages):
            if hasattr(msg, "type") and getattr(msg, "type", "") == "human":
                user_query = msg.content if hasattr(msg, "content") else str(msg)
                break
            if hasattr(msg, "content") and isinstance(msg.content, str):
                user_query = msg.content
                break

        # Nếu không có tool results hoặc draft đã đầy đủ → giữ nguyên
        if not tool_results or (draft and len(draft.strip()) < 20):
            logger.debug("[RESPONSE_EDITOR] Skip: no tool results or short draft")
            return {"node_durations": {"ResponseEditor": _ms(t0)}}

        llm = self._get_llm()
        if llm is None:
            logger.debug("[RESPONSE_EDITOR] Skip: LLM unavailable")
            return {"node_durations": {"ResponseEditor": _ms(t0)}}

        # Build tool results text (tối đa 2000 chars)
        tool_lines = []
        for key, val in tool_results.items():
            tool_name = key.split(":")[0]
            result = val.get("result", "")
            if result:
                text = str(result)[:500]
                tool_lines.append(f"[{tool_name}] {text}")
        tool_results_text = "\n".join(tool_lines)[:2000]

        if not tool_results_text:
            logger.debug("[RESPONSE_EDITOR] Skip: no tool result content")
            return {"node_durations": {"ResponseEditor": _ms(t0)}}

        prompt = _EDITOR_PROMPT.format(
            user_query=user_query or "(không rõ)",
            tool_results_text=tool_results_text,
            draft=draft or "(trống)",
        )

        try:
            response = llm.invoke(prompt, temperature=0.2, max_tokens=1024)
            if response and response.content:
                edited = response.content.strip()
                if len(edited) > 20:
                    logger.info(
                        "[RESPONSE_EDITOR] Edited | draft=%d → %d chars",
                        len(draft), len(edited)
                    )
                    return {
                        "final_answer": edited,
                        "node_durations": {"ResponseEditor": _ms(t0)},
                    }
        except Exception as e:
            logger.warning("[RESPONSE_EDITOR] LLM error: %s", str(e)[:100])

        return {"node_durations": {"ResponseEditor": _ms(t0)}}


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000
