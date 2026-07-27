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


def _reviews_via_db(product_id: str) -> list:
    """Query local SQLite database for reviews as fallback."""
    import sqlite3 as _sqlite3
    from pathlib import Path as _Path

    try:
        candidates = []
        fp = _Path(__file__).resolve()
        for base in [fp.parents[4], fp.parents[3], fp.parents[2], fp.parents[1], _Path.cwd()]:
            candidates.append(base / "server-test" / "shopping.db")
            candidates.append(base / "shopping.db")
        db_path = None
        for c in candidates:
            if c.exists():
                db_path = c
                break
        if not db_path:
            return []
        conn = _sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT username, score, description FROM productreviews WHERE product_id = ?",
                (product_id,)
            )
            rows = cur.fetchall()
            return [
                {"username": r[0] if r[0] else "Anonymous",
                 "score": float(r[1]) if r[1] else 0.0,
                 "description": r[2] or ""}
                for r in rows
            ]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("DB review fallback failed: %s", e)
        return []


def _reviews_via_rag(product_id: str) -> list:
    """Query local DB for reviews. Primary source when RAG/gRPC unavailable."""
    return _reviews_via_db(product_id)


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
            logger.info("RAG source: %d reviews for %s", len(reviews), product_id)
    except Exception as e:
        logger.error("RAG failed for %s: %s", product_id, e, exc_info=True)


    # ── Fallback: gRPC EKS service ────────────────────────────────────────────
    if not reviews:
        try:
            grpc_reviews = _reviews_via_grpc(product_id)
            if grpc_reviews:
                reviews = grpc_reviews
                source = "grpc"
                logger.info("gRPC fallback: %d reviews for %s", len(reviews), product_id)
        except grpc.RpcError as e:
            logger.error("gRPC fallback failed for %s: %s", product_id, e.details(), exc_info=True)
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
            logger.error("gRPC fallback failed for %s: %s", product_id, e, exc_info=True)
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


@tool
def get_best_reviewed_products_tool(limit: int = 10, category: str = None) -> str:
    """
    Get the top-rated products based on average review scores.
    Use when user asks: "sản phẩm đánh giá tốt nhất", "best reviewed products",
    "highest rated", "top rated products", "sản phẩm review cao nhất".
    
    Parameters:
    - limit: Number of products to return (default 10)
    - category: Optional category filter (e.g., "telescopes", "binoculars")
    
    Returns JSON: {"status", "total", "products": [{"id", "name", "price", "avg_score", "review_count"}]}
    """
    try:
        from src.tools.search.flow1.sql_executor import SQLQueryExecutor
        executor = SQLQueryExecutor()
        init_method = getattr(executor, 'ensure_initialized', None) or getattr(executor, 'initialize', None)
        if init_method:
            init_method()
        
        # Build WHERE clause for category filter
        where_clause = ""
        if category:
            category_pattern = category.lower().rstrip('s')
            where_clause = f"WHERE LOWER(p.categories) LIKE '%{category_pattern}%'"
        
        query = f"""
            SELECT p.id, p.name, p.categories, p.price_units, p.price_nanos,
                   ROUND(AVG(r.score), 2) AS avg_score,
                   COUNT(r.id) AS review_count
            FROM catalog.products p
            JOIN reviews.productreviews r ON r.product_id = p.id
            {where_clause}
            GROUP BY p.id, p.name, p.categories, p.price_units, p.price_nanos
            HAVING COUNT(r.id) > 0
            ORDER BY avg_score DESC, review_count DESC
        """
        
        rows = executor.execute(query, limit=limit)
        
        if not rows:
            return json.dumps({
                "status": "empty",
                "total": 0,
                "products": [],
                "filters": {"category": category}
            })
        
        products = []
        for r in rows:
            price_u = r.get("price_units", 0) or 0
            price_n = r.get("price_nanos", 0) or 0
            products.append({
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "categories": r.get("categories", ""),
                "price": round(price_u + price_n / 1e9, 2),
                "avg_score": float(r.get("avg_score", 0)),
                "review_count": int(r.get("review_count", 0)),
            })
        
        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
            "filters": {"category": category}
        })
        
    except Exception as e:
        logger.error(f"get_best_reviewed_products_tool error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)[:200],
            "total": 0,
            "products": []
        })


