"""
tools/search/multi_filter.py — multi_filter tool

Chuỗi filter tuần tự: kết quả filter trước là input của filter sau.
Mỗi filter trong list là dict: {"type": "category"|"price"|"semantic", ...params}
"""

import asyncio
import json
import logging
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

from src.tools.search.category_filter import category_filter
from src.tools.search.price_filter import price_filter
from src.tools.search.semantic_filter import semantic_filter

logger = logging.getLogger("tools.multi_filter")


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


def _all_products() -> list[dict]:
    """Lấy tất cả sản phẩm từ database."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, description, categories, price_units, price_nanos
            FROM products ORDER BY name
        """)
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


def _parse_result(raw: str) -> dict:
    """Parse JSON string result từ filter tool."""
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {"status": "error", "total": 0, "products": []}


async def _run_filter(f: dict, previous_ids: list[str] | None) -> dict:
    """Run một filter trong chain. Trả về parsed result dict."""
    typ = f.get("type", "")
    if typ == "category":
        name = f.get("name", "")
        raw = await category_filter(name, previous_ids)
    elif typ == "price":
        min_p = f.get("min_price", 0.0)
        max_p = f.get("max_price", 999999.0)
        raw = await price_filter(float(min_p), float(max_p), previous_ids)
    elif typ == "semantic":
        query = f.get("query", "")
        raw = await semantic_filter(query, previous_ids)
    else:
        return {"status": "error", "total": 0, "products": [], "error": f"Unknown filter type: {typ}"}
    return _parse_result(raw)


@tool
async def multi_filter(filters: list[dict]) -> str:
    """
    Chuỗi filter tuần tự: kết quả filter trước là input của filter sau.
    filters: list[dict], mỗi dict gồm {"type": "category"|"price"|"semantic", ...params}

    Ví dụ: [{"type": "category", "name": "telescopes"},
            {"type": "price", "max_price": 100},
            {"type": "semantic", "query": "beginner friendly"}]

    Thứ tự quan trọng: category → price → semantic (tối ưu).
    KHÔNG hỗ trợ lồng multi_filter.
    Trả về JSON: {status, total, products[], filter_chain}
    """
    try:
        if not filters:
            all_products = _all_products()
            return json.dumps({
                "status": "success",
                "total": len(all_products),
                "products": all_products,
                "filter_chain": [],
            }, ensure_ascii=False)

        previous_ids = None
        chain_log = []

        for idx, f in enumerate(filters):
            logger.info("[multi_filter] step %d: %s | previous_ids=%s", idx, f, previous_ids)
            result = await _run_filter(f, previous_ids)
            chain_log.append({"step": idx, "filter": f, "total": result.get("total", 0)})

            if result.get("status") == "error":
                logger.warning("[multi_filter] step %d failed: %s", idx, result.get("error", ""))
                return json.dumps({
                    "status": "error",
                    "message": result.get("message", f"Filter step {idx} failed"),
                    "total": 0,
                    "products": [],
                    "filter_chain": chain_log,
                })

            products = result.get("products", [])
            if not products:
                return json.dumps({
                    "status": "success",
                    "total": 0,
                    "products": [],
                    "filter_chain": chain_log,
                })

            previous_ids = [p["id"] for p in products]

        # Lấy thông tin đầy đủ cho kết quả cuối cùng
        if previous_ids:
            db_path = _get_db_path()
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                placeholders = ",".join("?" for _ in previous_ids)
                cur.execute(f"""
                    SELECT id, name, description, categories, price_units, price_nanos
                    FROM products WHERE id IN ({placeholders})
                    ORDER BY name
                """, previous_ids)
                rows = cur.fetchall()
                final_products = []
                for row in rows:
                    pid, name, desc, cats_raw, units, nanos = row
                    units = units or 0
                    nanos = nanos or 0
                    cents = nanos // 10_000_000
                    cats = [c.strip() for c in str(cats_raw or "").split(",") if c.strip()]
                    final_products.append({
                        "id": pid,
                        "name": name,
                        "price": f"${units}.{cents:02d}",
                        "description": desc or "",
                        "categories": cats,
                    })
            finally:
                conn.close()
        else:
            final_products = []

        return json.dumps({
            "status": "success",
            "total": len(final_products),
            "products": final_products,
            "filter_chain": chain_log,
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("[multi_filter] error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": f"Lỗi: {str(e)[:200]}", "total": 0, "products": []})


from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="multi_filter",
    description=(
        "Lọc sản phẩm theo chuỗi filter tuần tự. Kết quả của filter trước làm input cho filter sau. "
        "Dùng KHI CẦN KẾT HỢP NHIỀU ĐIỀU KIỆN: danh mục + giá + tìm kiếm ngữ nghĩa. "
        "Mỗi filter là dict với 'type' (category|price|semantic) và các param tương ứng. "
        "Thứ tự khuyến nghị: category → price → semantic. "
        "KHÔNG dùng cho filter đơn lẻ — dùng category_filter, price_filter, semantic_filter riêng. "
        "KHÔNG lồng multi_filter trong multi_filter."
    ),
    is_write=False,
    input_schema={"type": "object", "properties": {
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["category", "price", "semantic"]},
                    "name": {"type": "string"},
                    "min_price": {"type": "number"},
                    "max_price": {"type": "number"},
                    "query": {"type": "string"},
                },
                "required": ["type"],
            },
        },
    }, "required": ["filters"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"}, "total": {"type": "integer"},
        "products": {"type": "array"}, "filter_chain": {"type": "array"},
    }},
    examples=[
        {"input": {"filters": [{"type": "category", "name": "telescopes"}, {"type": "price", "max_price": 100}]},
         "output": {"status": "success", "total": 2}},
        {"input": {"filters": [{"type": "category", "name": "telescopes"}, {"type": "price", "max_price": 200}, {"type": "semantic", "query": "beginner friendly telescope"}]},
         "output": {"status": "success", "total": 1}},
        {"input": {"filters": [{"type": "category", "name": "books"}, {"type": "price", "max_price": 30}, {"type": "semantic", "query": "children astronomy book"}]},
         "output": {"status": "success", "total": 1}},
    ],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=multi_filter)
