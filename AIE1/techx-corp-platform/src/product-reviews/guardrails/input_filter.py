"""
Lớp 2 Guardrail: Bộ lọc Đầu vào — Kiến trúc 2 tầng (Regex + Bedrock Guardrails)

Tầng 1 — Regex Static Rules (~1ms, miễn phí):
    Quét chuỗi văn bản đầu vào qua 28+ regex pattern EN+VI.
    Có Unicode normalization (NFC) để xử lý dấu tiếng Việt nhất quán.
    Nếu phát hiện pattern tấn công → từ chối ngay, không gửi gì vào LLM.

Tầng 2 — AWS Bedrock Guardrails (~200ms, semantic):
    Dùng ApplyGuardrail API để phân tích ngữ nghĩa đa ngôn ngữ.
    Bắt các cuộc tấn công mà Regex không cover: paraphrase, ngôn ngữ lạ,
    code-switching, cách viết lóng.
"""

import re
import os
import logging
import unicodedata
from dataclasses import dataclass
from typing import List, Tuple, Optional

logger = logging.getLogger("guardrails.input_filter")


@dataclass
class InputFilterResult:
    """Kết quả kiểm tra đầu vào."""
    is_safe: bool
    blocked_reason: str         # Rỗng nếu is_safe=True
    original_input: str         # Giữ nguyên input gốc để ghi log audit
    blocked_tier: str = ""      # "REGEX" | "BEDROCK" | "" — cho metric/audit


# ─── Hàm chuẩn hoá Unicode ───

def _normalize_text(text: str) -> str:
    """
    Chuẩn hoá Unicode NFC và lowercase.
    Đảm bảo dấu tiếng Việt (ã, ắ, ổ...) luôn ở dạng nhất quán.
    """
    return unicodedata.normalize("NFC", text.lower())


# ─── Định nghĩa các Pattern tấn công theo danh mục ───

