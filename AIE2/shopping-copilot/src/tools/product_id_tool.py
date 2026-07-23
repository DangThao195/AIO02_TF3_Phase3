"""
tools/product_id_tool.py — get_product_id

Backend: SQLite/PostgreSQL trực tiếp — tra product_id từ tên sản phẩm.
"""

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger("tools.product_id")


@tool
def get_product_id(product_name: str) -> str:
    """
    Tra cứu mã product_id từ tên sản phẩm chính xác.
    Trả về JSON: {status, product_id, product_name}
    """
    if not product_name or not product_name.strip():
        return json.dumps({"status": "error", "message": "Vui lòng nhập tên sản phẩm."})

    try:
        import sqlite3, os
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(root, "server-test", "shopping.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Exact match trước
        cursor.execute("SELECT id, name FROM products WHERE name = ? LIMIT 1", (product_name,))
        row = cursor.fetchone()

        # Fallback: LIKE match (case-insensitive)
        if not row:
            cursor.execute("SELECT id, name FROM products WHERE LOWER(name) LIKE ? LIMIT 1",
                           (f"%{product_name.lower()}%",))
            row = cursor.fetchone()

        conn.close()

        if row:
            return json.dumps({"status": "success", "product_id": row[0], "product_name": row[1]},
                              ensure_ascii=False)
        return json.dumps({"status": "not_found",
                           "message": f"Không tìm thấy sản phẩm '{product_name}'."})
    except Exception as e:
        logger.error("[get_product_id] error: %s", e)
        return json.dumps({"status": "error", "message": "Dịch vụ không khả dụng."})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_product_id",
    description="Tra cứu mã product_id từ tên sản phẩm chính xác. Dùng khi cần product_id để gọi tool khác.",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "product_name": {"type": "string", "description": "Tên sản phẩm chính xác"},
    }, "required": ["product_name"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string", "enum": ["success", "not_found", "error"]},
        "product_id": {"type": "string"},
        "product_name": {"type": "string"},
        "message": {"type": "string"},
    }},
    examples=[{"input": {"product_name": "Vintage Typewriter"},
               "output": {"status": "success", "product_id": "OLJCESPC7Z"}}],
    retry_config={"max_retries": 2, "backoff": [0.5]},
), fn=get_product_id)
