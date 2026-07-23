"""
tools/shipping_tool.py — get_shipping_quote_tool

Backend: ShippingService HTTP/gRPC
"""

import json
import logging

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import SHIPPING_ADDR

logger = logging.getLogger("tools.shipping")


@tool
def get_shipping_quote_tool(
    address: str = "",
    destination: str = "",
    street: str = "",
    city: str = "",
    country: str = "VN",
    zip_code: str = "",
    state: str = "",
) -> str:
    """
    Xem phí vận chuyển đến một địa chỉ (nội địa Việt Nam).
    Trả về JSON: {status, destination, cost, days}
    """
    # Normalize address
    dest = address or destination or f"{street}, {city}, {country}".strip(", ")
    if not dest.strip():
        return json.dumps({"status": "error", "message": "Vui lòng cung cấp địa chỉ giao hàng."})

    try:
        # Dùng gRPC nếu địa chỉ là host:port (không có http://)
        shipping_host = SHIPPING_ADDR.replace("http://", "").replace("https://", "")
        with grpc.insecure_channel(shipping_host) as ch:
            stub = demo_pb2_grpc.ShippingServiceStub(ch)
            resp = stub.GetQuote(demo_pb2.GetQuoteRequest(
                address=demo_pb2.Address(
                    street_address=street or address,
                    city=city,
                    state=state,
                    country=country or "VN",
                    zip_code=zip_code,
                ),
                items=[],
            ))
            cost = resp.cost_usd
            cost_str = f"${cost.units}.{cost.nanos // 10_000_000:02d}"
            days = getattr(resp, "shipping_days", getattr(resp, "days", 3))

            return json.dumps({
                "status": "success",
                "destination": dest,
                "cost": cost_str,
                "days": days,
            }, ensure_ascii=False)

    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        logger.error("[get_shipping_quote_tool] gRPC %s | dest=%s | %s", code, dest, e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ vận chuyển tạm thời không khả dụng."})
    except Exception as e:
        logger.error("[get_shipping_quote_tool] error | dest=%s | %s", dest, e, exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_shipping_quote_tool",
    description="Xem phí vận chuyển và thời gian giao hàng đến một địa chỉ nội địa Việt Nam.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "address": {"type": "string", "description": "Địa chỉ đầy đủ (ưu tiên)"},
        "city": {"type": "string"}, "country": {"type": "string", "default": "VN"},
    }, "required": []},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "destination": {"type": "string"},
        "cost": {"type": "string", "description": "Phí ship (VD: $8.99)"},
        "days": {"type": "integer"},
    }},
    examples=[{"input": {"address": "123 Nguyễn Huệ, Q1, TP.HCM"},
               "output": {"status": "success", "cost": "$8.99", "days": 3}}],
    retry_config={"max_retries": 1, "backoff": [1.0]},
), fn=get_shipping_quote_tool)
