"""
tools/product_tool.py — get_product_details_tool

Backend: ProductCatalogService gRPC (demo.proto)
"""

import json
import logging

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import CATALOG_ADDR

logger = logging.getLogger("tools.product")


def _normalize_price(units: int, nanos: int) -> str:
    cents = nanos // 10_000_000
    return f"${units}.{cents:02d}"


@tool
def get_product_details_tool(product_id: str) -> str:
    """
    Lấy chi tiết đầy đủ của một sản phẩm theo product_id (tên, giá, mô tả, hình ảnh, danh mục).
    Trả về JSON: {status, product{id,name,price,description,image,categories,rating,review_count}}
    """
    try:
        with grpc.insecure_channel(CATALOG_ADDR) as ch:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(ch)
            p = stub.GetProduct(demo_pb2.GetProductRequest(id=product_id))

            cats = p.categories
            if isinstance(cats, str):
                cats = [c.strip() for c in cats.split(",") if c.strip()]
            elif not isinstance(cats, list):
                cats = list(cats)

            return json.dumps({
                "status": "success",
                "product": {
                    "id": p.id,
                    "name": p.name,
                    "price": _normalize_price(p.price_usd.units, p.price_usd.nanos),
                    "description": p.description,
                    "image": getattr(p, "picture", "") or "",
                    "categories": cats,
                    "rating": 0,
                    "review_count": 0,
                },
            }, ensure_ascii=False)

    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        if code == "NOT_FOUND":
            return json.dumps({"status": "error", "message": f"Không tìm thấy sản phẩm '{product_id}'."})
        logger.error("[get_product_details_tool] gRPC %s | product=%s | %s", code, product_id, e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ không khả dụng, vui lòng thử lại sau."})
    except Exception as e:
        logger.error("[get_product_details_tool] error | product=%s | %s", product_id, e, exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_product_details_tool",
    description="Lấy chi tiết đầy đủ của một sản phẩm theo product_id (tên, giá, mô tả, hình ảnh, danh mục, đánh giá).",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "product_id": {"type": "string", "description": "ID sản phẩm"}
    }, "required": ["product_id"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "product": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": {"type": "string"},
            "price": {"type": "string"}, "description": {"type": "string"},
            "image": {"type": "string"}, "categories": {"type": "array"},
            "rating": {"type": "number"}, "review_count": {"type": "integer"},
        }},
        "message": {"type": "string"},
    }},
    examples=[{"input": {"product_id": "OLJCESPC7Z"},
               "output": {"status": "success", "product": {"name": "Vintage Typewriter", "price": "$65.50"}}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_product_details_tool)
