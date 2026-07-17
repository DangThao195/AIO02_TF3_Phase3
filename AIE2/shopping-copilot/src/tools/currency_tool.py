# tools/currency_tool.py
from __future__ import annotations

import grpc
from langchain_core.tools import tool

import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc
from src.tools.service_config import CURRENCY_ADDR


@tool
def convert_currency_tool(
    from_currency: str,
    to_currency: str,
    amount: float | int | None = None,
    amount_units: int | None = None,
) -> str:
    """
    Convert money between currencies.
    Accepts both `amount` and `amount_units` for compatibility.
    """
    value = amount if amount is not None else amount_units
    if value is None:
        return "Lỗi: thiếu số tiền cần quy đổi."

    try:
        amount_value = float(value)
    except (TypeError, ValueError):
        return "Lỗi: số tiền cần quy đổi không hợp lệ."

    channel = grpc.insecure_channel(CURRENCY_ADDR)
    stub = demo_pb2_grpc.CurrencyServiceStub(channel)

    try:
        units = int(amount_value)
        nanos = int(round((amount_value - units) * 1_000_000_000))
        if nanos >= 1_000_000_000:
            units += 1
            nanos -= 1_000_000_000
        if nanos < 0:
            nanos = 0

        money_from = demo_pb2.Money(
            currency_code=from_currency,
            units=units,
            nanos=nanos,
        )

        request = demo_pb2.CurrencyConversionRequest()
        getattr(request, "from").CopyFrom(money_from)
        request.to_code = to_currency
        response = stub.Convert(request)

        converted = response.units + (response.nanos / 1_000_000_000)
        return (
            f"{amount_value:g} {from_currency} tương đương khoảng "
            f"{converted:,.2f} {to_currency}."
        )
    except grpc.RpcError as e:
        return f"Lỗi hệ thống khi thực hiện quy đổi tiền tệ (gRPC): {e.details()}"
    finally:
        channel.close()
