"""Deterministic routing for narrow, obvious non-product requests."""

import re
import unicodedata


def _normalized_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )


def is_clearly_off_topic_question(question: str) -> bool:
    """Fast-path obvious non-product requests before spending model calls.

    Patterns are intentionally narrow so ambiguous product questions continue
    through the grounded candidate and judge path.
    """
    normalized = _normalized_search_text(question)
    patterns = (
        r"^\s*\d+\s*[+*/-]\s*\d+",
        r"\b(?:capital|thu do)\s+(?:of|cua)\b",
        r"\b(?:what is the weather|weather (?:in|today)|thoi tiet (?:o|tai|hom nay))\b",
        r"\b(?:write|tell|sang tac|viet|ke).{0,30}\b(?:poem|story|bai tho|truyen)\b",
        r"\b(?:recipe|cong thuc nau|cach nau)\b",
        r"\btranslate\b.{0,80}\b(?:into|to)\b",
        r"\b(?:write|viet|generate|tao|create|make|code|lap trinh)\b.{0,80}\b(?:code|python|javascript|java|c\+\+|html|css|script|hello world|web\s?page)\b",
        r"\bhello\s+world\b.{0,80}\b(?:html|css|code|script|program)\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)
