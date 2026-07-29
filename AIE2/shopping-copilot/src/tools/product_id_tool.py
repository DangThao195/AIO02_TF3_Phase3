"""tools/product_id_tool.py — Resolve product_id from product name. Returns normalized JSON."""

import json
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

from src.database.connect import get_conn, init_pool


@tool
def get_product_id(product_name: str) -> str:
    """
    Tra cứu mã product_id từ tên sản phẩm (không phân biệt hoa thường).
    Dùng sau search_products_v2 khi cần product_id để gọi các tool khác
    (get_product_reviews_tool, add_to_cart_tool, get_recommendations_tool).
    Returns JSON: {"status": "success"|"not_found", "product_id", "product_name"}
    """
    name = (product_name or "").strip()
    if not name:
        return json.dumps({"status": "error", "error": "Product name is required.", "product_id": "", "product_name": ""})

    search_pattern = f"%{name.lower()}%"

    # Try PostgreSQL first
    try:
        init_pool()
        with get_conn() as conn:
            cur = conn.cursor()
            # Try exact case-insensitive match first
            cur.execute("SELECT id, name FROM products WHERE LOWER(name) = LOWER(%s)", (name,))
            row = cur.fetchone()
            if not row:
                # Try wildcard match
                cur.execute("SELECT id, name FROM products WHERE LOWER(name) LIKE %s", (search_pattern,))
                row = cur.fetchone()
            
            if row:
                return json.dumps({"status": "success", "product_id": str(row[0]), "product_name": row[1]})
    except Exception:
        pass

    # Fallback to SQLite
    try:
        candidates = []
        file_path = Path(__file__).resolve()
        for base in [file_path.parents[4], file_path.parents[3], file_path.parents[2], file_path.parents[1], Path.cwd()]:
            candidates.append(base / "server-test" / "shopping.db")
            candidates.append(base / "shopping.db")
        db_path = None
        for candidate in candidates:
            if candidate.exists():
                db_path = candidate
                break
        
        if db_path is not None:
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.cursor()
                # Try exact case-insensitive match
                cur.execute("SELECT id, name FROM products WHERE LOWER(name) = LOWER(?)", (name,))
                row = cur.fetchone()
                if not row:
                    # Try wildcard match
                    cur.execute("SELECT id, name FROM products WHERE LOWER(name) LIKE ?", (search_pattern,))
                    row = cur.fetchone()
                
                if row:
                    return json.dumps({"status": "success", "product_id": str(row[0]), "product_name": row[1]})
            finally:
                conn.close()
    except Exception:
        pass

    return json.dumps({"status": "not_found", "product_id": "", "product_name": name})


__all__ = ["get_product_id"]
