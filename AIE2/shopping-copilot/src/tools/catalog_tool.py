"""
tools/catalog_tool.py — Công cụ truy vấn danh mục và toàn bộ sản phẩm.
Returns normalized JSON for all outputs.
"""

import json
import logging

from langchain_core.tools import tool

from src.tools.search.flow1.sql_executor import SQLQueryExecutor

logger = logging.getLogger("tools.catalog_tool")


@tool
def get_categories() -> str:
    """
    Lấy danh sách tất cả các danh mục sản phẩm khác nhau trong database.
    Dùng khi người dùng hỏi: "có những danh mục nào?", "bạn bán những loại gì?",
    "categories", "list categories", hoặc muốn xem tổng quan các nhóm hàng.
    Không cần tham số đầu vào.
    Returns JSON: {"status", "categories": ["Cat1","Cat2",...], "total"}
    """
    try:
        executor = SQLQueryExecutor()
        executor.ensure_initialized()
        rows = executor.execute(
            "SELECT DISTINCT categories FROM products WHERE categories IS NOT NULL AND categories != '' ORDER BY categories"
        )
        seen: set = set()
        categories: list[str] = []
        for row in rows:
            raw = str(row.get("categories", "") or "")
            if not raw:
                continue
            for part in raw.split(","):
                cleaned = part.strip()
                if cleaned and cleaned.lower() not in seen:
                    seen.add(cleaned.lower())
                    categories.append(cleaned)
        if not categories:
            return json.dumps({"status": "empty", "categories": [], "total": 0})

        sorted_cats = sorted(categories)
        return json.dumps({
            "status": "success",
            "categories": sorted_cats,
            "total": len(sorted_cats),
        })
    except Exception as e:
        logger.error(f"get_categories error: {e}")
        return json.dumps({"status": "error", "error": str(e)[:200], "categories": [], "total": 0})


@tool
def get_all_products() -> str:
    """
    Lấy toàn bộ thông tin sản phẩm trong database (tên, giá, mô tả, danh mục).
    CHỈ DÙNG khi thực sự cần thiết: khi người dùng yêu cầu danh sách đầy đủ tất cả sản phẩm
    (VD: "liệt kê tất cả sản phẩm", "show all products", "bán những gì", "danh sách full"),
    xuất dữ liệu kho hàng, hoặc kiểm kê toàn bộ danh mục.
    KHÔNG dùng để tìm kiếm thông thường — dùng search_products_v2 cho mục đích đó.
    Không cần tham số đầu vào.
    Returns JSON: {"status", "total", "products": [{id, name, price, price_units, price_nanos, categories, description}]}
    """
    try:
        executor = SQLQueryExecutor()
        executor.ensure_initialized()
        rows = executor.execute(
            "SELECT id, name, description, categories, price_units, price_nanos FROM products ORDER BY name",
            limit=100,
        )
        if not rows:
            return json.dumps({"status": "empty", "total": 0, "products": []})

        products = []
        for r in rows:
            price_u = r.get("price_units", 0) or 0
            price_n = r.get("price_nanos", 0) or 0
            products.append({
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "price": round(price_u + price_n / 1e9, 2),
                "categories": r.get("categories", ""),
            })

        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
        })
    except Exception as e:
        logger.error(f"get_all_products error: {e}")
        return json.dumps({"status": "error", "error": str(e)[:200], "total": 0, "products": []})


