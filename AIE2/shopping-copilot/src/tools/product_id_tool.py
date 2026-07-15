import sqlite3
from pathlib import Path

from langchain_core.tools import tool

from src.database.connect import get_conn, init_pool


@tool
def get_product_id(product_name: str) -> str:
    """
    Tra cứu mã product_id từ tên sản phẩm (chính xác).
    Dùng sau search_products_v2 khi cần product_id để gọi các tool khác
    (get_product_reviews_tool, add_to_cart_tool, get_recommendations_tool).
    """
    name = (product_name or "").strip()
    if not name:
        return "Vui lòng nhập tên sản phẩm."

    try:
        init_pool()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM products WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                return str(row[0])
    except Exception:
        pass

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
        if db_path is None:
            return f"Không tìm thấy sản phẩm '{product_name}'."
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM products WHERE name = ?", (name,))
            row = cur.fetchone()
            if row:
                return str(row[0])
        finally:
            conn.close()
    except Exception:
        pass

    return f"Không tìm thấy sản phẩm '{product_name}'."


__all__ = ["get_product_id"]
