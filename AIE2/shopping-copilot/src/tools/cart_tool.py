# tools/cart_tool.py
"""Cart tools — add, view, check items. All return normalized JSON.
Cart policy: only add (with confirmation) and view are allowed. No remove/update/checkout."""

import json
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.guardrails.confirmation import request_confirmation

from src.tools.service_config import CART_ADDR, CATALOG_ADDR


@tool
def check_cart_item_tool(user_id: str, product_id: str) -> str:
    """
    Hữu ích khi người dùng muốn kiểm tra xem một sản phẩm có đang có trong giỏ hàng hay không.
    Trả về kết quả rõ ràng để agent có thể dùng trực tiếp mà không cần suy đoán.
    Returns JSON: {"status", "found", "product_id", "quantity"}
    """
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)
    try:
        request = demo_pb2.GetCartRequest(user_id=user_id)
        response = stub.GetCart(request)

        for item in getattr(response, "items", []) or []:
            if getattr(item, "product_id", "") == product_id:
                return json.dumps({
                    "status": "success",
                    "found": True,
                    "product_id": product_id,
                    "quantity": item.quantity,
                })

        return json.dumps({
            "status": "success",
            "found": False,
            "product_id": product_id,
            "quantity": 0,
        })
    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "error": f"gRPC error: {e.details()}",
            "found": False,
            "product_id": product_id,
            "quantity": 0,
        })
    finally:
        channel.close()


@tool
def add_to_cart_tool(user_id: str, product_id: str, quantity: int) -> str:
    """
    Hữu ích khi người dùng yêu cầu thêm sản phẩm vào giỏ hàng của họ.
    Yêu cầu đầu vào: user_id, product_id, và quantity (số lượng).
    Returns JSON: {"status": "pending"|"success"|"error", ...}
    """
    if int(quantity) <= 0:
        return json.dumps({
            "status": "error",
            "error": "Quantity must be greater than 0.",
        })

    confirmation = request_confirmation(
        user_id=user_id,
        action="AddItem",
        action_params={"product_id": product_id, "quantity": quantity},
    )

    if confirmation.status == "DENIED":
        return json.dumps({
            "status": "error",
            "error": "Add to cart action was denied by policy.",
        })

    if confirmation.status == "PENDING":
        product_name = product_id
        try:
            cat_channel = grpc.insecure_channel(CATALOG_ADDR)
            cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_channel)
            p_req = demo_pb2.GetProductRequest(id=product_id)
            p_res = cat_stub.GetProduct(p_req)
            if p_res.name:
                product_name = p_res.name
            cat_channel.close()
        except Exception:
            pass

        return json.dumps({
            "status": "pending",
            "message": f"Please confirm adding {quantity} of product '{product_name}' to your cart.",
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
        return json.dumps({
            "status": "success",
            "product_id": product_id,
            "quantity": quantity,
            "message": f"Successfully added {quantity} of '{product_id}' to cart.",
        })
    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "error": f"gRPC error: {e.details()}",
        })
    finally:
        channel.close()


@tool
def get_cart_tool(user_id: str) -> str:
    """
    Hữu ích khi người dùng muốn xem danh sách các sản phẩm đang có trong giỏ hàng của họ.
    Đầu vào cần thiết: user_id.
    Returns JSON: {"status", "user_id", "items": [{"product_id","quantity"}], "total_items"}
    """
    channel = grpc.insecure_channel(CART_ADDR)
    stub = demo_pb2_grpc.CartServiceStub(channel)

    try:
        request = demo_pb2.GetCartRequest(user_id=user_id)
        response = stub.GetCart(request)

        if not response.items:
            return json.dumps({
                "status": "empty",
                "user_id": user_id,
                "items": [],
                "total_items": 0,
            })

        items = []
        product_names = {}
        
        # Try to resolve product names via Catalog Service
        if response.items:
            cat_channel = grpc.insecure_channel(CATALOG_ADDR)
            try:
                cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_channel)
                for item in response.items:
                    try:
                        p_req = demo_pb2.GetProductRequest(id=item.product_id)
                        p_res = cat_stub.GetProduct(p_req)
                        product_names[item.product_id] = p_res.name
                    except Exception:
                        pass
            finally:
                cat_channel.close()

        for item in response.items:
            items.append({
                "product_id": item.product_id,
                "product_name": product_names.get(item.product_id, "Unknown Product"),
                "quantity": item.quantity,
            })

        return json.dumps({
            "status": "success",
            "user_id": user_id,
            "items": items,
            "total_items": len(items),
        })

    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "user_id": user_id,
            "error": f"gRPC error: {e.details()}",
            "items": [],
            "total_items": 0,
        })
    finally:
        channel.close()