# tools/currency_tool.py
import json
import logging
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.tools.service_config import CURRENCY_ADDR

logger = logging.getLogger("tools.currency_tool")

# Danh sách currency codes được backend gRPC hỗ trợ (lấy từ GetSupportedCurrencies)
_SUPPORTED_CURRENCIES: set[str] = set()
_SUPPORTED_LIST: list[str] = []  # sorted list for display


def _get_supported_currencies() -> set[str]:
    """Lazy-load supported currencies from the gRPC service."""
    global _SUPPORTED_CURRENCIES, _SUPPORTED_LIST
    if _SUPPORTED_CURRENCIES:
        return _SUPPORTED_CURRENCIES
    try:
        channel = grpc.insecure_channel(CURRENCY_ADDR)
        stub = demo_pb2_grpc.CurrencyServiceStub(channel)
        resp = stub.GetSupportedCurrencies(demo_pb2.Empty())
        codes = set(resp.currency_codes)
        channel.close()
        if codes:
            _SUPPORTED_CURRENCIES = codes
            _SUPPORTED_LIST = sorted(codes)
            logger.info(f"[CURRENCY] Loaded {len(codes)} supported currencies: {_SUPPORTED_LIST}")
    except Exception as e:
        logger.warning(f"[CURRENCY] Could not load supported currencies: {e}")
        # Hard-coded fallback from known service capabilities
        _SUPPORTED_CURRENCIES = {
            "AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK",
            "EUR", "GBP", "HKD", "HRK", "HUF", "IDR", "ILS", "INR",
            "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD", "PHP",
            "PLN", "RON", "RUB", "SEK", "SGD", "THB", "TRY", "USD", "ZAR"
        }
        _SUPPORTED_LIST = sorted(_SUPPORTED_CURRENCIES)
    return _SUPPORTED_CURRENCIES


@tool
def convert_currency_tool(from_currency: str, to_currency: str, amount_units: int) -> str:
    """
    Quy đổi tiền tệ: chuyển đổi số tiền từ một loại đơn vị tiền tệ sang đơn vị tiền tệ khác.
    Hữu ích khi khách hàng hỏi giá theo tiền tệ khác (EUR, JPY, THB, ...).

    Tham số:
    - from_currency: mã tiền tệ nguồn, ví dụ "USD"
    - to_currency: mã tiền tệ đích, ví dụ "EUR", "JPY", "THB"
    - amount_units: số tiền cần chuyển đổi (phần nguyên, đơn vị tiền tệ)

    Lưu ý: VND không được hỗ trợ. Các mã hỗ trợ: AUD, EUR, GBP, JPY, KRW, THB, SGD, MYR, IDR, PHP, v.v.

    Returns JSON: {"status", "from_currency", "to_currency", "result_units", "result_nanos", "message"}
    """
    supported = _get_supported_currencies()

    # Normalize to uppercase
    from_code = (from_currency or "").strip().upper()
    to_code = (to_currency or "").strip().upper()

    # Validate from_currency
    if from_code not in supported:
        similar = [c for c in _SUPPORTED_LIST if c.startswith(from_code[:2])][:5]
        return json.dumps({
            "status": "error",
            "error": f"Currency '{from_code}' is not supported by the currency service.",
            "supported_currencies": _SUPPORTED_LIST,
            "suggestions": similar or _SUPPORTED_LIST[:10],
        })

    # Validate to_currency
    if to_code not in supported:
        similar = [c for c in _SUPPORTED_LIST if c.startswith(to_code[:2])][:5]
        return json.dumps({
            "status": "unsupported_currency",
            "error": f"Currency '{to_code}' is not supported. Please use one of the supported codes.",
            "requested_to_currency": to_code,
            "supported_currencies": _SUPPORTED_LIST,
            "suggestions": similar or _SUPPORTED_LIST[:10],
        })

    # Call gRPC Convert
    channel = grpc.insecure_channel(CURRENCY_ADDR)
    stub = demo_pb2_grpc.CurrencyServiceStub(channel)

    try:
        money_from = demo_pb2.Money(
            currency_code=from_code,
            units=int(amount_units),
            nanos=0,
        )
        request = demo_pb2.CurrencyConversionRequest()
        getattr(request, "from").CopyFrom(money_from)
        request.to_code = to_code

        response = stub.Convert(request)

        # nanos: 1_000_000_000 = 1 unit → format 2 decimal places
        nanos_val = response.nanos if response.nanos >= 0 else -response.nanos
        cents = round(nanos_val / 10_000_000)
        formatted_nanos = f"{cents:02d}"

        logger.info(f"[CURRENCY] Converted {amount_units} {from_code} → {response.units}.{formatted_nanos} {to_code}")

        return json.dumps({
            "status": "success",
            "from_currency": from_code,
            "to_currency": to_code,
            "amount_units": amount_units,
            "result_units": response.units,
            "result_nanos": formatted_nanos,
            "message": (
                f"{amount_units} {from_code} = "
                f"{response.units}.{formatted_nanos} {to_code}"
            ),
        })

    except grpc.RpcError as e:
        logger.error(f"[CURRENCY] gRPC error: {e.details()}")
        return json.dumps({
            "status": "error",
            "error": f"Currency service error: {e.details()}",
            "from_currency": from_code,
            "to_currency": to_code,
        })
    finally:
        channel.close()