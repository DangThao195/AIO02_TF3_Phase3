# tools/recommendation_tool.py
"""Recommendation tool — returns normalized JSON."""

import json
import grpc
from langchain_core.tools import tool
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.tools.service_config import RECO_ADDR
from src.tools.search.flow1.sql_executor import SQLQueryExecutor


def _sql_fallback_recommendations(product_id: str, limit: int = 4) -> list:
    """
    FIX #4: SQL-based fallback khi gRPC Recommendation Service không khả dụng.
    Tìm sản phẩm cùng danh mục với sản phẩm hiện tại, loại trừ chính nó.
    NOTE: SQLQueryExecutor.execute() chỉ nhận plain SQL string (không hỗ trợ params).
    product_id là UUID từ hệ thống nội bộ — an toàn để interpolate trực tiếp.
    """
    safe_pid = product_id.replace("'", "")  # sanitize UUID
    executor = SQLQueryExecutor()
    executor.ensure_initialized()

    # Step 1: Lấy categories của sản phẩm hiện tại
    cat_rows = executor.execute(
        f"SELECT categories FROM products WHERE id = '{safe_pid}' LIMIT 1"
    )

    rows = []
    if cat_rows:
        categories = cat_rows[0].get("categories", []) or []
        # categories có thể là list (PostgreSQL) hoặc string CSV (SQLite)
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(",") if c.strip()]
        if categories:
            cat = str(categories[0]).replace("'", "")
            # Cú pháp ANY(categories) hoạt động trên PostgreSQL;
            # SQLite fallback sẽ dùng LIKE để tương thích
            try:
                rows = executor.execute(
                    f"SELECT id, name, price_units, price_nanos, description FROM products "
                    f"WHERE id != '{safe_pid}' AND '{cat}' = ANY(categories) LIMIT {limit}"
                )
            except Exception:
                # SQLite không hỗ trợ ANY() → dùng LIKE
                rows = executor.execute(
                    f"SELECT id, name, price_units, price_nanos, description FROM products "
                    f"WHERE id != '{safe_pid}' AND categories LIKE '%{cat}%' LIMIT {limit}"
                )

    if not rows:
        rows = executor.execute(
            f"SELECT id, name, price_units, price_nanos, description FROM products "
            f"WHERE id != '{safe_pid}' LIMIT {limit}"
        )

    details = []
    for r in rows:
        price_u = r.get("price_units", 0) or 0
        price_n = r.get("price_nanos", 0) or 0
        details.append({
            "id": str(r.get("id", "")),
            "name": r.get("name", ""),
            "price": round(price_u + price_n / 1e9, 2),
            "description": (r.get("description", "") or "")[:120],
        })
    return details



@tool
def get_recommendations_tool(product_id: str, user_id: str = "default_user") -> str:
    """
    Hữu ích khi người dùng muốn xem các gợi ý sản phẩm liên quan, sản phẩm tương tự
    hoặc các mặt hàng thường được mua kèm với sản phẩm họ đang xem (Cross-sell).
    Đầu vào cần thiết: product_id (mã sản phẩm hiện tại).
    Returns JSON: {"status", "product_id", "recommendations": [...], "total"}
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

        # Fetch product details for the recommended IDs
        executor = SQLQueryExecutor()
        executor.ensure_initialized()
        placeholders = ",".join([f"'{x}'" for x in recs])
        query = f"SELECT id, name, price_units, price_nanos, description FROM products WHERE id IN ({placeholders})"
        rows = executor.execute(query)
        
        details = []
        for r in rows:
            price_u = r.get("price_units", 0) or 0
            price_n = r.get("price_nanos", 0) or 0
            details.append({
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "price": round(price_u + price_n / 1e9, 2),
                "description": (r.get("description", "") or "")[:120],
            })

        return json.dumps({
            "status": "success",
            "product_id": product_id,
            "recommendations": details,
            "total": len(details),
        })

    except grpc.RpcError:
        # FIX #4: gRPC không khả dụng → dùng SQL fallback thay vì báo lỗi
        channel.close()
        try:
            details = _sql_fallback_recommendations(product_id)
            return json.dumps({
                "status": "success",
                "product_id": product_id,
                "source": "sql_fallback",
                "recommendations": details,
                "total": len(details),
            })
        except Exception as sql_err:
            return json.dumps({
                "status": "error",
                "product_id": product_id,
                "error": f"Recommendation service unavailable: {sql_err}",
                "recommendations": [],
                "total": 0,
            })
    finally:
        try:
            channel.close()
        except Exception:
            pass