"""
Guardrail bổ sung: Tool Allow-list + User Isolation + Parameter Validation

Chặn 3 lỗ hổng:
  - Case 1: LLM gọi tool lạ ngoài danh sách cho phép
  - Case 2: LLM tự bịa user_id để truy cập cart người khác
  - Case 3: Tham số phá hoại (quantity quá lớn, product_id injection)
"""

import re
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

logger = logging.getLogger("guardrails.tool_validator")

# ── Tool Allow-list: CHỈ những tool này được phép thực thi ──
# Nếu LLM hallucinate ra tool "delete_database" → chặn ngay
ALLOWED_TOOLS = frozenset([
    "search_products_tool",          # deprecated — giữ để không break tool cũ
    "search_products_v2",            # multi-strategy search (EN + VI)
    "add_to_cart_tool",              # thêm vào giỏ hàng (write — cần L4 confirm)
    "get_cart_tool",                 # xem giỏ hàng
    "get_product_reviews_tool",      # xem đánh giá sản phẩm
    "get_recommendations_tool",      # gợi ý sản phẩm
    "convert_currency_tool",         # quy đổi tiền tệ
    "get_shipping_quote_tool",       # phí vận chuyển
])

# ── Giới hạn tham số ──
MAX_QUANTITY = 99        # Không ai mua 100+ cái cùng lúc
MIN_QUANTITY = 1
PRODUCT_ID_PATTERN = re.compile(r"^[A-Z0-9]{8,12}$")  # Format chuẩn của TechX: ví dụ "OLJCESPC7Z"


@dataclass
class ToolValidationResult:
    """Kết quả kiểm tra tool call."""
    is_valid: bool
    blocked_reason: str
    violation_type: str  # "UNKNOWN_TOOL" | "USER_ISOLATION" | "PARAM_INVALID" | ""


def validate_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    session_user_id: str,
) -> ToolValidationResult:
    """
    Kiểm tra một lời gọi tool trước khi thực thi.

    Args:
        tool_name:       Tên tool mà LLM muốn gọi.
        tool_args:       Tham số LLM truyền vào tool.
        session_user_id: user_id thật từ session (Frontend gửi lên), KHÔNG phải do LLM tự điền.

    Returns:
        ToolValidationResult — is_valid=True nếu qua hết kiểm tra.
    """
    # ── Case 1: Tool Allow-list ──
    if tool_name not in ALLOWED_TOOLS:
        logger.warning(
            f"[TOOL_VALIDATOR] BLOCKED_UNKNOWN_TOOL | tool={tool_name} | "
            f"user={session_user_id}"
        )
        return ToolValidationResult(
            is_valid=False,
            blocked_reason=f"Công cụ '{tool_name}' không nằm trong danh sách được phép. "
                           f"Chỉ được dùng: {', '.join(sorted(ALLOWED_TOOLS))}.",
            violation_type="UNKNOWN_TOOL",
        )

    # ── Case 2: User Isolation — chặn truy cập cross-user ──
    arg_user_id = tool_args.get("user_id")
    if arg_user_id is not None and arg_user_id != session_user_id:
        logger.warning(
            f"[TOOL_VALIDATOR] BLOCKED_CROSS_USER | tool={tool_name} | "
            f"session_user={session_user_id} | attempted_user={arg_user_id}"
        )
        return ToolValidationResult(
            is_valid=False,
            blocked_reason="Bạn chỉ được thao tác trên giỏ hàng của chính mình.",
            violation_type="USER_ISOLATION",
        )

    # ── Case 3: Parameter Bounds ──

    # Kiểm tra quantity
    quantity = tool_args.get("quantity")
    if quantity is not None:
        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            return ToolValidationResult(
                is_valid=False,
                blocked_reason=f"Số lượng '{quantity}' không hợp lệ. Vui lòng nhập số nguyên.",
                violation_type="PARAM_INVALID",
            )

        if qty < MIN_QUANTITY or qty > MAX_QUANTITY:
            logger.warning(
                f"[TOOL_VALIDATOR] BLOCKED_QUANTITY | tool={tool_name} | "
                f"quantity={qty} | allowed=[{MIN_QUANTITY}-{MAX_QUANTITY}]"
            )
            return ToolValidationResult(
                is_valid=False,
                blocked_reason=f"Số lượng phải từ {MIN_QUANTITY} đến {MAX_QUANTITY}. "
                               f"Bạn yêu cầu: {qty}.",
                violation_type="PARAM_INVALID",
            )

    # Kiểm tra product_id format (chống SQL injection / garbage input)
    product_id = tool_args.get("product_id")
    if product_id is not None:
        if not PRODUCT_ID_PATTERN.match(str(product_id)):
            logger.warning(
                f"[TOOL_VALIDATOR] BLOCKED_PRODUCT_ID | tool={tool_name} | "
                f"product_id={product_id!r}"
            )
            return ToolValidationResult(
                is_valid=False,
                blocked_reason=f"Mã sản phẩm '{product_id}' không đúng định dạng hệ thống.",
                violation_type="PARAM_INVALID",
            )

    # ── Tất cả kiểm tra OK ──
    return ToolValidationResult(is_valid=True, blocked_reason="", violation_type="")
