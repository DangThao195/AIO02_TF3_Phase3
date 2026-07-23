"""
graph/nodes/confirmation.py — Confirmation Node

Xử lý resume sau khi user confirm write action.
Khi graph resume với confirmed=True, node này thực thi gRPC thật.
"""

from __future__ import annotations

import json
import logging
import time

import grpc
from langgraph.types import interrupt

logger = logging.getLogger("graph.confirmation")


async def confirmation_node(state: dict) -> dict:
    """
    Confirmation Node — xử lý write flow.

    Flow:
      1. Nếu pending_action tồn tại và chưa confirmed → gọi interrupt()
         (graph suspend, chờ user confirm)
      2. Khi graph resume với Command(resume={"confirmed": True}),
         interrupt() trả về resume value → tiếp tục thực thi gRPC write
    """
    t0 = time.time()

    pending = state.get("pending_action")

    # Nếu không có pending_action → skip
    if not pending:
        return {"node_durations": {"confirmation": int((time.time() - t0) * 1000)}}

    # Nếu có pending_action và chưa confirmed → suspend graph
    confirmed = state.get("confirmed", False)
    if not confirmed:
        resume_value = interrupt({"pending_action": pending, "tool_errors": {}})
        # Sau resume: interrupt() trả về giá trị từ Command(resume=...)
        confirmed = isinstance(resume_value, dict) and resume_value.get("confirmed", False)
        if not confirmed:
            return {
                "pending_action": None,
                "final_answer": "Hành động đã bị hủy.",
                "node_durations": {"confirmation": int((time.time() - t0) * 1000)},
            }

    # ── Đã confirmed — thực thi gRPC write ──
    action = pending.get("action", "")
    args = pending.get("args", {})
    user_id = state.get("user_id", "anonymous")

    result = {}
    try:
        if action == "add_to_cart_tool":
            from src.protos import demo_pb2, demo_pb2_grpc
            from src.tools.service_config import CART_ADDR

            product_id = args.get("product_id", "")
            quantity = int(args.get("quantity", 1))

            with grpc.insecure_channel(CART_ADDR) as ch:
                stub = demo_pb2_grpc.CartServiceStub(ch)
                stub.AddItem(demo_pb2.AddItemRequest(
                    user_id=user_id,
                    item=demo_pb2.CartItem(product_id=product_id, quantity=quantity),
                ))
            result = {"status": "confirmed", "message": f"Đã thêm {quantity} sản phẩm vào giỏ hàng."}

        elif action in ("update_cart_item_tool", "RemoveItem", "UpdateItem"):
            from src.protos import demo_pb2, demo_pb2_grpc
            from src.tools.service_config import CART_ADDR

            product_id = args.get("product_id", "")
            quantity = int(args.get("quantity", 0))

            with grpc.insecure_channel(CART_ADDR) as ch:
                stub = demo_pb2_grpc.CartServiceStub(ch)
                stub.AddItem(demo_pb2.AddItemRequest(
                    user_id=user_id,
                    item=demo_pb2.CartItem(product_id=product_id, quantity=quantity),
                ))
            result = {"status": "confirmed", "message": "Đã cập nhật giỏ hàng."}

        else:
            result = {"status": "confirmed", "message": "Hành động đã được xác nhận."}

    except Exception as e:
        logger.error("[confirmation] gRPC error: %s", e)
        result = {"status": "error", "message": "Không thể thực thi hành động. Vui lòng thử lại."}

    duration_ms = int((time.time() - t0) * 1000)

    tool_results = dict(state.get("tool_results") or {})
    tool_results[action] = result

    final_answer = result.get("message", "Đã xác nhận.")

    return {
        "tool_results": tool_results,
        "final_answer": final_answer,
        "pending_action": None,
        "confirmed": False,
        "node_durations": {"confirmation": duration_ms},
    }
