"""
tools/currency_tool.py — convert_currency_tool

Backend: CurrencyService gRPC (demo.proto)
"""

import json
import logging

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import CURRENCY_ADDR

logger = logging.getLogger("tools.currency")


@tool
def convert_currency_tool(from_currency: str, to_currency: str,
                           amount: float = 0, amount_units: int = 0) -> str:
    """
    Quy đổi giá tiền giữa các đơn vị tiền tệ.
    Trả về JSON: {status, from, to, amount, converted, rate}
    """
    if amount < 0:
        return json.dumps({"status": "error", "message": "Số tiền không được âm."})
    actual_amount = amount if amount > 0 else float(amount_units)
    if actual_amount <= 0:
        return json.dumps({"status": "error", "message": "Số tiền phải lớn hơn 0."})

    try:
        with grpc.insecure_channel(CURRENCY_ADDR) as ch:
            stub = demo_pb2_grpc.CurrencyServiceStub(ch)
            resp = stub.Convert(demo_pb2.CurrencyConversionRequest(
                from_=demo_pb2.Money(
                    currency_code=from_currency.upper(),
                    units=int(actual_amount),
                    nanos=int((actual_amount % 1) * 1e9),
                ),
                to_code=to_currency.upper(),
            ))

            converted = resp.units + resp.nanos / 1e9
            rate = round(converted / actual_amount, 4) if actual_amount > 0 else 0

            return json.dumps({
                "status": "success",
                "from": from_currency.upper(),
                "to": to_currency.upper(),
                "amount": actual_amount,
                "converted": round(converted, 2),
                "rate": rate,
            }, ensure_ascii=False)

    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        logger.error("[convert_currency_tool] gRPC %s | from=%s to=%s amount=%s | %s",
                      code, from_currency, to_currency, amount, e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ quy đổi tiền tệ không khả dụng."})
    except Exception as e:
        logger.error("[convert_currency_tool] error | from=%s to=%s amount=%s | %s",
                      from_currency, to_currency, amount, e, exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="convert_currency_tool",
    description="Quy đổi giá tiền giữa các đơn vị tiền tệ (USD, VND, EUR, ...).",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "from_currency": {"type": "string", "description": "Mã tiền tệ nguồn (VD: USD)"},
        "to_currency": {"type": "string", "description": "Mã tiền tệ đích (VD: VND)"},
        "amount": {"type": "number", "description": "Số tiền cần quy đổi"},
    }, "required": ["from_currency", "to_currency"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "from": {"type": "string"}, "to": {"type": "string"},
        "amount": {"type": "number"}, "converted": {"type": "number"},
        "rate": {"type": "number"},
    }},
    examples=[{"input": {"from_currency": "USD", "to_currency": "VND", "amount": 50},
               "output": {"status": "success", "converted": 1250000, "rate": 25000}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=convert_currency_tool)
