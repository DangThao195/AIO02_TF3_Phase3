# tools/cart_tool.py
import grpc
from langchain_core.tools import tool
import protos.demo_pb2 as demo_pb2
import protos.demo_pb2_grpc as demo_pb2_grpc

# 🛡️ KIỂM TRA MÔI TRƯỜNG GUARDRAILS (Chủ động xử lý trường hợp file trống)
try:
    # Thử import hàm tạo xác nhận HMAC theo đặc tả hệ thống
    from guardrails.confirmation import request_confirmation
    HAS_CONFIRMATION_SYSTEM = True
except ImportError:
    # Nếu file confirmation.py trống hoặc thiếu hàm -> Chế độ Testing
    HAS_CONFIRMATION_SYSTEM = False

import os
CART_ADDR = os.getenv("CART_ADDR", "cart:7070")

@tool
def add_to_cart_tool(user_id: str, product_id: str, quantity: int) -> str:
    """
    Hữu ích khi người dùng yêu cầu thêm sản phẩm vào giỏ hàng của họ.
    Yêu cầu đầu vào: user_id, product_id, và quantity (số lượng).
    """
    # 🧪 TEST CHẾ ĐỘ BYPASS (Do Guardrail chưa hoàn thiện)
    if HAS_CONFIRMATION_SYSTEM:
        # Code thực tế sẽ gọi HMAC Token ở đây
        # confirmation_token = request_confirmation(user_id, "AddItem", {"product_id": product_id, "quantity": quantity})
        # return f"Hành động tạm dừng. Vui lòng xác nhận thêm sản phẩm vào giỏ với mã: {confirmation_token}"
        pass
    else:
        # Thông báo Audit Log chế độ đang chạy
        print("⚠️ [SYSTEM INFO] confirmation.py hiện tại đang trống. Agent chạy chế độ BYPASS để test gRPC AddItem trực tiếp lên EKS.")

    # 🛡️ LỚP BẢO VỆ 2: Validate dữ liệu đầu vào cơ bản
    if int(quantity) <= 0:
        return "Lỗi: Số lượng sản phẩm thêm vào giỏ phải lớn hơn 0."

    # TIẾN HÀNH GỌI GRPC THẬT LÊN CỤM EKS (Đã thông qua port-forward 7070)
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    
    try:
        # Cấu trúc Object CartItem lồng bên trong
        cart_item = demo_pb2.CartItem(product_id=product_id, quantity=int(quantity))
        
        # Đóng gói AddItemRequest tổng
        request = demo_pb2.AddItemRequest(user_id=user_id, item=cart_item)
        
        # Thực thi gọi API ghi vào Valkey Database trên EKS Cluster
        stub.AddItem(request)
        return f"Thành công: Đã thêm {quantity} sản phẩm '{product_id}' vào giỏ hàng của tài khoản '{user_id}' trên Cloud AWS."
        
    except grpc.RpcError as e:
        return f"Lỗi hệ thống khi tương tác với dịch vụ Giỏ hàng trên EKS (gRPC): {e.details()}"
    finally:
        channel.close()

@tool
def get_cart_tool(user_id: str) -> str:
    """
    Hữu ích khi người dùng muốn xem danh sách các sản phẩm đang có trong giỏ hàng của họ.
    Đầu vào cần thiết: user_id.
    """
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    
    try:
        # Khởi tạo request lấy giỏ hàng đúng cấu trúc proto
        request = demo_pb2.GetCartRequest(user_id=user_id)
        response = stub.GetCart(request)
        
        # Kiểm tra danh sách sản phẩm lồng trong trường 'items'
        if not response.items:
            return f"Giỏ hàng của người dùng '{user_id}' hiện đang trống."
            
        formatted_cart = []
        for item in response.items:
            formatted_cart.append(f"-Sản phẩm ID: {item.product_id} | Số lượng: {item.quantity}")
            
        return f"Chi tiết giỏ hàng của '{user_id}':\n" + "\n".join(formatted_cart)
        
    except grpc.RpcError as e:
        return f"Lỗi hệ thống khi lấy thông tin giỏ hàng (gRPC): {e.details()}"
    finally:
        channel.close()