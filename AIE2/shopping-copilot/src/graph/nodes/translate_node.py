"""
graph/nodes/translate_node.py — Translate Node

Chuyển query sang tiếng Việt trước khi đưa vào Planner (task_graph_builder).
- Nếu resolved_query có thì translate nó, nếu không thì translate message cuối.
- Bỏ qua nếu query đã là tiếng Việt.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("graph.translate_node")

TRANSLATE_PROMPT = """\
Bạn là phiên dịch viên chuyên nghiệp. Nhiệm vụ của bạn là dịch câu sau đây sang tiếng Việt.

YÊU CẦU:
- Chỉ trả về bản dịch, KHÔNG giải thích, KHÔNG thêm lời thoại.
- Giữ nguyên thông tin: tên sản phẩm, số tiền, số lượng, địa chỉ.
- Nếu câu đã là tiếng Việt, trả về nguyên văn.
- Giữ nguyên các từ viết tắt, tên thương hiệu, tên sản phẩm (VD: National Geographic, DSLR, LED, USA).

Câu gốc: {query}
Bản dịch:"""


async def translate_node(state: dict) -> dict:
    t0 = time.time()

    try:
        resolved_query = state.get("resolved_query") or ""
        messages = state.get("messages", [])
        last_msg = ""
        if messages:
            last = messages[-1]
            last_msg = last.content if hasattr(last, "content") else str(last)

        query = resolved_query or last_msg
        if not query:
            duration_ms = int((time.time() - t0) * 1000)
            return {"node_durations": {"translate": duration_ms}}

        from src.tools.language_detector import detect_language
        lang = detect_language(query)

        if lang == "vi":
            logger.info("[translate] query already Vietnamese, passing through")
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "translated_query": query,
                "user_original_lang": "vi",
                "node_durations": {"translate": duration_ms},
            }

        from src.llm.llm import get_llm_client
        llm = get_llm_client()
        prompt = TRANSLATE_PROMPT.format(query=query)

        try:
            resp = llm.invoke(prompt, temperature=0.0, max_tokens=300)
            translated = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
        except Exception as e:
            logger.warning("[translate] LLM translation failed: %s", e)
            translated = query

        if not translated:
            translated = query

        logger.info("[translate] %.80s → %.80s", query.replace("\n", " "), translated.replace("\n", " "))

    except Exception as e:
        logger.error("[translate] UNHANDLED ERROR: %s", e, exc_info=True)
        translated = state.get("resolved_query") or ""
        if not translated:
            messages = state.get("messages", [])
            if messages:
                last = messages[-1]
                translated = last.content if hasattr(last, "content") else str(last)

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "translated_query": translated,
        "user_original_lang": lang,
        "node_durations": {"translate": duration_ms},
    }
