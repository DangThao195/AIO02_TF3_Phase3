# tools/currency_tool.py
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.tools.service_config import CURRENCY_ADDR

@tool
def convert_currency_tool(from_currency: str, to_currency: str, amount_units: int) -> str:
    """
    Hữu ích khi khách hàng muốn quy đổi giá tiền hoặc xem chi phí sản phẩm theo các đơn vị tiền tệ khác nhau.
    Yêu cầu: from_currency, to_currency, amount_units.
    """
    channel = grpc.insecure_channel(CURRENCY_ADDR)
    stub = demo_pb2_grpc.CurrencyServiceStub(channel)
    
    try:
        # Khởi tạo đối tượng Money đúng cấu trúc proto
        money_from = demo_pb2.Money(
            currency_code=from_currency,
            units=int(amount_units),
            nanos=0
        )

        # Sử dụng đúng tên trường trong protobuf: field `from`
        request = demo_pb2.CurrencyConversionRequest()
        getattr(request, 'from').CopyFrom(money_from)
        request.to_code = to_currency
        response = stub.Convert(request)

        # Định dạng chuỗi tiền tệ đầu ra mượt mà
        formatted_nanos = f"{response.nanos // 10000000:02d}"
        return f"Kết quả quy đổi lấy từ Cloud AWS: {amount_units} {from_currency} tương đương với {response.units}.{formatted_nanos} {to_currency}."
        
    except grpc.RpcError as e:
        return f"Lỗi hệ thống khi thực hiện quy đổi tiền tệ (gRPC): {e.details()}"
    finally:
        channel.close()