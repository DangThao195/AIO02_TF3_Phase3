"""
tools/recommendation_tool.py — get_recommendations_tool

Backend: RecommendationService gRPC (demo.proto)
"""

import json
import logging

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import RECO_ADDR, CATALOG_ADDR

logger = logging.getLogger("tools.recommendation")


def _normalize_price(units: int, nanos: int) -> str:
    cents = nanos // 10_000_000
    return f"${units}.{cents:02d}"


@tool
def get_recommendations_tool(product_id: str) -> str:
    """
    Gợi ý sản phẩm liên quan hoặc thường mua kèm với một sản phẩm.
    Trả về JSON: {status, product_id, recommendations[{id,name,price}]}
    """
    try:
        with grpc.insecure_channel(RECO_ADDR) as reco_ch, \
             grpc.insecure_channel(CATALOG_ADDR) as cat_ch:
            reco_stub = demo_pb2_grpc.RecommendationServiceStub(reco_ch)
            cat_stub = demo_pb2_grpc.ProductCatalogServiceStub(cat_ch)

            resp = reco_stub.ListRecommendations(
                demo_pb2.ListRecommendationsRequest(product_ids=[product_id])
            )

            product_ids = list(resp.product_ids)
            recommendations = []
            for pid in product_ids[:5]:
                try:
                    p = cat_stub.GetProduct(demo_pb2.GetProductRequest(id=pid))
                    recommendations.append({
                        "id": p.id,
                        "name": p.name,
                        "price": _normalize_price(p.price_usd.units, p.price_usd.nanos),
                    })
                except Exception:
                    recommendations.append({"id": pid, "name": pid, "price": "$0.00"})

            return json.dumps({
                "status": "success",
                "product_id": product_id,
                "recommendations": recommendations,
                "total": len(recommendations),
            }, ensure_ascii=False)

    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        logger.error("[get_recommendations_tool] gRPC %s | product=%s | %s", code, product_id, e, exc_info=True)
        return json.dumps({"status": "error", "product_id": product_id,
                           "message": "Dịch vụ gợi ý không khả dụng."})
    except Exception as e:
        logger.error("[get_recommendations_tool] error | product=%s | %s", product_id, e, exc_info=True)
        return json.dumps({"status": "error", "product_id": product_id, "message": str(e)})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_recommendations_tool",
    description="Gợi ý sản phẩm liên quan hoặc thường mua kèm với một sản phẩm.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "product_id": {"type": "string"}
    }, "required": ["product_id"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "product_id": {"type": "string"},
        "recommendations": {"type": "array"},
        "total": {"type": "integer"},
    }},
    examples=[{"input": {"product_id": "OLJCESPC7Z"},
               "output": {"status": "success", "total": 3}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_recommendations_tool)
