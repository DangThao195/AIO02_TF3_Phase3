# tools/review_tool.py
"""
get_product_reviews_tool — Lấy đánh giá sản phẩm theo 2 tầng:
  1. [Primary]  Bedrock Knowledge Base RAG  (không cần port-forward)
  2. [Fallback] gRPC product-reviews EKS    (cần port-forward localhost:9090)
"""
import json
import logging
import grpc
from langchain_core.tools import tool

import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc
from src.tools.service_config import REVIEWS_ADDR
from src.tools.search.flow2.kb_client import BedrockRAGStrategy
from src.guardrails.input_filter import check_input

logger = logging.getLogger("tools.review_tool")


def _sanitize_review_description(description: str) -> str:
    """
    Lọc injection attempts trong nội dung review trước khi đưa vào context LLM.

    Nếu review chứa câu lệnh tấn công (prompt injection), thay bằng
    placeholder thay vì để LLM thấy toàn bộ nội dung độc.
    """
    if not description:
        return description
    result = check_input(description)
    if not result.is_safe:
        logger.warning(
            f"[REVIEW_TOOL] Injection detected in review text | "
            f"reason={result.blocked_reason} | tier={result.blocked_tier}"
        )
        return "[Nội dung review bị xóa: vi phạm chính sách nội dung]"
    return description


def _reviews_via_rag(product_id: str) -> list:
    """Query Bedrock KB for reviews. Returns list of review dicts or empty list."""
    rag = BedrockRAGStrategy()
    if not rag.kb_id:
        return []
    return rag.retrieve_reviews(product_id)


def _reviews_via_grpc(product_id: str) -> list:
    """Call gRPC product-reviews service. Returns list of review dicts or raises on error."""
    channel = grpc.insecure_channel(REVIEWS_ADDR)
    stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
    try:
        request = demo_pb2.GetProductReviewsRequest(product_id=product_id)
        response = stub.GetProductReviews(request)

        reviews = []
        for rev in response.product_reviews:
            username = rev.username if rev.username else "Anonymous"
            try:
                score = float(rev.score) if rev.score else 0.0
            except ValueError:
                score = 0.0
            reviews.append({
                "username": username,
                "score": score,
                "description": _sanitize_review_description(rev.description if rev.description else ""),
            })
        return reviews
    finally:
        channel.close()


@tool
def get_product_reviews_tool(product_id: str) -> str:
    """
    Get real customer reviews for a specific product to provide grounded answers.
    Required input: product_id (string, e.g. 'OLJCESPC7Z').
    Tries Bedrock Knowledge Base first, falls back to gRPC product-reviews service.
    Returns JSON: {"status", "product_id", "reviews": [{"username","score","description"}],
                   "average_score", "total_reviews", "source"}
    """
    reviews = []
    source = "none"

    # ── Primary: Bedrock KB RAG ──────────────────────────────────────────────
    try:
        rag_reviews = _reviews_via_rag(product_id)
        if rag_reviews:
            # Sanitize injection attempts in review descriptions from RAG
            for r in rag_reviews:
                if "description" in r:
                    r["description"] = _sanitize_review_description(r["description"])
            reviews = rag_reviews
            source = "rag"
            print(f"[REVIEW] Using RAG source: {len(reviews)} reviews for {product_id}")
    except Exception as e:
        print(f"[REVIEW] RAG failed: {e}")


    # ── Fallback: gRPC EKS service ────────────────────────────────────────────
    if not reviews:
        try:
            grpc_reviews = _reviews_via_grpc(product_id)
            if grpc_reviews:
                reviews = grpc_reviews
                source = "grpc"
                print(f"[REVIEW] Using gRPC fallback: {len(reviews)} reviews for {product_id}")
        except grpc.RpcError as e:
            print(f"[REVIEW] gRPC fallback failed: {e.details()}")
            return json.dumps({
                "status": "error",
                "product_id": product_id,
                "error": f"No review data available. RAG: no results. gRPC: {e.details()}",
                "reviews": [],
                "average_score": 0,
                "total_reviews": 0,
                "source": "none",
            })
        except Exception as e:
            print(f"[REVIEW] gRPC fallback failed: {e}")
            return json.dumps({
                "status": "error",
                "product_id": product_id,
                "error": f"No review data available: {str(e)[:150]}",
                "reviews": [],
                "average_score": 0,
                "total_reviews": 0,
                "source": "none",
            })

    if not reviews:
        return json.dumps({
            "status": "success",
            "product_id": product_id,
            "reviews": [],
            "average_score": 0,
            "total_reviews": 0,
            "source": "none",
        })

    # Tính điểm trung bình
    scores = [r["score"] for r in reviews if r.get("score", 0) > 0]
    avg = round(sum(scores) / len(scores), 2) if scores else 0

    return json.dumps({
        "status": "success",
        "product_id": product_id,
        "reviews": reviews,
        "average_score": avg,
        "total_reviews": len(reviews),
        "source": source,
    })