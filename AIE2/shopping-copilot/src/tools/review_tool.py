# tools/review_tool.py
import json
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.tools.service_config import REVIEWS_ADDR


@tool
def get_product_reviews_tool(product_id: str) -> str:
    """
    Get real customer reviews for a specific product to provide grounded answers.
    Required input: product_id.
    Returns JSON: {"status", "product_id", "reviews": [{"username","score","description"}], "average_score", "total_reviews"}
    """
    channel = grpc.insecure_channel(REVIEWS_ADDR)
    stub = demo_pb2_grpc.ProductReviewServiceStub(channel)

    try:
        request = demo_pb2.GetProductReviewsRequest(product_id=product_id)
        response = stub.GetProductReviews(request)

        if not response.product_reviews:
            return json.dumps({
                "status": "success",
                "product_id": product_id,
                "reviews": [],
                "average_score": 0,
                "total_reviews": 0,
            })

        reviews = []
        total_score = 0
        count = 0
        for rev in response.product_reviews:
            username = rev.username if rev.username else "Anonymous"
            try:
                score = float(rev.score) if rev.score else 0.0
            except ValueError:
                score = 0.0
            description = rev.description if rev.description else ""
            reviews.append({
                "username": username,
                "score": score,
                "description": description,
            })
            if score > 0:
                total_score += score
                count += 1

        avg = round(total_score / count, 2) if count > 0 else 0

        return json.dumps({
            "status": "success",
            "product_id": product_id,
            "reviews": reviews,
            "average_score": avg,
            "total_reviews": len(reviews),
        })

    except grpc.RpcError as e:
        return json.dumps({
            "status": "error",
            "product_id": product_id,
            "error": f"gRPC error: {e.details()}",
            "reviews": [],
            "average_score": 0,
            "total_reviews": 0,
        })
    finally:
        channel.close()