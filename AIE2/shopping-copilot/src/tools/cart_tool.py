"""
tools/cart_tool.py — Cart tools: get_cart, add_to_cart, update_cart_item, check_cart_item

Backend: CartService gRPC (demo.proto)
"""

import json
import logging
from typing import Optional

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import CART_ADDR, CATALOG_ADDR
from src.guardrails.confirmation import request_confirmation

logger = logging.getLogger("tools.cart")


def _normalize_price(units: int, nanos: int) -> str:
    cents = nanos // 10_000_000
    return f"${units}.{cents:02d}"


# ─────────────────────────────────────────────────────────────────
# get_cart_tool
# ─────────────────────────────────────────────────────────────────

@tool
def get_cart_tool(user_id: str) -> str:
    """
    Xem danh sách sản phẩm trong giỏ hàng hiện tại (tên, giá, số lượng, tổng tiền).
    Trả về JSON: {status, items[], subtotal, item_count}
    """
    try:
        with grpc.insecure_channel(CART_ADDR) as cart_ch, \
             grpc.insecure_channel(CATALOG_ADDR) as cat_ch:
            cart_stub = demo_pb2_grpc.CartServiceStub(cart_ch)
            cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_ch)

            resp = cart_stub.GetCart(demo_pb2.GetCartRequest(user_id=user_id))

            if not resp.items:
                return json.dumps({
                    "status": "empty",
                    "items": [],
                    "subtotal": "$0.00",
                    "item_count": 0,
                }, ensure_ascii=False)

            items = []
            total_cents = 0
            total_count = 0
            for item in resp.items:
                pname = item.product_id
                price_str = "$0.00"
                image = ""
                item_total = 0
                try:
                    p = cat_stub.GetProduct(demo_pb2.GetProductRequest(id=item.product_id))
                    pname = p.name
                    price_str = _normalize_price(p.price_usd.units, p.price_usd.nanos)
                    item_total = (p.price_usd.units * 100 + p.price_usd.nanos // 10_000_000) * item.quantity
                    total_cents += item_total
                    image = getattr(p, "picture", "") or ""
                except Exception as e:
                    logger.debug("[get_cart_tool] product lookup failed for %s: %s", item.product_id, e)

                items.append({
                    "product_id": item.product_id,
                    "name": pname,
                    "price": price_str,
                    "quantity": item.quantity,
                    "image": image,
                })
                total_count += item.quantity

            subtotal = f"${total_cents // 100}.{total_cents % 100:02d}"
            return json.dumps({
                "status": "success",
                "items": items,
                "subtotal": subtotal,
                "item_count": total_count,
            }, ensure_ascii=False)

    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        logger.error("[get_cart_tool] gRPC %s | user=%s | error=%s", code, user_id, e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ giỏ hàng không khả dụng."})
    except Exception as e:
        logger.error("[get_cart_tool] error | user=%s | %s", user_id, e, exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# ─────────────────────────────────────────────────────────────────
# add_to_cart_tool
# ─────────────────────────────────────────────────────────────────

@tool
def add_to_cart_tool(user_id: str, product_id: str, quantity: int = 1) -> str:
    """
    Thêm sản phẩm vào giỏ hàng. Cần xác nhận trước khi thực thi.
    Trả về JSON: {status: pending|confirmed|denied|error, token?, message, item?}
    """
    if quantity <= 0:
        return json.dumps({"status": "error", "message": "Số lượng phải lớn hơn 0."})

    try:
        # Lấy tên sản phẩm để hiển thị
        product_name = product_id
        price_str = "$0.00"
        try:
            with grpc.insecure_channel(CATALOG_ADDR) as cat_ch:
                cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_ch)
                p = cat_stub.GetProduct(demo_pb2.GetProductRequest(id=product_id))
                product_name = p.name
                price_str = _normalize_price(p.price_usd.units, p.price_usd.nanos)
        except Exception as e:
            logger.debug("[add_to_cart_tool] product lookup failed for %s: %s", product_id, e)

        # L4 Confirmation
        confirm_result = request_confirmation(
            user_id=user_id,
            action="AddItem",
            action_params={"product_id": product_id, "quantity": quantity},
        )

        if confirm_result.status == "DENIED":
            return json.dumps({
                "status": "denied",
                "message": confirm_result.message,
            })

        return json.dumps({
            "status": "pending",
            "token": confirm_result.confirmation_token or "",
            "message": f"Vui lòng xác nhận: thêm {quantity} {product_name} vào giỏ hàng.",
            "item": {
                "product_id": product_id,
                "name": product_name,
                "price": price_str,
                "quantity": quantity,
            },
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("[add_to_cart_tool] error | user=%s | product=%s | qty=%s | %s",
                      user_id, product_id, quantity, e, exc_info=True)
        return json.dumps({"status": "error", "message": "Không thể thêm sản phẩm vào giỏ hàng."})


# ─────────────────────────────────────────────────────────────────
# update_cart_item_tool
# ─────────────────────────────────────────────────────────────────

@tool
def update_cart_item_tool(user_id: str, product_id: str, quantity: int) -> str:
    """
    Cập nhật số lượng sản phẩm trong giỏ hàng (quantity=0 để xóa).
    Cần xác nhận trước khi thực thi.
    Trả về JSON: {status, message, token?}
    """
    try:
        action_label = "RemoveItem" if quantity == 0 else "UpdateItem"
        confirm_result = request_confirmation(
            user_id=user_id,
            action=action_label,
            action_params={"product_id": product_id, "quantity": quantity},
        )

        if confirm_result.status == "DENIED":
            return json.dumps({
                "status": "denied",
                "message": confirm_result.message,
            })

        msg = (
            f"Xác nhận xóa sản phẩm {product_id} khỏi giỏ?"
            if quantity == 0
            else f"Xác nhận cập nhật số lượng {product_id} thành {quantity}?"
        )
        return json.dumps({
            "status": "pending",
            "token": confirm_result.confirmation_token or "",
            "message": msg,
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("[update_cart_item_tool] error | user=%s | product=%s | qty=%s | %s",
                      user_id, product_id, quantity, e, exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# ─────────────────────────────────────────────────────────────────
# check_cart_item_tool
# ─────────────────────────────────────────────────────────────────

@tool
def check_cart_item_tool(user_id: str, product_id: str) -> str:
    """
    Kiểm tra sản phẩm có trong giỏ hàng không và số lượng hiện tại.
    Trả về chuỗi mô tả kết quả.
    """
    try:
        with grpc.insecure_channel(CART_ADDR) as ch:
            stub = demo_pb2_grpc.CartServiceStub(ch)
            resp = stub.GetCart(demo_pb2.GetCartRequest(user_id=user_id))
            for item in resp.items:
                if item.product_id == product_id:
                    return f"Sản phẩm '{product_id}' đang có trong giỏ hàng với số lượng {item.quantity}."
            return f"Không tìm thấy sản phẩm '{product_id}' trong giỏ hàng của bạn."
    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        logger.warning("[check_cart_item_tool] gRPC %s | user=%s | product=%s", code, user_id, product_id)
        return "Dịch vụ giỏ hàng tạm thời không khả dụng."
    except Exception as e:
        logger.error("[check_cart_item_tool] error | user=%s | product=%s | %s",
                      user_id, product_id, e, exc_info=True)
        return f"Lỗi kiểm tra giỏ hàng: {str(e)}"


# ─────────────────────────────────────────────────────────────────
# ToolSpec registration
# ─────────────────────────────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_cart_tool",
    description="Xem danh sách sản phẩm trong giỏ hàng hiện tại của người dùng (tên, giá, số lượng, tổng tiền).",
    is_write=False,
    input_schema={"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string", "enum": ["success", "empty", "error"]},
        "items": {"type": "array"},
        "subtotal": {"type": "string"},
        "item_count": {"type": "integer"},
    }},
    examples=[{"input": {"user_id": "u1"}, "output": {"status": "success", "item_count": 2, "subtotal": "$149.98"}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_cart_tool)

ToolRegistry.register(ToolSpec(
    name="add_to_cart_tool",
    description="Thêm sản phẩm vào giỏ hàng. Cần user confirm trước khi execute (write tool).",
    is_write=True,
    input_schema={"type": "object", "properties": {
        "product_id": {"type": "string"},
        "quantity": {"type": "integer", "default": 1},
    }, "required": ["product_id"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string", "enum": ["pending", "confirmed", "denied", "error"]},
        "token": {"type": "string"},
        "message": {"type": "string"},
        "item": {"type": "object"},
    }},
    examples=[{"input": {"product_id": "OLJCESPC7Z", "quantity": 1}, "output": {"status": "pending"}}],
    retry_config={"max_retries": 1, "backoff": [0.5]},
), fn=add_to_cart_tool)

ToolRegistry.register(ToolSpec(
    name="update_cart_item_tool",
    description="Cập nhật số lượng sản phẩm trong giỏ hàng (quantity=0 để xóa). Cần confirm.",
    is_write=True,
    input_schema={"type": "object", "properties": {
        "user_id": {"type": "string"},
        "product_id": {"type": "string"},
        "quantity": {"type": "integer"},
    }, "required": ["user_id", "product_id", "quantity"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "token": {"type": "string"},
        "message": {"type": "string"},
    }},
    retry_config={"max_retries": 1, "backoff": [0.5]},
), fn=update_cart_item_tool)

ToolRegistry.register(ToolSpec(
    name="check_cart_item_tool",
    description="Kiểm tra sản phẩm có trong giỏ hàng không và số lượng hiện tại.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "user_id": {"type": "string"},
        "product_id": {"type": "string"},
    }, "required": ["user_id", "product_id"]},
    output_schema={"type": "string"},
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=check_cart_item_tool)
