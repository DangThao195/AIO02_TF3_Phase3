# tools/recommendation_tool.py
"""Recommendation tool — returns normalized JSON."""

import json
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.tools.service_config import RECO_ADDR


@tool
def get_recommendations_tool(product_id: str, user_id: str = "default_user") -> str:
    """
    Hữu ích khi người dùng muốn xem các gợi ý sản phẩm liên quan, sản phẩm tương tự
    hoặc các mặt hàng thường được mua kèm với sản phẩm họ đang xem (Cross-sell).
    Đầu vào cần thiết: product_id (mã sản phẩm hiện tại).
    Returns JSON: {"status", "product_id", "recommendations": ["id1","id2",...], "total"}
    """
    channel = grpc.insecure_channel(RECO_ADDR)
    stub = demo_pb2_grpc.RecommendationServiceStub(channel)

    try:
        request = demo_pb2.ListRecommendationsRequest(
            user_id=user_id,
            product_ids=[product_id]
        )
        response = stub.ListRecommendations(request)

        if not response.product_ids:
            return json.dumps({
                "status": "empty",
                "product_id": product_id,
                "recommendations": [],
                "total": 0,
            })

        recs = list(response.product_ids)
        return json.dumps({
            "status": "success",
            "product_id": product_id,
            "recommendations": recs,
            "total": len(recs),
        })

    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "product_id": product_id,
            "error": f"gRPC error: {e.details()}",
            "recommendations": [],
            "total": 0,
        })
    finally:
        channel.close()