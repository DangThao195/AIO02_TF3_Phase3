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
