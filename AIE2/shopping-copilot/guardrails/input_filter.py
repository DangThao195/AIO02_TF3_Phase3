"""
Lớp 2 Guardrail: Bộ lọc Prompt-Injection Đầu vào (Input Guardrail Middleware)

Quét chuỗi văn bản đầu vào (user message) TRƯỚC khi đưa vào mảng messages gửi sang LLM.
Nếu phát hiện pattern tấn công → từ chối xử lý ngay, không gửi gì vào LLM.

Tham chiếu: SHOPPING_COPILOT_SPECS.md — Mục 3, Lớp 2.
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger("guardrails.input_filter")


@dataclass
class InputFilterResult:
    """Kết quả kiểm tra đầu vào."""
    is_safe: bool
    blocked_reason: str  # Rỗng nếu is_safe=True
    original_input: str  # Giữ nguyên input gốc để ghi log audit


# ─── Định nghĩa các Pattern tấn công theo danh mục ───

# Mỗi tuple: (regex pattern, tên loại tấn công để ghi log)
ATTACK_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # ── Danh mục 1: Override hệ thống ──
    (re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"forget\s+(all\s+)?(your\s+)?instructions?", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"disregard\s+(all\s+)?(above|previous|prior)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"override\s+(your\s+)?(safety|rules|guidelines|restrictions)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"do\s+not\s+follow\s+(your\s+)?(rules|instructions|guidelines)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),

    # ── Danh mục 2: Tiết lộ System Prompt ──
    (re.compile(r"(show|print|display|reveal|tell)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?|rules|configuration)", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),
    (re.compile(r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions?|rules)", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),
    (re.compile(r"repeat\s+(the\s+)?(text|words?|message)\s+above", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),

    # ── Danh mục 3: Jailbreak DAN-style ──
    (re.compile(r"(act|pretend|behave|respond)\s+(as|like)\s+(if\s+)?(you\s+)?(are|were)\s+", re.IGNORECASE),
     "JAILBREAK"),
    (re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
     "JAILBREAK"),
    (re.compile(r"\bDAN\b", re.IGNORECASE),
     "JAILBREAK"),
    (re.compile(r"jailbreak", re.IGNORECASE),
     "JAILBREAK"),
    (re.compile(r"developer\s+mode", re.IGNORECASE),
     "JAILBREAK"),

    # ── Danh mục 4: Delimiter Injection (giả mạo role trong conversation) ──
    (re.compile(r"\n\s*(system|assistant)\s*:", re.IGNORECASE),
     "DELIMITER_INJECTION"),
    (re.compile(r"<\|?(system|assistant|im_start)\|?>", re.IGNORECASE),
     "DELIMITER_INJECTION"),
    (re.compile(r"\[INST\]|\[/INST\]|\<\<SYS\>\>", re.IGNORECASE),
     "DELIMITER_INJECTION"),

    # ── Danh mục 5: Trích xuất PII / dữ liệu nhạy cảm ──
    (re.compile(r"(give|show|list|extract|leak)\s+(me\s+)?(all\s+)?(customer|user)?\s*(credit\s*card|password|ssn|social\s*security|api\s*key|secret)", re.IGNORECASE),
     "PII_EXTRACTION"),
]

# ── Thông báo từ chối thân thiện cho từng loại ──
BLOCK_MESSAGES = {
    "SYSTEM_OVERRIDE": "Yêu cầu này không được phép vì có chứa nội dung cố gắng thay đổi hành vi của hệ thống.",
    "PROMPT_DISCLOSURE": "Tôi không thể chia sẻ thông tin cấu hình nội bộ của hệ thống.",
    "JAILBREAK": "Yêu cầu này không được phép vì có chứa nội dung giả mạo danh tính hệ thống.",
    "DELIMITER_INJECTION": "Yêu cầu này không được phép vì có chứa ký tự điều khiển đáng ngờ.",
    "PII_EXTRACTION": "Tôi không thể cung cấp thông tin nhạy cảm của khách hàng hoặc hệ thống.",
}


def check_input(user_message: str) -> InputFilterResult:
    """
    Quét tin nhắn của người dùng qua tất cả các pattern tấn công.

    Args:
        user_message: Chuỗi văn bản thô từ khách hàng nhập vào chatbox.

    Returns:
        InputFilterResult:
            - is_safe=True  → Tin nhắn sạch, cho phép đi tiếp vào LLM.
            - is_safe=False → Tin nhắn bị chặn, kèm lý do trong blocked_reason.
    """
    if not user_message or not user_message.strip():
        return InputFilterResult(
            is_safe=False,
            blocked_reason="Tin nhắn trống, vui lòng nhập nội dung.",
            original_input=user_message or ""
        )

    # Quét qua từng pattern
    for pattern, attack_type in ATTACK_PATTERNS:
        if pattern.search(user_message):
            reason = BLOCK_MESSAGES.get(attack_type, "Yêu cầu bị từ chối vì lý do bảo mật.")

            # Log để AIOps đếm metric sau này
            logger.warning(
                f"[INPUT_FILTER] BLOCKED | type={attack_type} | "
                f"input_preview={user_message[:80]!r}"
            )

            return InputFilterResult(
                is_safe=False,
                blocked_reason=reason,
                original_input=user_message
            )

    # Tất cả pattern đều không khớp → tin nhắn sạch
    return InputFilterResult(
        is_safe=True,
        blocked_reason="",
        original_input=user_message
    )