# Mỗi tuple: (regex pattern, tên loại tấn công để ghi log)
ATTACK_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # ══════════════════════════════════════
    # Danh mục 1: Override hệ thống
    # ══════════════════════════════════════

    # ── Tiếng Anh ──
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

    # ── Tiếng Việt ──
    (re.compile(r"(bỏ\s*qua|quên|bỏ|hãy\s*quên)\s*(tất\s*cả\s*)?(các\s*)?(chỉ\s*dẫn|hướng\s*dẫn|luật|quy\s*tắc|lệnh|instructions?)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"không\s*(được\s*)?(tuân\s*theo|nghe\s*theo|làm\s*theo)\s*(các\s*)?(chỉ\s*dẫn|hướng\s*dẫn|luật|quy\s*tắc)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"ghi\s*đè\s*(các\s*)?(quy\s*tắc|luật|hướng\s*dẫn|chỉ\s*dẫn)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),

    # ══════════════════════════════════════
    # Danh mục 2: Tiết lộ System Prompt
    # ══════════════════════════════════════

    # ── Tiếng Anh ──
    (re.compile(r"(show|print|display|reveal|tell)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?|rules|configuration)", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),
    (re.compile(r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions?|rules)", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),
    (re.compile(r"repeat\s+(the\s+)?(text|words?|message)\s+above", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),

    # ── Tiếng Việt ──
    (re.compile(r"(tiết\s*lộ|hiển\s*thị|cho\s*(tôi\s*)?biết|in|đọc|xem)\s*(system\s*prompt|chỉ\s*dẫn\s*hệ\s*thống|hướng\s*dẫn\s*nội\s*bộ|prompt\s*hệ\s*thống)", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),
    (re.compile(r"(nội\s*dung|cấu\s*hình)\s*(system\s*prompt|hệ\s*thống)\s*(là\s*gì|của\s*bạn)", re.IGNORECASE),
     "PROMPT_DISCLOSURE"),

    # ══════════════════════════════════════
    # Danh mục 3: Jailbreak DAN-style
    # ══════════════════════════════════════

    # ── Tiếng Anh ──
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

    # ── Tiếng Việt ──
    (re.compile(r"(đóng\s*vai|giả\s*vờ|giả\s*làm|đóng\s*làm|hãy\s*làm)\s*(là|thành|như)\s*", re.IGNORECASE),
     "JAILBREAK"),
    (re.compile(r"(bây\s*giờ|từ\s*giờ)\s*(bạn|mày|m)\s*(là|hãy\s*là)\s*", re.IGNORECASE),
     "JAILBREAK"),
    (re.compile(r"(chế\s*độ|mode)\s*(nhà\s*phát\s*triển|developer|không\s*giới\s*hạn|tự\s*do)", re.IGNORECASE),
     "JAILBREAK"),

    # ══════════════════════════════════════
    # Danh mục 4: Delimiter Injection
    # ══════════════════════════════════════
    (re.compile(r"\n\s*(system|assistant)\s*:", re.IGNORECASE),
     "DELIMITER_INJECTION"),
    (re.compile(r"<\|?(system|assistant|im_start)\|?>", re.IGNORECASE),
     "DELIMITER_INJECTION"),
    (re.compile(r"\[INST\]|\[/INST\]|\\<<SYS\\>>", re.IGNORECASE),
     "DELIMITER_INJECTION"),

    # ══════════════════════════════════════
    # Danh mục 5: Trích xuất PII / dữ liệu nhạy cảm
    # ══════════════════════════════════════

    # ── Tiếng Anh ──
    (re.compile(r"(give|show|list|extract|leak)\s+(me\s+)?(all\s+)?(customer|user)?\s*(credit\s*card|password|ssn|social\s*security|api\s*key|secret)", re.IGNORECASE),
     "PII_EXTRACTION"),

    # ── Tiếng Việt ──
    (re.compile(r"(lấy|xuất|rò\s*rỉ|cho\s*xem|liệt\s*kê|đưa)\s*(tất\s*cả\s*)?(thông\s*tin|mật\s*khẩu|tài\s*khoản|thẻ\s*tín\s*dụng|thẻ\s*ngân\s*hàng|password|credit\s*card)", re.IGNORECASE),
     "PII_EXTRACTION"),

    # ══════════════════════════════════════
    # Danh mục 6: Off-topic / Lạm dụng AI
    # ══════════════════════════════════════

    # ── Tiếng Anh ──
    (re.compile(r"(how\s+to|teach\s+me(\s+to)?|explain)\s+(hack|exploit|attack|crack|bypass\s+security)", re.IGNORECASE),
     "OFF_TOPIC"),
    (re.compile(r"(write|create|generate)\s+(a\s+)?(malware|virus|exploit|phishing|ransomware)", re.IGNORECASE),
     "OFF_TOPIC"),

    # ── Tiếng Việt ──
    (re.compile(r"(cách|hướng\s*dẫn|dạy)\s*(hack|tấn\s*công|khai\s*thác\s*lỗ\s*hổng|bẻ\s*khoá|phá\s*hệ\s*thống)", re.IGNORECASE),
     "OFF_TOPIC"),

    # ══════════════════════════════════════
    # Danh mục bổ sung: Ngăn chặn Checkout / Thanh toán
    # ══════════════════════════════════════
    (re.compile(r"(thanh\s*toán|checkout|đặt\s*hàng|chốt\s*đơn|pay)", re.IGNORECASE),
     "UNAUTHORIZED_ACTION"),

    # ══════════════════════════════════════
    # Danh mục 7: Encoding Evasion
    # (phát hiện kẻ tấn công mã hoá payload
    #  bằng base64/hex/unicode escape để bypass regex)
    # ══════════════════════════════════════
    (re.compile(r"base64[:\s]|aWdub3Jl|SWdub3Jl", re.IGNORECASE),
     "ENCODING_EVASION"),
    # aWdub3Jl = base64("ignore"), SWdub3Jl = base64("Ignore")
    (re.compile(r"\\x[0-9a-f]{2}(\\x[0-9a-f]{2}){3,}", re.IGNORECASE),
     "ENCODING_EVASION"),
    (re.compile(r"\\u[0-9a-f]{4}(\\u[0-9a-f]{4}){3,}", re.IGNORECASE),
     "ENCODING_EVASION"),
    (re.compile(r"eval\s*\(|exec\s*\(|import\s+os|subprocess", re.IGNORECASE),
     "ENCODING_EVASION"),

    # ══════════════════════════════════════
    # Bổ sung: System Override nâng cao
    # ══════════════════════════════════════
    (re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"(từ\s*bây\s*giờ|bắt\s*đầu\s*từ\s*giờ)\s*(hãy|phải|bạn\s*sẽ)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
    (re.compile(r"(please\s+)?stop\s+being\s+(a\s+)?(shopping|helpful)", re.IGNORECASE),
     "SYSTEM_OVERRIDE"),
]

# ── Thông báo từ chối thân thiện cho từng loại ──
BLOCK_MESSAGES = {
    "SYSTEM_OVERRIDE": "Yêu cầu này không được phép vì có chứa nội dung cố gắng thay đổi hành vi của hệ thống.",
    "PROMPT_DISCLOSURE": "Tôi không thể chia sẻ thông tin cấu hình nội bộ của hệ thống.",
    "JAILBREAK": "Yêu cầu này không được phép vì có chứa nội dung giả mạo danh tính hệ thống.",
    "DELIMITER_INJECTION": "Yêu cầu này không được phép vì có chứa ký tự điều khiển đáng ngờ.",
    "PII_EXTRACTION": "Tôi không thể cung cấp thông tin nhạy cảm của khách hàng hoặc hệ thống.",
    "OFF_TOPIC": "Tôi chỉ hỗ trợ mua sắm. Vui lòng đặt câu hỏi liên quan đến sản phẩm hoặc đơn hàng.",
    "UNAUTHORIZED_ACTION": "Tôi là trợ lý ảo và không có quyền thực hiện thanh toán hay chốt đơn. Vui lòng tự thực hiện quy trình checkout trên trang web.",
    "ENCODING_EVASION": "Yêu cầu này không được phép vì có chứa nội dung được mã hoá đáng ngờ.",
    "BEDROCK_GUARDRAIL": "Yêu cầu này đã bị hệ thống bảo mật phát hiện là không phù hợp.",
}


# ═══════════════════════════════════════════════════
# Tầng 1: Regex Pattern Matching (Fast-path)
# ═══════════════════════════════════════════════════

def check_input(user_message: str) -> InputFilterResult:
    """
    Tầng 1 — Quét tin nhắn qua Regex pattern (EN + VI).

    Bao gồm Unicode normalization (NFC) trước khi matching.
    """
    if not user_message or not user_message.strip():
        return InputFilterResult(
            is_safe=False,
            blocked_reason="Tin nhắn trống, vui lòng nhập nội dung.",
            original_input=user_message or "",
            blocked_tier="REGEX",
        )

    # Chuẩn hoá Unicode NFC cho tiếng Việt
    normalized = _normalize_text(user_message)

    # Quét qua từng pattern (dùng cả bản gốc và bản normalized)
    for pattern, attack_type in ATTACK_PATTERNS:
        if pattern.search(user_message) or pattern.search(normalized):
            reason = BLOCK_MESSAGES.get(attack_type, "Yêu cầu bị từ chối vì lý do bảo mật.")

            logger.warning(
                f"[INPUT_FILTER] BLOCKED | tier=REGEX | type={attack_type} | "
                f"input_preview={user_message[:80]!r}"
            )

            return InputFilterResult(
                is_safe=False,
                blocked_reason=reason,
                original_input=user_message,
                blocked_tier="REGEX",
            )

    # Tất cả pattern đều không khớp → tin nhắn sạch (tầng Regex)
    return InputFilterResult(
        is_safe=True,
        blocked_reason="",
        original_input=user_message,
        blocked_tier="",
    )


# ═══════════════════════════════════════════════════
# Tầng 2: AWS Bedrock Guardrails (Semantic Check)
# ═══════════════════════════════════════════════════

# Config — set từ biến môi trường hoặc sau khi tạo guardrail trên AWS
_BEDROCK_GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID", "")
_BEDROCK_GUARDRAIL_VERSION = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
_BEDROCK_GUARDRAIL_REGION = os.getenv("BEDROCK_GUARDRAIL_REGION") or os.getenv("BEDROCK_REGION") or "ap-southeast-1"

# Lazy init client — tránh import lỗi khi boto3 chưa cài
_bedrock_client = None


def _get_bedrock_client():
    """Lazy init boto3 bedrock-runtime client."""
    global _bedrock_client
    if _bedrock_client is None:
        try:
            import boto3
            _bedrock_client = boto3.client("bedrock-runtime", region_name=_BEDROCK_GUARDRAIL_REGION)
        except Exception as e:
            logger.error(f"[INPUT_FILTER] Không thể khởi tạo Bedrock client: {e}")
            return None
    return _bedrock_client


def check_input_bedrock(user_message: str) -> InputFilterResult:
    """
    Tầng 2 — Quét tin nhắn qua AWS Bedrock Guardrails (semantic, đa ngôn ngữ).

    Bắt các cuộc tấn công mà Regex không cover:
      - Paraphrase tinh vi
      - Ngôn ngữ không có trong bộ regex (FR, DE, JP, AR, ...)
      - Code-switching (trộn EN+VI)
      - Cách viết lóng, viết tắt

    Nếu BEDROCK_GUARDRAIL_ID chưa được cấu hình → bỏ qua (cho phép đi tiếp).
    """
    # Nếu chưa cấu hình guardrail ID → skip tầng này
    if not _BEDROCK_GUARDRAIL_ID:
        logger.debug("[INPUT_FILTER] Bedrock Guardrails chưa cấu hình — skip tầng 2")
        return InputFilterResult(
            is_safe=True,
            blocked_reason="",
            original_input=user_message,
            blocked_tier="",
        )

    client = _get_bedrock_client()
    if client is None:
        # Không kết nối được Bedrock → fail-open (cho phép đi tiếp, tầng khác bảo vệ)
        logger.warning("[INPUT_FILTER] Bedrock client unavailable — fail-open, skip tầng 2")
        return InputFilterResult(
            is_safe=True,
            blocked_reason="",
            original_input=user_message,
            blocked_tier="",
        )

    try:
        response = client.apply_guardrail(
            guardrailIdentifier=_BEDROCK_GUARDRAIL_ID,
            guardrailVersion=_BEDROCK_GUARDRAIL_VERSION,
            source="INPUT",
            content=[{"text": {"text": user_message}}],
        )

        action = response.get("action", "NONE")

        if action == "GUARDRAIL_INTERVENED":
            # Bedrock phát hiện nội dung vi phạm
            # Trích xuất lý do từ response (nếu có)
            outputs = response.get("outputs", [])
            bedrock_reason = outputs[0].get("text", "") if outputs else ""

            logger.warning(
                f"[INPUT_FILTER] BLOCKED | tier=BEDROCK | action={action} | "
                f"reason={bedrock_reason[:100]!r} | input_preview={user_message[:80]!r}"
            )

            return InputFilterResult(
                is_safe=False,
                blocked_reason=BLOCK_MESSAGES["BEDROCK_GUARDRAIL"],
                original_input=user_message,
                blocked_tier="BEDROCK",
            )

        # NONE → cho phép
        return InputFilterResult(
            is_safe=True,
            blocked_reason="",
            original_input=user_message,
            blocked_tier="",
        )

    except Exception as e:
        # Bedrock lỗi → fail-open
        logger.error(f"[INPUT_FILTER] Bedrock Guardrails error (fail-open): {e}")
        return InputFilterResult(
            is_safe=True,
            blocked_reason="",
            original_input=user_message,
            blocked_tier="",
        )
