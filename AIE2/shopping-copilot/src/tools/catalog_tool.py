"""
tools/catalog_tool.py — get_categories, get_all_products

Backend: SQLite/PostgreSQL trực tiếp
"""

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger("tools.catalog")


def _get_db_conn():
    """Thử PostgreSQL, fallback SQLite."""
    try:
        from src.database.connect import get_conn
        return get_conn, "pg"
    except Exception:
        pass
    # SQLite fallback
    import sqlite3
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(root, "server-test", "shopping.db")
    return sqlite3.connect(db_path), "sqlite"


def _normalize_price(units: int, nanos: int) -> str:
    cents = nanos // 10_000_000
    return f"${units}.{cents:02d}"


@tool
def get_categories() -> str:
    """
    Lấy danh sách tất cả danh mục sản phẩm hiện có trong hệ thống (sorted A-Z).
    Trả về JSON: {status, categories[], total}
    """
    try:
        import sqlite3, os
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(root, "server-test", "shopping.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT categories FROM products WHERE categories IS NOT NULL AND categories != ''")
            rows = cursor.fetchall()
        finally:
            conn.close()

        cats: set = set()
        for (raw,) in rows:
            for c in str(raw).split(","):
                c = c.strip()
                if c:
                    cats.add(c)

        sorted_cats = sorted(cats)
        if not sorted_cats:
            return json.dumps({"status": "empty", "categories": [], "total": 0})

        return json.dumps({"status": "success", "categories": sorted_cats, "total": len(sorted_cats)},
                          ensure_ascii=False)
    except Exception as e:
        logger.error("[get_categories] error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ không khả dụng."})


@tool
def get_all_products() -> str:
    """
    Lấy toàn bộ danh sách sản phẩm. CHỈ dùng khi user yêu cầu 'tất cả sản phẩm'.
    Trả về JSON: {status, products[], total}
    """
    try:
        import sqlite3, os
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(root, "server-test", "shopping.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, description, categories, price_units, price_nanos
                FROM products ORDER BY name LIMIT 100
            """)
            rows = cursor.fetchall()
        finally:
            conn.close()

        products = []
        for row in rows:
            pid, name, desc, cats_raw, units, nanos = row
            cats = [c.strip() for c in str(cats_raw or "").split(",") if c.strip()]
            products.append({
                "id": pid,
                "name": name,
                "price": _normalize_price(units or 0, nanos or 0),
                "description": desc or "",
                "categories": cats,
            })

        return json.dumps({"status": "success", "products": products, "total": len(products)},
                          ensure_ascii=False)
    except Exception as e:
        logger.error("[get_all_products] error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ không khả dụng."})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_categories",
    description="Lấy danh sách tất cả danh mục sản phẩm hiện có trong hệ thống.",
    is_write=False,
    input_schema={"type": "object", "properties": {}, "required": []},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"}, "categories": {"type": "array"}, "total": {"type": "integer"},
    }},
    examples=[{"input": {}, "output": {"status": "success", "categories": ["telescopes", "books"], "total": 2}}],
    retry_config={"max_retries": 2, "backoff": [0.5]},
), fn=get_categories)

ToolRegistry.register(ToolSpec(
    name="get_all_products",
    description="Lấy toàn bộ danh sách sản phẩm (CHỈ dùng khi user yêu cầu 'tất cả sản phẩm' — không dùng để tìm kiếm).",
    is_write=False,
    input_schema={"type": "object", "properties": {}, "required": []},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"}, "products": {"type": "array"}, "total": {"type": "integer"},
    }},
    retry_config={"max_retries": 2, "backoff": [0.5]},
), fn=get_all_products)
