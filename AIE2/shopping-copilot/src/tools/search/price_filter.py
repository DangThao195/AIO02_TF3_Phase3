"""
tools/search/price_filter.py — price_filter tool
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger("tools.price_filter")


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
            ORDER BY price_units ASC, name ASC
        """
        cur.execute(query, params)
        rows = cur.fetchall()
        products = []
        for row in rows:
            pid, name, desc, cats_raw, units, nanos = row
            units = units or 0
            nanos = nanos or 0
            cents = nanos // 10_000_000
            cats = [c.strip() for c in str(cats_raw or "").split(",") if c.strip()]
            products.append({
                "id": pid,
                "name": name,
                "price": f"${units}.{cents:02d}",
                "description": desc or "",
                "categories": cats,
            })
        return products
    finally:
        conn.close()


@tool
def price_filter(min_price: float = 0.0, max_price: float = 999999.0, previous_ids: Optional[list[str]] = None) -> str:
    """
    Lọc sản phẩm theo khoảng giá (USD).
    Nếu previous_ids=None, lọc từ tất cả sản phẩm.
    Nếu previous_ids != None, lọc subset đó theo giá.
    Trả về JSON: {status, total, products[], filter_applied}
    """
    try:
        if previous_ids:
            placeholders = ",".join("?" for _ in previous_ids)
            where = "WHERE price_units >= ? AND price_units <= ? AND id IN ({})".format(placeholders)
            params = (int(min_price), int(max_price), *previous_ids)
        else:
            where = "WHERE price_units >= ? AND price_units <= ?"
            params = (int(min_price), int(max_price))

        products = _fetch_products(where, params)
        return json.dumps({
            "status": "success",
            "total": len(products),
            "products": products,
            "filter_applied": {"type": "price", "min_price": min_price, "max_price": max_price},
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[price_filter] error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": f"Lỗi: {str(e)[:200]}", "total": 0, "products": []})


from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="price_filter",
    description=(
        "Lọc sản phẩm theo khoảng giá (USD). "
        "Dùng khi user nói 'dưới X đô', 'từ X đến Y đô', 'trên X đô', 'giá rẻ nhất'. "
        "Có thể dùng standalone hoặc trong multi_filter chain. "
        "Nếu cần kết hợp với các điều kiện khác, dùng multi_filter thay vì tự truyền previous_ids."
    ),
    is_write=False,
    input_schema={"type": "object", "properties": {
        "min_price": {"type": "number", "description": "Giá tối thiểu (USD), default 0"},
        "max_price": {"type": "number", "description": "Giá tối đa (USD), default 999999"},
        "previous_ids": {"type": "array", "items": {"type": "string"}, "description": "Danh sách product_id để filter (từ filter trước trong chain)"},
    }},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"}, "total": {"type": "integer"},
        "products": {"type": "array"}, "filter_applied": {"type": "object"},
    }},
    examples=[
        {"input": {"max_price": 100}, "output": {"status": "success", "total": 8}},
        {"input": {"min_price": 50, "max_price": 200}, "output": {"status": "success", "total": 6}},
        {"input": {"min_price": 500}, "output": {"status": "success", "total": 2}},
    ],
    retry_config={"max_retries": 2, "backoff": [0.5]},
), fn=price_filter)
