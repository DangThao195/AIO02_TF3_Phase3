# tools/cart_tool.py
import json
import grpc
from langchain_core.tools import tool
import protos.demo_pb2 as demo_pb2
import protos.demo_pb2_grpc as demo_pb2_grpc

from guardrails.confirmation import request_confirmation

import os
CART_ADDR = os.getenv("CART_ADDR", "cart:7070")

@tool
def add_to_cart_tool(user_id: str, product_id: str, quantity: int) -> str:
    """
    Hữu ích khi người dùng yêu cầu thêm sản phẩm vào giỏ hàng của họ.
    Yêu cầu đầu vào: user_id, product_id, và quantity (số lượng).
    """
    if int(quantity) <= 0:
        return "Lỗi: Số lượng sản phẩm thêm vào giỏ phải lớn hơn 0."

    confirmation = request_confirmation(
        user_id=user_id,
        action="AddItem",
        action_params={"product_id": product_id, "quantity": quantity},
    )

    if confirmation.status == "DENIED":
        return json.dumps({
            "status": "error",
            "message": "Hành động thêm vào giỏ hàng bị từ chối.",
        })

    if confirmation.status == "PENDING":
        return json.dumps({
            "status": "pending",
            "message": (f"Vui lòng xác nhận thêm {quantity} sản phẩm '{product_id}' vào giỏ hàng."),
            "token": confirmation.confirmation_token,
            "action_data": {
                "user_id": user_id,
                "action": "AddItem",
                "params": {"product_id": product_id, "quantity": quantity},
            },
        })

    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    try:
        cart_item = demo_pb2.CartItem(product_id=product_id, quantity=int(quantity))
        request = demo_pb2.AddItemRequest(user_id=user_id, item=cart_item)
        stub.AddItem(request)
        return f"Thành công: Đã thêm {quantity} sản phẩm '{product_id}' vào giỏ hàng."
    except grpc.RpcError as e:
        return f"Lỗi hệ thống khi tương tác với dịch vụ Giỏ hàng (gRPC): {e.details()}"
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