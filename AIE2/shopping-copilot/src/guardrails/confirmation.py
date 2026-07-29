"""
Lớp 1 Guardrail: Cổng xác nhận hành động ghi (Confirmation Gate)

Chặn đứng hành vi tự ý ghi dữ liệu của AI Agent (Excessive-Agency).
Sử dụng Token stateless (HMAC-signed) để không phụ thuộc vào RAM server —
hỗ trợ multi-replica khi deploy lên EKS.

Tham chiếu: SHOPPING_COPILOT_SPECS.md — Mục 3, Lớp 1.
"""

import hmac
import hashlib
import json
import time
import base64
import os
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger("guardrails.confirmation")

# ── Secret key dùng để ký Token ──
# Production: đọc từ biến môi trường hoặc Kubernetes Secret
# Local dev: dùng fallback mặc định (KHÔNG dùng ở production)
_SECRET_KEY = os.environ.get(
    "COPILOT_CONFIRMATION_SECRET",
    "tf3-copilot-dev-secret-change-in-prod"
).encode("utf-8")

# Token hết hạn sau 5 phút (300 giây) — đủ thời gian cho user bấm nút
TOKEN_EXPIRY_SECONDS = 300

# ── Danh sách hành động bị CẤM TUYỆT ĐỐI — AI không được gọi dưới bất kỳ điều kiện nào ──
DENIED_ACTIONS = frozenset([
    "EmptyCart",    # Xóa sạch giỏ hàng
    "PlaceOrder",  # Tự ý đặt hàng
    "Charge",      # Tự ý thanh toán
])

# ── Danh sách hành động CẦN XÁC NHẬN từ user trước khi thực thi ──
CONFIRM_REQUIRED_ACTIONS = frozenset([
    "AddItem",     # Thêm sản phẩm vào giỏ
])


@dataclass
class ConfirmationResult:
    """Kết quả từ Confirmation Gate."""
    status: str                       # "PENDING" | "DENIED" | "APPROVED"
    message: str                      # Thông báo cho user/FE hiển thị
    confirmation_token: Optional[str] # Token gửi về FE (chỉ có khi PENDING)
    action_data: Optional[Dict]       # Dữ liệu hành động (để FE hiển thị chi tiết)


def _sign_payload(payload_bytes: bytes) -> str:
    """Tạo chữ ký HMAC-SHA256 cho payload."""
    return hmac.new(_SECRET_KEY, payload_bytes, hashlib.sha256).hexdigest()


def generate_confirmation_token(
    user_id: str,
    action: str,
    params: Dict[str, Any]
) -> str:
    """
    Sinh Token stateless cho một hành động ghi cần xác nhận.

    Token = base64(payload_json) + "." + hmac_signature
    Payload chứa: user_id, action, params, exp (thời điểm hết hạn).
    """
    payload = {
        "user_id": user_id,
        "action": action,
        "params": params,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8")
    signature = _sign_payload(payload_b64.encode("utf-8"))

    return f"{payload_b64}.{signature}"


def verify_confirmation_token(token: str) -> tuple[bool, Optional[Dict]]:
    """
    Xác thực Token do Frontend gửi lại sau khi user bấm nút "Xác nhận".

    Returns:
        (is_valid, action_data):
            - (True, {...})  → Token hợp lệ, chưa hết hạn, chữ ký đúng.
            - (False, None)  → Token bị sửa, hết hạn, hoặc không đúng định dạng.
    """
    try:
        parts = token.split(".")
        if len(parts) != 2:
            logger.warning("[CONFIRMATION] Token format invalid — thiếu dấu chấm phân cách")
            return False, None

        payload_b64, provided_signature = parts

        # Kiểm tra chữ ký — chống giả mạo token
        expected_signature = _sign_payload(payload_b64.encode("utf-8"))
        if not hmac.compare_digest(provided_signature, expected_signature):
            logger.warning("[CONFIRMATION] Token signature mismatch — có thể bị giả mạo")
            return False, None

        # Giải mã payload
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        action_data = json.loads(payload_json)

        # Kiểm tra hết hạn
        if time.time() > action_data.get("exp", 0):
            logger.info("[CONFIRMATION] Token expired")
            return False, None

        return True, action_data

    except Exception as e:
        logger.error(f"[CONFIRMATION] Token verification error: {e}")
        return False, None


def request_confirmation(
    user_id: str,
    action: str,
    action_params: Dict[str, Any]
) -> ConfirmationResult:
    """
    Hàm chính — được tool gọi khi AI muốn thực hiện hành động ghi.

    Luồng xử lý:
        1. action nằm trong DENIED_ACTIONS → TỪ CHỐI NGAY (không tạo token)
        2. action nằm trong CONFIRM_REQUIRED_ACTIONS → tạo token, trả PENDING
        3. action không nằm trong danh sách nào → cho qua (hành động đọc)

    Args:
        user_id:       ID người dùng đang chat.
        action:        Tên hành động (ví dụ: "AddItem", "EmptyCart").
        action_params: Tham số đi kèm (ví dụ: {"product_id": "XYZ", "quantity": 2}).

    Returns:
        ConfirmationResult với status tương ứng.
    """
    # ── Lớp 1: Deny-list — CHẶN TUYỆT ĐỐI ──
    if action in DENIED_ACTIONS:
        logger.warning(
            f"[CONFIRMATION] DENIED | action={action} | user={user_id} | "
            f"reason=action_in_deny_list"
        )
        return ConfirmationResult(
            status="DENIED",
            message=f"Hành động '{action}' bị cấm tuyệt đối. "
                    f"AI không được phép tự thực hiện thao tác này.",
            confirmation_token=None,
            action_data=None,
        )

    # ── Lớp 2: Confirm-list — CẦN XÁC NHẬN ──
    if action in CONFIRM_REQUIRED_ACTIONS:
        token = generate_confirmation_token(user_id, action, action_params)

        logger.info(
            f"[CONFIRMATION] PENDING | action={action} | user={user_id} | "
            f"params={action_params}"
        )
        return ConfirmationResult(
            status="PENDING",
            message=f"Vui lòng xác nhận hành động: {action} "
                    f"(sản phẩm: {action_params.get('product_id', '?')}, "
                    f"số lượng: {action_params.get('quantity', '?')})",
            confirmation_token=token,
            action_data=action_params,
        )

    # ── Hành động không nằm trong danh sách chặn → cho qua ──
    return ConfirmationResult(
        status="APPROVED",
        message="Hành động được phép thực thi.",
        confirmation_token=None,
        action_data=action_params,
    )


# ── Alias cho cart_tool.py (compat với interface cũ của đồng đội) ──
# cart_tool.py gọi: is_confirmed = trigger_confirmation_gate(user_id, action_text)
# Hàm này wrap request_confirmation và trả bool:
#   True  = APPROVED (được phép thực thi ngay — chỉ với read actions)
#   False = PENDING/DENIED (cần dừng lại, tool trả thông báo cho agent)
def trigger_confirmation_gate(user_id: str, action_text: str) -> bool:
    """
    Compatibility alias dùng bởi cart_tool.py.
    Luôn trả False vì 'AddItem' thuộc CONFIRM_REQUIRED_ACTIONS.
    Agent sẽ nhận thông báo pending và tạo HMAC token riêng qua react_loop.
    """
    result = request_confirmation(user_id, "AddItem", {"action_text": action_text})
    return result.status == "APPROVED"