"""Input filter (AIE-TF3 / AI-20, AI-21) — prompt-injection + PII + system-prompt-leak guard.

Sits BEFORE the LLM call: review text (indirect injection surface) and user chat questions
(direct injection surface) are scanned. This complements the output-side faithfulness
guardrail — defence in depth: filter the input, verify the output.

Design (per frontend-security-coder guidance): allowlist-minded, ReDoS-safe patterns (no
nested quantifiers, bounded classes), and non-destructive by default — we NEUTRALISE injected
instructions rather than silently dropping the whole review (a real review must still be
summarised). Detection is logged so guardrail_block/injection metrics stay observable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Threat(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    SYSTEM_LEAK = "system_leak"
    PII = "pii"


_INJECTION_PATTERNS = [
    # English
    r"\bignore (?:all |the |previous |above )?(?:instructions|prompts?|rules?)\b",
    r"\bsystem (?:instruction|prompt|message)\b",
    r"\bdisregard (?:all |the |previous )?(?:instructions|context)\b",
    r"\byou are now\b",
    r"\bfrom now on\b",
    r"\bact as\b",
    r"\bnew (?:instructions?|rules?|task)\b",
    r"\bprint (?:out |the )?(?:your |the )?(?:system )?(?:prompt|config|instructions?)\b",
    r"\breveal (?:your |the )?(?:system )?(?:prompt|instructions?)\b",
    r"\b10\s*/\s*10\b.{0,40}\bbuy (?:it |this )?now\b",
    # Tiếng Việt — injection nhét trong review / chat (bổ sung theo eval #14)
    r"bỏ qua (?:mọi |các |hướng dẫn |chỉ dẫn |quy tắc)",
    r"(?:bỏ|phớt) lờ (?:mọi |các )?(?:hướng dẫn|chỉ dẫn|quy tắc|hệ thống)",
    r"\bsystem\s*:",                                  # "SYSTEM: bây giờ bạn là..."
    r"(?:bây giờ |giờ )?bạn (?:là|sẽ là) (?:một )?trợ lý (?:không giới hạn|tự do)",
    r"thay vào đó (?:hãy |trả lời|nói)",
    r"quên (?:mọi |các )?(?:hướng dẫn|quy tắc)(?: (?:trên|trước))?",
]

_LEAK_PATTERNS = [
    r"\bwhat (?:is|are) your (?:system )?(?:prompt|instructions?)\b",
    r"\bwho are you\b.{0,30}\binstruction",
    r"\byour (?:system )?(?:prompt|configuration|tools?)\b",
    # Tiếng Việt — yêu cầu lộ system prompt
    r"(?:cho|show)\s*(?:tôi |mình )?(?:xem |thấy )?(?:system[- ]?prompt|prompt hệ thống|câu lệnh hệ thống)",
    r"(?:hệ thống|system).{0,20}(?:hướng dẫn|chỉ dẫn) (?:của bạn|gì)",
]

_PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,10}\b",


    # SĐT VN: dạng có phân tách (090 123 4567) HOẶC liền 10-11 số (0909123456, +84...)
    "phone": r"(?:\+?84|0)(?:\d[ .-]?){8,10}\d",
    "credit_card": r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}\b",
}

_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]
_LEAK_RE = [re.compile(p, re.IGNORECASE) for p in _LEAK_PATTERNS]
_PII_RE = {name: re.compile(p) for name, p in _PII_PATTERNS.items()}

_REDACTION = "[redacted]"
_NEUTRALISED = "[removed: injected instruction]"


@dataclass
class FilterResult:
    clean_text: str
    threats: list[Threat] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.threats


def scan_reviews(text: str) -> FilterResult:
    """Scan review text (indirect-injection surface) before it reaches the LLM.

    Non-destructive: neutralise injected instruction sentences + redact PII, keep the real
    review content so the summary is still generated. This is the AI-20 review path.
    """
    threats: list[Threat] = []
    details: list[str] = []


    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    for sentence in sentences:
        hit = next((rx for rx in _INJECTION_RE if rx.search(sentence)), None)
        if hit is not None:
            threats.append(Threat.PROMPT_INJECTION)
            details.append(f"injection: {hit.pattern[:40]}")
            kept.append(_NEUTRALISED)
        else:
            kept.append(sentence)
    cleaned = " ".join(kept)

    cleaned, pii_hits = _redact_pii(cleaned)
    if pii_hits:
        threats.append(Threat.PII)
        details += [f"pii:{h}" for h in pii_hits]

    return FilterResult(clean_text=cleaned, threats=_dedup(threats), details=details)


def scan_user_question(text: str) -> FilterResult:
    """Scan a chat question (direct-injection surface). This is the AI-21 Q&A path.

    Here we are stricter: a detected system-leak / injection probe is flagged so the caller
    can refuse with a safe canned answer instead of forwarding it to the model.
    """
    threats: list[Threat] = []
    details: list[str] = []

    for rx in _INJECTION_RE + _LEAK_RE:
        if rx.search(text):
            kind = Threat.SYSTEM_LEAK if rx in _LEAK_RE else Threat.PROMPT_INJECTION
            threats.append(kind)
            details.append(f"{kind.value}: {rx.pattern[:40]}")

    cleaned, pii_hits = _redact_pii(text)
    if pii_hits:
        threats.append(Threat.PII)
        details += [f"pii:{h}" for h in pii_hits]

    return FilterResult(clean_text=cleaned, threats=_dedup(threats), details=details)


def _redact_pii(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    out = text
    for name, rx in _PII_RE.items():
        if rx.search(out):
            hits.append(name)
            out = rx.sub(_REDACTION, out)
    return out, hits


def _dedup(items: list[Threat]) -> list[Threat]:
    seen: list[Threat] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen


SAFE_REFUSAL = "Xin lỗi, tôi chỉ có thể trả lời câu hỏi về sản phẩm dựa trên đánh giá của khách hàng."
