from server import demo_pb2 as pb
from server import demo_pb2_grpc as grpc_svc


_RATES: dict[str, dict[str, tuple[int, int]]] = {
    "USD": {
        "EUR": (0, 850000000),
        "GBP": (0, 750000000),
        "VND": (25000, 0),
        "JPY": (150, 0),
        "USD": (1, 0),
    },
    "EUR": {"USD": (1, 180000000)},
    "GBP": {"USD": (1, 330000000)},
    "VND": {"USD": (0, 40000)},
    "JPY": {"USD": (0, 6700000)},
}

_SUPPORTED = ["USD", "EUR", "GBP", "VND", "JPY"]


class DemoCurrencyService(grpc_svc.CurrencyServiceServicer):

    async def GetSupportedCurrencies(self, request, context):
        return pb.GetSupportedCurrenciesResponse(currency_codes=_SUPPORTED)

    async def Convert(self, request, context):
        from_obj = getattr(request, 'from', None) if hasattr(request, 'from') else None
        from_code = "USD"
        amount_units = 1
        amount_nanos = 0
        if from_obj is not None:
            from_code = from_obj.currency_code
            amount_units = from_obj.units
            amount_nanos = from_obj.nanos

        to_code = request.to_code

        if from_code == to_code:
            return pb.Money(currency_code=to_code, units=amount_units, nanos=amount_nanos)

        if from_code in _RATES and to_code in _RATES[from_code]:
            rate_units, rate_nanos = _RATES[from_code][to_code]
            total_nanos = amount_units * 1_000_000_000 + amount_nanos
            rate_total_nanos = rate_units * 1_000_000_000 + rate_nanos
            result_nanos = total_nanos * rate_total_nanos // 1_000_000_000
            return pb.Money(
                currency_code=to_code,
                units=result_nanos // 1_000_000_000,
                nanos=result_nanos % 1_000_000_000,
            )

        return pb.Money(currency_code=to_code, units=amount_units, nanos=amount_nanos)
