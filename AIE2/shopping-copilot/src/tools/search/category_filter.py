"""
tools/search/category_filter.py — category_filter tool
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger("tools.category_filter")


def _get_db_path() -> str:
    candidates = []
    fp = Path(__file__).resolve()
    for base in [fp.parents[4], fp.parents[3], fp.parents[2], fp.parents[1], Path.cwd()]:
        candidates.append(base / "server-test" / "shopping.db")
        candidates.append(base / "shopping.db")
    for c in candidates:
        if c.exists():
            return str(c)
    raise FileNotFoundError("Không tìm thấy file shopping.db")


def _fetch_products(where_clause: str, params: tuple) -> list[dict]:
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        query = f"""
            SELECT id, name, description, categories, price_units, price_nanos
            FROM products {where_clause}
            ORDER BY name
        """
        cur.execute(query, params)
        rows = cur.fetchall()
        products = []
        for row in rows:
            pid, name, desc, cats_raw, units, nanos = row
            cents = (nanos or 0) // 10_000_000
            cats = [c.strip() for c in str(cats_raw or "").split(",") if c.strip()]
            products.append({
                "id": pid,
                "name": name,
                "price": f"${units}.{cents:02d}" if (units or cents) else "$0.00",
                "description": desc or "",
                "categories": cats,
            })
        return products
    finally:
        conn.close()


@tool
def category_filter(name: str, previous_ids: Optional[list[str]] = None) -> str:
    """
    Lọc sản phẩm theo danh mục.
    Nếu previous_ids=None, lấy tất cả sản phẩm trong danh mục.
    Nếu previous_ids != None, lọc subset đó theo danh mục.
    Trả về JSON: {status, total, products[], filter_applied}
    """
    try:
        name_lower = name.lower().rstrip("s")
        if previous_ids:
            placeholders = ",".join("?" for _ in previous_ids)
            where = "WHERE LOWER(categories) LIKE ? AND id IN ({})".format(placeholders)
            params = (f"%{name_lower}%", *previous_ids)
        else:
            where = "WHERE LOWER(categories) LIKE ?"
            params = (f"%{name_lower}%",)

        products = _fetch_products(where, params)
        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
            "filter_applied": {"type": "category", "name": name},
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[category_filter] error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": f"Lỗi: {str(e)[:200]}", "total": 0, "products": []})


from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="category_filter",
    description=(
        "Lọc sản phẩm theo danh mục (VD: 'telescopes', 'binoculars', 'books', 'accessories'). "
        "Dùng khi user hỏi 'sản phẩm trong danh mục X', 'có kính thiên văn không', 'đồ thiên văn'. "
        "Nếu cần kết hợp nhiều điều kiện (vd: category + giá), dùng multi_filter thay vì tự truyền previous_ids."
    ),
    is_write=False,
    input_schema={"type": "object", "properties": {
        "name": {"type": "string", "description": "Tên danh mục (tiếng Anh, VD: telescopes, binoculars, books)"},
        "previous_ids": {"type": "array", "items": {"type": "string"}, "description": "Danh sách product_id để filter (từ filter trước trong chain)"},
    }, "required": ["name"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"}, "total": {"type": "integer"},
        "products": {"type": "array"}, "filter_applied": {"type": "object"},
    }},
    examples=[
        {"input": {"name": "telescopes"}, "output": {"status": "success", "total": 5}},
        {"input": {"name": "binoculars"}, "output": {"status": "success", "total": 3}},
        {"input": {"name": "books"}, "output": {"status": "success", "total": 4}},
    ],
    retry_config={"max_retries": 2, "backoff": [0.5]},
), fn=category_filter)
