"""
agent/response_formatter.py — Response Formatter block

Chạy SAU Output Filter (L5), dùng LLM rẻ (mixtral-8b-32768) để:
- Restructure câu trả lời thành markdown có cấu trúc
- Loại bỏ icon/emoji
- Làm nội dung dễ đọc, chuyên nghiệp hơn

Nếu LLM fail hoặc response quá ngắn → giữ nguyên bản gốc.
"""

import logging
from typing import Optional

logger = logging.getLogger("agent.response_formatter")

# ── Prompt ──────────────────────────────────────────────

_FORMAT_PROMPT = """Bạn là chuyên gia định dạng nội dung thương mại điện tử.
Nhiệm vụ: Viết lại đoạn văn bên dưới thành markdown có cấu trúc, dễ đọc, chuyên nghiệp.

QUY TẮC:
1. LOẠI BỎ hoàn toàn mọi icon/emoji (✅ ❌ ⚠️ 🚀 🛒 ⭐ 💰 👉 🎉 🔥 v.v.)
2. Dùng **bold** cho tên sản phẩm và số tiền
3. Dùng gạch đầu dòng (-) cho danh sách
4. Giữ nguyên mọi thông tin thực tế (giá, tên, mô tả, số lượng)
5. Xuống dòng hợp lý giữa các section
6. Giọng văn lịch sự, chuyên nghiệp, thân thiện
7. KHÔNG thêm thông tin không có trong đoạn gốc
8. KHÔNG thay đổi ý nghĩa hoặc nội dung
9. Nếu đoạn gốc ngắn hơn 20 từ hoặc chỉ là lời chào/cảm ơn — giữ nguyên, không sửa

ĐOẠN VĂN GỐC:
"""


def format_response(text: str) -> Optional[str]:
    """
    Restructure response text thành markdown structured.
    Gọi LLM rẻ (mixtral-8b-32768) để formatting.

    Args:
        text: Response gốc từ Output Filter.

    Returns:
        String đã format, hoặc None nếu text quá ngắn / LLM fail.
    """
    if not text or len(text.strip()) < 20:
        logger.debug("[FORMATTER] Response quá ngắn, giữ nguyên")
        return None

    from llm.llm import LLMClient
    from llm import get_llm_client

    client = get_llm_client()
    if not isinstance(client, LLMClient):
        logger.debug("[FORMATTER] Not a real LLM client (%s) — skip formatting", type(client).__name__)
        return None

    full_prompt = _FORMAT_PROMPT + text

    try:
        response = client.invoke(
            prompt=full_prompt,
            temperature=0.1,
            max_tokens=1024,
        )

        if not response or not response.content:
            logger.warning("[FORMATTER] LLM trả response rỗng")
            return None

        formatted = response.content.strip()
        if not formatted:
            return None

        logger.info(
            "[FORMATTER] OK | %d → %d chars",
            len(text), len(formatted),
        )
        return formatted

    except Exception as e:
        logger.error("[FORMATTER] LLM invoke error: %s", str(e)[:120])
        return None
