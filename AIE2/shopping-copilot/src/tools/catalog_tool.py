"""
tools/catalog_tool.py — Công cụ truy vấn danh mục và toàn bộ sản phẩm.
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
            return "Không có danh mục nào trong hệ thống."
        return "Các danh mục sản phẩm hiện có:\n" + "\n".join(f"- {c}" for c in sorted(categories))
    except Exception as e:
        logger.error(f"get_categories error: {e}")
        return "Dịch vụ tạm thời không khả dụng, vui lòng thử lại sau."


@tool
def get_all_products() -> str:
    """
    Lấy toàn bộ thông tin sản phẩm trong database (tên, giá, mô tả, danh mục).
    CHỈ DÙNG khi thực sự cần thiết: khi người dùng yêu cầu danh sách đầy đủ tất cả sản phẩm
    (VD: "liệt kê tất cả sản phẩm", "show all products", "bán những gì", "danh sách full"),
    xuất dữ liệu kho hàng, hoặc kiểm kê toàn bộ danh mục.
    KHÔNG dùng để tìm kiếm thông thường — dùng search_products_v2 cho mục đích đó.
    Không cần tham số đầu vào.
    """
    try:
        executor = SQLQueryExecutor()
        executor.ensure_initialized()
        rows = executor.execute(
            "SELECT id, name, description, categories, price_units, price_nanos FROM products ORDER BY name",
            limit=100,
        )
        if not rows:
            return "Không có sản phẩm nào trong hệ thống."

        parts = [f"Toàn bộ sản phẩm ({len(rows)} sản phẩm):"]
        for r in rows:
            name = r.get("name", "N/A")
            price_u = r.get("price_units", 0)
            price_n = r.get("price_nanos", 0)
            price = f"${price_u}.{str(price_n).zfill(9)}"
            cats = r.get("categories", "")
            cat_str = f" [{cats}]" if cats else ""
            desc = (r.get("description", "") or "")[:80]
            parts.append(f"- {name} - {price}{cat_str} — {desc}")
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"get_all_products error: {e}")
        return "Dịch vụ tạm thời không khả dụng, vui lòng thử lại sau."
