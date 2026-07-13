"""
Lớp 3 Guardrail: Fallback & Exception Handler

Bọc lỗi cho toàn bộ luồng xử lý Agent — đảm bảo khi LLM timeout, gRPC sập,
hoặc agent rơi vào vòng lặp tool-calling vô hạn, hệ thống LUÔN trả về thông báo
thân thiện cho khách hàng thay vì crash hoặc treo Storefront.

Tham chiếu: SHOPPING_COPILOT_SPECS.md — Mục 3, Lớp 3.
"""

import logging
import functools
from typing import Dict, Any, Callable

logger = logging.getLogger("guardrails.fallback")

# ── Config: Giới hạn vòng lặp tool-calling ──
# Export biến này để agent module (Thành viên 2) dùng khi cấu hình LangChain agent
MAX_TOOL_ITERATIONS = 3


class MaxIterationsExceeded(Exception):
    """
    Exception khi LLM vượt quá số lần gọi tool cho phép.
    Agent module sẽ raise exception này khi đếm đủ MAX_TOOL_ITERATIONS.
    """
    pass


class CopilotServiceError(Exception):
    """
    Exception tổng quát cho các lỗi nghiệp vụ của Shopping Copilot.
    Dùng khi muốn trả thông báo lỗi cụ thể mà không cần phân loại exception gốc.
    """
    def __init__(self, message: str, error_code: str = "COPILOT_ERROR"):
        super().__init__(message)
        self.error_code = error_code


def make_error_response(message: str, error_code: str = "INTERNAL_ERROR") -> Dict[str, Any]:
    """
    Tạo response lỗi theo format chuẩn.
    Tất cả response lỗi trong Shopping Copilot tuân theo format này.
    """
    return {
        "status": "error",
        "message": message,
        "error_code": error_code,
    }


# ── Bảng ánh xạ Exception → Thông báo thân thiện ──
# Mỗi entry: (loại exception, error_code, message cho khách hàng)
_ERROR_HANDLERS = []


def _register_grpc_handlers():
    """Đăng ký handler cho lỗi gRPC — gọi lazy lần đầu khi cần."""
    global _ERROR_HANDLERS
    try:
        import grpc

        def _handle_grpc_error(e: Exception) -> Dict[str, Any]:
            """Phân loại lỗi gRPC và trả thông báo tương ứng."""
            if not isinstance(e, grpc.RpcError):
                return None

            code = e.code()
            if code == grpc.StatusCode.UNAVAILABLE:
                return make_error_response(
                    "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau giây lát.",
                    "SERVICE_UNAVAILABLE"
                )
            elif code == grpc.StatusCode.DEADLINE_EXCEEDED:
                return make_error_response(
                    "Yêu cầu mất quá nhiều thời gian xử lý. Vui lòng thử lại.",
                    "TIMEOUT"
                )
            else:
                return make_error_response(
                    f"Có lỗi khi kết nối dịch vụ nội bộ. Vui lòng thử lại sau.",
                    f"GRPC_{code.name}"
                )

        _ERROR_HANDLERS.append((grpc.RpcError, _handle_grpc_error))
    except ImportError:
        pass  # grpc không được cài — bỏ qua handler này


def _register_openai_handlers():
    """Đăng ký handler cho lỗi OpenAI/LLM — gọi lazy lần đầu khi cần."""
    global _ERROR_HANDLERS
    try:
        import openai

        def _handle_openai_error(e: Exception) -> Dict[str, Any]:
            if isinstance(e, openai.RateLimitError):
                return make_error_response(
                    "Hệ thống AI đang bận, vui lòng thử lại sau ít phút.",
                    "LLM_RATE_LIMIT"
                )
            elif isinstance(e, openai.APITimeoutError):
                return make_error_response(
                    "Hệ thống AI phản hồi chậm, vui lòng thử lại.",
                    "LLM_TIMEOUT"
                )
            elif isinstance(e, openai.APIError):
                return make_error_response(
                    "Hệ thống AI gặp sự cố tạm thời. Vui lòng thử lại sau.",
                    "LLM_API_ERROR"
                )
            return None

        _ERROR_HANDLERS.append((openai.OpenAIError, _handle_openai_error))
    except ImportError:
        pass  # openai không được cài — bỏ qua handler này


# ── Đăng ký tất cả handlers ──
_handlers_registered = False


def _ensure_handlers():
    """Đăng ký handlers lần đầu — lazy init để tránh import error lúc load module."""
    global _handlers_registered
    if not _handlers_registered:
        _register_grpc_handlers()
        _register_openai_handlers()
        _handlers_registered = True


def handle_exception(e: Exception) -> Dict[str, Any]:
    """
    Phân loại exception và trả về response thân thiện.

    Được gọi trực tiếp hoặc qua decorator @with_fallback.
    """
    _ensure_handlers()

    # Custom exceptions của Copilot
    if isinstance(e, MaxIterationsExceeded):
        logger.warning(f"[FALLBACK] Agent vượt quá {MAX_TOOL_ITERATIONS} vòng lặp tool-calling")
        return make_error_response(
            f"Không thể xử lý yêu cầu này sau {MAX_TOOL_ITERATIONS} lần thử. "
            f"Vui lòng thử diễn đạt câu hỏi theo cách khác.",
            "MAX_ITERATIONS_EXCEEDED"
        )

    if isinstance(e, CopilotServiceError):
        return make_error_response(e.args[0], e.error_code)

    # Quét qua các handler đã đăng ký
    for exc_type, handler_fn in _ERROR_HANDLERS:
        if isinstance(e, exc_type):
            result = handler_fn(e)
            if result is not None:
                return result

    # Fallback cuối cùng — exception không xác định
    logger.error(f"[FALLBACK] Unhandled exception: {type(e).__name__}: {e}", exc_info=True)
    return make_error_response(
        "Đã có lỗi xảy ra. Vui lòng thử lại sau hoặc liên hệ hỗ trợ.",
        "UNKNOWN_ERROR"
    )


def with_fallback(fn: Callable) -> Callable:
    """
    Decorator bọc quanh hàm xử lý request chính của Agent.

    Mọi exception xảy ra bên trong đều bị bắt và chuyển thành
    response lỗi thân thiện — KHÔNG BAO GIỜ để lỗi thoát ra ngoài.

    Cách dùng (Thành viên 2 sẽ gắn vào agent):
        @with_fallback
        def process_chat_request(user_message, session_id):
            ...  # logic gọi LLM + tool
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return handle_exception(e)
    return wrapper