@tool
def get_worst_reviewed_products_tool(limit: int = 10, category: str = None) -> str:
    """
    Get the worst-rated products based on average review scores.
    Use when user asks: "sản phẩm đánh giá tệ nhất", "worst reviewed products",
    "lowest rated", "sản phẩm review thấp nhất", "sản phẩm dở nhất".
    
    Parameters:
    - limit: Number of products to return (default 10)
    - category: Optional category filter (e.g., "telescopes", "binoculars")
    
    Returns JSON: {"status", "total", "products": [{"id", "name", "price", "avg_score", "review_count"}]}
    """
    try:
        from src.tools.search.flow1.sql_executor import SQLQueryExecutor
        executor = SQLQueryExecutor()
        init_method = getattr(executor, 'ensure_initialized', None) or getattr(executor, 'initialize', None)
        if init_method:
            init_method()
        
        # Build WHERE clause for category filter
        where_clause = ""
        if category:
            category_pattern = category.lower().rstrip('s')
            where_clause = f"WHERE LOWER(p.categories) LIKE '%{category_pattern}%'"
        
        query = f"""
            SELECT p.id, p.name, p.categories, p.price_units, p.price_nanos,
                   ROUND(AVG(r.score), 2) AS avg_score,
                   COUNT(r.id) AS review_count
            FROM catalog.products p
            JOIN reviews.productreviews r ON r.product_id = p.id
            {where_clause}
            GROUP BY p.id, p.name, p.categories, p.price_units, p.price_nanos
            HAVING COUNT(r.id) > 0
            ORDER BY avg_score ASC, review_count DESC
        """
        
        rows = executor.execute(query, limit=limit)
        
        if not rows:
            return json.dumps({
                "status": "empty",
                "total": 0,
                "products": [],
                "filters": {"category": category}
            })
        
        products = []
        for r in rows:
            price_u = r.get("price_units", 0) or 0
            price_n = r.get("price_nanos", 0) or 0
            products.append({
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "categories": r.get("categories", ""),
                "price": round(price_u + price_n / 1e9, 2),
                "avg_score": float(r.get("avg_score", 0)),
                "review_count": int(r.get("review_count", 0)),
            })
        
        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
            "filters": {"category": category}
        })
        
    except Exception as e:
        logger.error(f"get_worst_reviewed_products_tool error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e)[:200],
            "total": 0,
            "products": []
        })


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_product_reviews_tool",
    description="Lấy đánh giá thực tế của khách hàng cho một sản phẩm. Tries Bedrock KB first, falls back to gRPC.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "product_id": {"type": "string", "description": "ID sản phẩm (VD: OLJCESPC7Z)"},
    }, "required": ["product_id"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "product_id": {"type": "string"},
        "reviews": {"type": "array", "items": {"type": "object",
            "properties": {
                "username": {"type": "string"},
                "score": {"type": "number"},
                "description": {"type": "string"},
            },
        }},
        "average_score": {"type": "number"},
        "total_reviews": {"type": "integer"},
    }},
    examples=[{"input": {"product_id": "OLJCESPC7Z"},
               "output": {"status": "success", "total_reviews": 5, "average_score": 4.2}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_product_reviews_tool)

ToolRegistry.register(ToolSpec(
    name="get_best_reviewed_products_tool",
    description="Get the top-rated products based on average review scores. Dùng khi user hỏi 'sản phẩm đánh giá tốt nhất'.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "limit": {"type": "integer", "description": "Số lượng sản phẩm trả về (default 10)"},
        "category": {"type": "string", "description": "Lọc theo danh mục (optional)"},
    }},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "total": {"type": "integer"},
        "products": {"type": "array"},
    }},
    examples=[{"input": {"limit": 5, "category": "telescopes"},
               "output": {"status": "success", "total": 3}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_best_reviewed_products_tool)

ToolRegistry.register(ToolSpec(
    name="get_worst_reviewed_products_tool",
    description="Get the worst-rated products based on average review scores. Dùng khi user hỏi 'sản phẩm đánh giá tệ nhất'.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "limit": {"type": "integer", "description": "Số lượng sản phẩm trả về (default 10)"},
        "category": {"type": "string", "description": "Lọc theo danh mục (optional)"},
    }},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "total": {"type": "integer"},
        "products": {"type": "array"},
    }},
    examples=[{"input": {"limit": 5}, "output": {"status": "success", "total": 3}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_worst_reviewed_products_tool)
