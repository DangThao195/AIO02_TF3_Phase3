"""
Guardrail bổ sung: Output Filter — lọc phản hồi LLM trước khi trả cho khách.

Chặn Case 4: LLM phản hồi chứa PII, thông tin nội bộ hệ thống, hoặc nội dung nhạy cảm.
Chạy SAU khi LLM trả response, TRƯỚC khi gửi về Frontend.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Tuple

logger = logging.getLogger("guardrails.output_filter")


@dataclass
class OutputFilterResult:
    """Kết quả lọc output."""
    is_clean: bool
    filtered_response: str       # Response đã redact (nếu cần)
    redacted_items: List[str]    # Danh sách các loại PII/nhạy cảm bị redact


# ── Pattern PII cần redact (thay bằng [REDACTED]) ──
PII_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Email
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
     "EMAIL"),
    # Số điện thoại (Việt Nam + quốc tế)
    (re.compile(r"(?:\+?84|0)\d{9,10}"),
     "PHONE_VN"),
    (re.compile(r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
     "PHONE_US"),
    # Credit card number (16 chữ số, có thể có dấu - hoặc khoảng trắng)
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
     "CREDIT_CARD"),
    # SSN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
     "SSN"),
]

# ── Pattern thông tin nội bộ hệ thống cần redact ──
SYSTEM_INFO_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # IP address nội bộ
    (re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
     "INTERNAL_IP"),
    # Kubernetes service DNS
    (re.compile(r"\b[\w-]+\.[\w-]+\.svc\.cluster\.local(?::\d+)?\b"),
     "K8S_SERVICE_DNS"),
    # Connection string / DSN
    (re.compile(r"(?:postgres|mysql|redis|mongodb)://[^\s]+", re.IGNORECASE),
     "CONNECTION_STRING"),
    # AWS ARN
    (re.compile(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[\w/+=,.@-]+"),
     "AWS_ARN"),
    # API key pattern (dãy dài chữ + số, thường prefix sk- hoặc key-)
    (re.compile(r"\b(?:sk|api|key|token|secret)[-_][A-Za-z0-9]{20,}\b", re.IGNORECASE),
     "API_KEY"),
]


def filter_output(llm_response: str) -> OutputFilterResult:
    """
    Quét và redact thông tin nhạy cảm trong phản hồi của LLM.

    Args:
        llm_response: Chuỗi text trả về từ LLM sau khi tổng hợp.

    Returns:
        OutputFilterResult:
            - is_clean=True nếu không có gì bị redact.
            - filtered_response chứa text đã thay thế PII bằng [REDACTED].
    """
    if not llm_response:
        return OutputFilterResult(is_clean=True, filtered_response="", redacted_items=[])

    filtered = llm_response
    redacted_items = []

    # Quét PII
    for pattern, pii_type in PII_PATTERNS:
        if pattern.search(filtered):
            filtered = pattern.sub(f"[{pii_type}_REDACTED]", filtered)
            redacted_items.append(pii_type)
            logger.warning(f"[OUTPUT_FILTER] REDACTED | type={pii_type}")

    # Quét thông tin hệ thống
    for pattern, info_type in SYSTEM_INFO_PATTERNS:
        if pattern.search(filtered):
            filtered = pattern.sub(f"[{info_type}_REDACTED]", filtered)
            redacted_items.append(info_type)
            logger.warning(f"[OUTPUT_FILTER] REDACTED | type={info_type}")

    return OutputFilterResult(
        is_clean=len(redacted_items) == 0,
        filtered_response=filtered,
        redacted_items=redacted_items,
    )
