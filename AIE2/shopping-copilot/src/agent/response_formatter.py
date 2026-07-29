"""
agent/response_formatter.py — Response Formatter block

Chạy SAU Output Filter (L5), thực hiện:
- Loại bỏ icon/emoji
- Chuẩn hóa khoảng trắng
- Dùng LLM để tái cấu trúc nội dung dễ đọc, chuyên nghiệp hơn
- Giữ nguyên tuyệt đối ý nghĩa và nội dung gốc (không thêm/bớt/sửa thông tin)
- Rule-based fallback nếu LLM không khả dụng
"""

import logging
import re
from typing import Optional

from src.llm.llm import llm_model
from src.llm.prompt import FORMAT_PROMPT_RESTRUCTURE

logger = logging.getLogger("agent.response_formatter")


# ── Emoji removal pattern ──────────────────────────────

_ICON_PATTERNS: list = []

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticon
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed chars
    "\U0001F200-\U0001F2FF"  # enclosed ideographic supplement
    "\U00002600-\U000026FF"  # miscellaneous symbols
    "\U00002700-\U000027BF"  # dingbats extended
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U00002B50"             # star
    "\U00002934-\U00002935"  # arrows
    "\U000025AA-\U000025AB"  # geometric shapes
    "\U000025B6"             # play button
    "\U000025C0"             # reverse button
    "\U000023F0-\U000023FF"  # time
    "\U000023E9-\U000023F3"  # arrows
    "\U0000FE0F"             # variation selector-16
    "\U000020E3"             # combining enclosing keycap
    "]"
)


# ── Content-type detection ──────────────────────────────

def _detect_content_type(text: str) -> str:
    text_lower = text.lower().strip()
    words = text.split()
    word_count = len(words)

    if word_count < 20 or any(text_lower.startswith(g) for g in
                              ["chào", "xin chào", "cảm ơn", "hello", "hi"]):
        return "GREETING"

    error_kw = ["lỗi", "không khả dụng", "không tìm thấy", "không thể xử lý",
                "thử lại", "error", "fail", "thất bại"]
    if any(kw in text_lower for kw in error_kw):
        return "ERROR"

    comp_kw = ["so sánh", "khác nhau", "vs", "phân biệt", "khác biệt"]
    if any(kw in text_lower for kw in comp_kw):
        return "COMPARISON"

    rec_kw = ["gợi ý", "đề xuất", "nên mua", "recommend", "suggest", "phù hợp"]
    if any(kw in text_lower for kw in rec_kw):
        return "RECOMMENDATION"

    bullet_lines = len(re.findall(r'^\s*[-*]\s', text, re.MULTILINE))
    bold_items = len(re.findall(r'\*\*[^*]+\*\*', text))
    price_patterns = len(re.findall(r'[\d,]+\.?\d*\s*(₫|vnd|usd|\$|€|¥)', text, re.IGNORECASE))
    product_hints = bullet_lines + bold_items + price_patterns

    if product_hints >= 2:
        return "PRODUCT_LIST"
    if product_hints >= 1:
        return "PRODUCT_INFO"

    return "GENERAL"


# ── LLM restructuring ──────────────────────────────────

def _llm_restructure(text: str) -> Optional[str]:
    """Call LLM to restructure text for readability, preserving meaning exactly."""
    if llm_model is None:
        logger.debug("[FORMATTER] LLM không khả dụng, bỏ qua LLM restructuring")
        return None
    try:
        prompt = FORMAT_PROMPT_RESTRUCTURE + "\n" + text
        response = llm_model.invoke(prompt, temperature=0.0, max_tokens=1024)
        if response and response.content:
            formatted = response.content.strip()
            if formatted:
                logger.info("[FORMATTER] LLM restructure OK (%d chars)", len(formatted))
                return formatted
    except Exception as e:
        logger.warning("[FORMATTER] LLM restructure error: %s", str(e)[:120])
    return None


# ── Rule-based formatting ──────────────────────────────

def _remove_emojis(text: str) -> str:
    text = _EMOJI_PATTERN.sub('', text)
    for pattern in _ICON_PATTERNS:
        text = pattern.sub('', text)
    text = re.sub(r'[\U0000FE00-\U0000FE0F]', '', text)
    return text


def _clean_whitespace(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^[ \t]+\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n[ \t]+$', '\n', text, flags=re.MULTILINE)
    return text.strip()


def _ensure_bold_prices(text: str) -> str:
    text = re.sub(
        r'(?<!\*)([\d]{1,3}(?:\.\d{3})*(?:\s*(₫|đồng|vnd|usd|\$|€|¥)))(?!\*)',
        r'**\1**',
        text,
        flags=re.IGNORECASE,
    )
    return text


def _rule_format(text: str) -> str:
    text = _remove_emojis(text)
    text = _ensure_bold_prices(text)
    text = _clean_whitespace(text)
    return text


# ── Main entry point ────────────────────────────────────

def format_response(text: str) -> Optional[str]:
    if not text or len(text.strip()) < 20:
        logger.debug("[FORMATTER] Response quá ngắn, giữ nguyên")
        return None

    content_type = _detect_content_type(text)
    logger.debug("[FORMATTER] Detected content type: %s", content_type)

    if content_type in ("GREETING", "ERROR"):
        logger.debug("[FORMATTER] %s — giữ nguyên bản gốc", content_type)
        return None

    try:
        attempt_llm = llm_model is not None and content_type != "GENERAL"

        if attempt_llm:
            cleaned = _remove_emojis(text)
            llm_result = _llm_restructure(cleaned)
            if llm_result:
                result = _ensure_bold_prices(llm_result)
                result = _clean_whitespace(result)
                logger.info("[FORMATTER] LLM %s | %d → %d chars", content_type, len(text), len(result))
                return result

        formatted = _rule_format(text)
        logger.info("[FORMATTER] Rule %s | %d → %d chars", content_type, len(text), len(formatted))
        return formatted

    except Exception as e:
        logger.error("[FORMATTER] Error: %s", str(e)[:120])
        return None