@tool
def get_top_rated_products(limit: int = 10) -> str:
    """
    Lấy danh sách sản phẩm được đánh giá cao nhất, xếp theo điểm trung bình giảm dần.
    Dùng khi người dùng hỏi: \"sản phẩm đánh giá cao nhất\", \"top rated\", \"best rated\",
    \"sản phẩm được yêu thích nhất\", \"xếp hạng theo đánh giá\".
    Returns JSON: {\"status\", \"total\", \"products\": [{id, name, price, avg_rating, review_count}]}
    """
    try:
        executor = SQLQueryExecutor()
        executor.ensure_initialized()
        rows = executor.execute(
            """
            SELECT p.id, p.name, p.price_units, p.price_nanos,
                   ROUND(AVG(r.score), 2) AS avg_rating,
                   COUNT(r.id) AS review_count
            FROM catalog.products p
            JOIN reviews.reviews r ON r.product_id = p.id
            GROUP BY p.id, p.name, p.price_units, p.price_nanos
            HAVING COUNT(r.id) > 0
            ORDER BY avg_rating DESC, review_count DESC
            """,
            limit=limit,
        )
        if not rows:
            return json.dumps({"status": "empty", "total": 0, "products": []})

        products = []
        for r in rows:
            price_u = r.get("price_units", 0) or 0
            price_n = r.get("price_nanos", 0) or 0
            products.append({
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "price": round(price_u + price_n / 1e9, 2),
                "avg_rating": float(r.get("avg_rating", 0)),
                "review_count": int(r.get("review_count", 0)),
            })

        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
        })
    except Exception as e:
        logger.error(f"get_top_rated_products error: {e}")
        return json.dumps({"status": "error", "error": str(e)[:200], "total": 0, "products": []})


@tool
def get_products_by_price_range(max_price: float = None, min_price: float = None, limit: int = 20) -> str:
    """
    Lấy danh sách sản phẩm trong khoảng giá chỉ định.
    Dùng khi người dùng hỏi: \"sản phẩm giá rẻ dưới X\", \"sản phẩm từ X đến Y USD\",
    \"under $50\", \"between 100 and 200 dollars\", \"dưới 100k\", \"từ 200 đến 500 đô\".
    
    Parameters:
    - max_price: Giá tối đa (USD). VD: 50 cho \"under $50\"
    - min_price: Giá tối thiểu (USD). VD: 100 cho \"from $100\"
    - limit: Số lượng sản phẩm tối đa trả về (mặc định 20)
    
    Returns JSON: {\"status\", \"total\", \"products\": [{id, name, price, categories}]}
    """
    try:
        executor = SQLQueryExecutor()
        executor.ensure_initialized()
        
        # Build WHERE clause safely (validate numeric inputs)
        where_clauses = []
        if min_price is not None:
            # Validate numeric to prevent SQL injection
            try:
                min_val = float(min_price)
                where_clauses.append(f"(price_units + price_nanos / 1e9) >= {min_val}")
            except (ValueError, TypeError):
                logger.error(f"Invalid min_price: {min_price}")
                return json.dumps({"status": "error", "error": "Invalid min_price parameter", "total": 0, "products": []})
        
        if max_price is not None:
            # Validate numeric to prevent SQL injection
            try:
                max_val = float(max_price)
                where_clauses.append(f"(price_units + price_nanos / 1e9) <= {max_val}")
            except (ValueError, TypeError):
                logger.error(f"Invalid max_price: {max_price}")
                return json.dumps({"status": "error", "error": "Invalid max_price parameter", "total": 0, "products": []})
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        rows = executor.execute(
            f"""
            SELECT id, name, description, categories, price_units, price_nanos
            FROM products
            WHERE {where_sql}
            ORDER BY (price_units + price_nanos / 1e9) ASC
            """,
            limit=limit,
        )
        
        if not rows:
            return json.dumps({"status": "empty", "total": 0, "products": []})

        products = []
        for r in rows:
            price_u = r.get("price_units", 0) or 0
            price_n = r.get("price_nanos", 0) or 0
            products.append({
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "price": round(price_u + price_n / 1e9, 2),
                "categories": r.get("categories", ""),
            })

        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
            "filters_applied": {
                "min_price": min_price,
                "max_price": max_price,
            }
        })
    except Exception as e:
        logger.error(f"get_products_by_price_range error: {e}")
        return json.dumps({"status": "error", "error": str(e)[:200], "total": 0, "products": []})

