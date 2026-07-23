"""
tools/out_of_scope_tool.py — respond_out_of_scope_tool

Tool chuyên trả lời các câu hỏi ngoài phạm vi mua sắm.
Không gọi backend, chỉ trả response cứng (hardcoded).
"""

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger("tools.out_of_scope")

_RESPONSES = {
    "greeting": (
        "Xin chào! Tôi là trợ lý mua sắm của TechX Corp. "
        "Tôi có thể giúp bạn tìm kiếm sản phẩm, xem giỏ hàng, thêm sản phẩm vào giỏ, "
        "xem đánh giá, quy đổi tiền tệ, hoặc tính phí vận chuyển. "
        "Bạn cần tôi hỗ trợ gì ạ?"
    ),
    "weather": (
        "Tôi là trợ lý mua sắm, chuyên hỗ trợ các câu hỏi về sản phẩm và giỏ hàng. "
        "Tôi không có khả năng xem thông tin thời tiết. "
        "Bạn có muốn tôi tìm kiếm sản phẩm hoặc kiểm tra giỏ hàng không?"
    ),
    "math": (
        "Tôi được thiết kế để hỗ trợ mua sắm trực tuyến, không phải để tính toán. "
        "Bạn có cần tôi tìm kiếm sản phẩm, xem giỏ hàng, hoặc quy đổi tiền tệ không?"
    ),
    "name": (
        "Tôi là trợ lý mua sắm của TechX Corp! "
        "Bạn có thể gọi tôi là TechX Assistant. "
        "Tôi có thể giúp gì cho bạn hôm nay?"
    ),
    "news": (
        "Tôi chỉ hỗ trợ các câu hỏi liên quan đến mua sắm. "
        "Tôi không thể cung cấp tin tức hay thông tin thời sự. "
        "Bạn cần tìm sản phẩm hay xem giỏ hàng?"
    ),
    "sports": (
        "Tôi là trợ lý mua sắm, không phải chuyên gia thể thao. "
        "Tôi có thể giúp bạn tìm kiếm sản phẩm thể thao nếu bạn muốn!"
    ),
    "health": (
        "Tôi chỉ hỗ trợ mua sắm trực tuyến, không thể tư vấn sức khỏe. "
        "Bạn cần tìm sản phẩm hay xem giỏ hàng?"
    ),
    "history": (
        "Tôi là trợ lý mua sắm, không có kiến thức về lịch sử. "
        "Bạn có muốn tìm kiếm sản phẩm hoặc xem giỏ hàng không?"
    ),
    "science": (
        "Tôi chuyên hỗ trợ mua sắm, không phải khoa học. "
        "Bạn cần tôi tìm kiếm sản phẩm hay kiểm tra giỏ hàng?"
    ),
    "entertainment": (
        "Tôi là trợ lý mua sắm, không cung cấp thông tin giải trí. "
        "Bạn có muốn xem các sản phẩm mới nhất của chúng tôi không?"
    ),
    "personal_info": (
        "Tôi không thể chia sẻ thông tin cá nhân hay nội bộ. "
        "Tôi chỉ hỗ trợ các câu hỏi liên quan đến mua sắm. "
        "Bạn cần giúp đỡ gì về sản phẩm hay giỏ hàng?"
    ),
    "general": (
        "Xin lỗi, tôi chỉ có thể hỗ trợ các câu hỏi liên quan đến mua sắm. "
        "Bạn cần tìm kiếm sản phẩm, xem giỏ hàng, thêm sản phẩm vào giỏ, "
        "xem đánh giá, quy đổi tiền tệ, hay tính phí vận chuyển?"
    ),
}


@tool
def respond_out_of_scope_tool(reason: str) -> str:
    """
    Dành cho các câu hỏi KHÔNG liên quan đến mua sắm.
    Dùng tool này khi người dùng hỏi về chủ đề ngoài phạm vi mua sắm:
    chào hỏi, thời tiết, toán học, tên tuổi, tin tức, thể thao,
    sức khỏe, lịch sử, khoa học, giải trí, thông tin cá nhân, v.v.
    KHÔNG dùng tool này cho câu hỏi mua sắm.
    Trả về JSON: {status, response}
    reason: one of greeting|weather|math|name|news|sports|health|history|science|entertainment|personal_info|general
    """
    try:
        response = _RESPONSES.get(reason, _RESPONSES["general"])
        return json.dumps({
            "status": "success",
            "response": response,
            "reason": reason,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[respond_out_of_scope_tool] error | reason=%s | %s", reason, e, exc_info=True)
        return json.dumps({
            "status": "error",
            "message": "Xin lỗi, tôi không thể xử lý yêu cầu này.",
        })


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="respond_out_of_scope_tool",
    description=(
        "Dành cho các câu hỏi KHÔNG liên quan đến mua sắm. "
        "Dùng tool này khi người dùng hỏi về chủ đề ngoài phạm vi mua sắm: "
        "chào hỏi, thời tiết, toán học, tên tuổi, tin tức, thể thao, "
        "sức khỏe, lịch sử, khoa học, giải trí, thông tin cá nhân, v.v. "
        "KHÔNG dùng tool này cho câu hỏi mua sắm."
    ),
    is_write=False,
    input_schema={"type": "object", "properties": {
        "reason": {
            "type": "string",
            "enum": ["greeting", "weather", "math", "name", "news",
                     "sports", "health", "history", "science",
                     "entertainment", "personal_info", "general"],
            "description": "Phân loại lý do câu hỏi ngoài phạm vi"
        }
    }, "required": ["reason"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "response": {"type": "string"},
        "reason": {"type": "string"},
    }},
    examples=[
        {"input": {"reason": "greeting"},
         "output": {"status": "success",
                     "response": "Xin chào! Tôi là trợ lý mua sắm của TechX Corp..."}},
        {"input": {"reason": "weather"},
         "output": {"status": "success",
                     "response": "Tôi là trợ lý mua sắm, chuyên hỗ trợ các câu hỏi về sản phẩm..."}},
    ],
    retry_config={"max_retries": 1},
), fn=respond_out_of_scope_tool)
