"""
graph/nodes/answer_synthesizer.py — Answer Synthesizer Node

Tổng hợp query + tool_results → final_answer draft qua LLM.
Chạy sau tool_executor, trước response_generator.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("graph.answer_synthesizer")


def _format_tool_results_text(tool_results: dict) -> str:
    lines = []
    for tool_name, result in tool_results.items():
        if tool_name.startswith("__"):
            continue
        r = result if isinstance(result, dict) else {"raw": str(result)[:200]}
        lines.append(f"[{tool_name}]: {json.dumps(r, ensure_ascii=False)[:500]}")
    return "\n".join(lines)


async def answer_synthesizer_node(state: dict) -> dict:
    """
    Answer Synthesizer — LLM tổng hợp tool_results + query → final_answer draft.
    Output: {final_answer, node_durations}
    """
    t0 = time.time()

    tool_results = {k: v for k, v in (state.get("tool_results") or {}).items() if not k.startswith("__")}
    pending = state.get("pending_action")
    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""
    current_goal = state.get("current_goal", "")
    planner_memory = state.get("planner_memory") or {}

    final_answer = ""

    # ── Trường hợp đặc biệt: tool không chạy (greeting, etc.) ──
    if not tool_results and not pending:
        import re
        from src.tools.language_detector import detect_language
        _lang = detect_language(query)
        is_en = (_lang == "en")
        if re.search(r"^(xin chào|chào|hello|hi|hey)\b", query.strip(), re.I):
            final_answer = "Hello! I'm the TechX Corp shopping assistant. I can help you find products, read reviews, and add items to your cart." if is_en else "Xin chào! Tôi là trợ lý mua sắm của TechX Corp. Tôi có thể giúp bạn tìm kiếm sản phẩm, xem đánh giá, hoặc thêm hàng vào giỏ."
        else:
            final_answer = "How can I help you with your shopping today?" if is_en else "Vui lòng cho tôi biết bạn cần tìm kiếm hay thực hiện thao tác gì?"
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "final_answer": final_answer,
            "node_durations": {"answer_synthesizer": duration_ms},
        }

    # ── Pending action → confirm message ──
    if pending:
        item = pending.get("args", {})
        product_name = item.get("product_name", item.get("product_id", "sản phẩm"))
        quantity = item.get("quantity", 1)
        final_answer = f"Vui lòng xác nhận: thêm **{quantity}** **{product_name}** vào giỏ hàng?"
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "final_answer": final_answer,
            "node_durations": {"answer_synthesizer": duration_ms},
        }

    # ── LLM Synthesis ──
    try:
        from src.llm.llm import get_llm_client
        from src.llm.prompt import SYNTHESIZER_PROMPT

        llm = get_llm_client()
        tool_results_text = _format_tool_results_text(tool_results)

        from src.tools.language_detector import detect_language
        user_lang = state.get("user_original_lang") or detect_language(query)
        lang_instruction = {
            "vi": "Viết câu trả lời bằng tiếng Việt, thân thiện, chuyên nghiệp.",
            "en": "Write the answer in English, friendly and professional.",
        }.get(user_lang, "Write the answer in the same language as the user's input.")

        mem_text = json.dumps(planner_memory, ensure_ascii=False)[:300] if planner_memory else "(không có)"

        resp = llm.invoke(
            SYNTHESIZER_PROMPT.format(
                user_query=query,
                current_goal=current_goal,
                tool_results_text=tool_results_text,
                planner_memory=mem_text,
                language_instruction=lang_instruction,
            ),
            temperature=0.2,
            max_tokens=1200,
        )
        final_answer = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        logger.warning("[answer_synthesizer] LLM failed: %s", e)
        final_answer = _format_tool_results_text(tool_results)[:500]

    if not final_answer:
        final_answer = "Tôi đã xử lý yêu cầu của bạn. Bạn cần hỗ trợ thêm gì không?"

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "final_answer": final_answer,
        "node_durations": {"answer_synthesizer": duration_ms},
    }
