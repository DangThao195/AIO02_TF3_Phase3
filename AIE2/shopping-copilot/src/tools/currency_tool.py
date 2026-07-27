"""
tools/currency_tool.py — convert_currency_tool

Backend: CurrencyService gRPC (demo.proto).
Khi VND xuất hiện, dùng USD làm trung gian — không gọi gRPC trực tiếp với VND.
"""

import json
import logging

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import CURRENCY_ADDR

logger = logging.getLogger("tools.currency")

_USD_TO_VND = 25000.0


def _grpc_convert(from_cur: str, to_cur: str, amount: float) -> tuple[float, float]:
    with grpc.insecure_channel(CURRENCY_ADDR) as ch:
        stub = demo_pb2_grpc.CurrencyServiceStub(ch)
        resp = stub.Convert(demo_pb2.CurrencyConversionRequest(**{
            "from": demo_pb2.Money(
                currency_code=from_cur,
                units=int(amount),
                nanos=int((amount % 1) * 1e9),
            ),
            "to_code": to_cur,
        }))
        converted = resp.units + resp.nanos / 1e9
        rate = round(converted / amount, 4) if amount > 0 else 0
        return converted, rate


def _convert_with_vnd(from_cur: str, to_cur: str, amount: float) -> str:
    if from_cur == "VND" and to_cur == "VND":
        return json.dumps({"status": "error", "message": "Không thể quy đổi VND sang VND."},
                          ensure_ascii=False)

    if from_cur == "USD" and to_cur == "VND":
        converted = round(amount * _USD_TO_VND, 2)
        return json.dumps({"status": "success", "from": "USD", "to": "VND",
                           "amount": amount, "converted": converted, "rate": _USD_TO_VND},
                          ensure_ascii=False)

    if from_cur == "VND" and to_cur == "USD":
        converted = round(amount / _USD_TO_VND, 2)
        rate = round(1 / _USD_TO_VND, 6)
        return json.dumps({"status": "success", "from": "VND", "to": "USD",
                           "amount": amount, "converted": converted, "rate": rate},
                          ensure_ascii=False)

    if from_cur == "VND":
        usd_amount = amount / _USD_TO_VND
        converted_usd, _ = _grpc_convert("USD", to_cur, round(usd_amount, 2))
        rate = round(converted_usd / amount, 6) if amount > 0 else 0
        return json.dumps({"status": "success", "from": "VND", "to": to_cur,
                           "amount": amount, "converted": round(converted_usd, 2), "rate": rate},
                          ensure_ascii=False)

    if to_cur == "VND":
        converted_usd, rate_x_usd = _grpc_convert(from_cur, "USD", amount)
        vnd_amount = round(converted_usd * _USD_TO_VND, 2)
        rate = round(rate_x_usd * _USD_TO_VND, 4) if rate_x_usd > 0 else 0
        return json.dumps({"status": "success", "from": from_cur, "to": "VND",
                           "amount": amount, "converted": vnd_amount, "rate": rate},
                          ensure_ascii=False)

    return json.dumps({"status": "error", "message": "Lỗi xử lý VND."},
                      ensure_ascii=False)


@tool
def convert_currency_tool(from_currency: str, to_currency: str,
                           amount: float = 0, amount_units: int = 0) -> str:
    """
    Quy đổi giá tiền giữa các đơn vị tiền tệ.
    Nếu có VND, dùng USD làm trung gian (không gọi gRPC với VND).
    Trả về JSON: {status, from, to, amount, converted, rate}
    """
    if amount < 0:
        return json.dumps({"status": "error", "message": "Số tiền không được âm."})
    actual_amount = amount if amount > 0 else float(amount_units)
    if actual_amount <= 0:
        return json.dumps({"status": "error", "message": "Số tiền phải lớn hơn 0."})

    from_up = from_currency.upper()
    to_up = to_currency.upper()

    if from_up == "VND" or to_up == "VND":
        return _convert_with_vnd(from_up, to_up, actual_amount)

    try:
        converted, rate = _grpc_convert(from_up, to_up, actual_amount)
        return json.dumps({"status": "success", "from": from_up, "to": to_up,
                           "amount": actual_amount, "converted": round(converted, 2),
                           "rate": rate}, ensure_ascii=False)
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
    }, "required": ["from_currency", "to_currency", "amount"]},
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
