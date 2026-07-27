"""
tools/search/semantic_filter.py — semantic_filter tool
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from src.tools.search.flow2.kb_client import BedrockRAGStrategy
from src.tools.search.models import SearchQuery, Money, Product, ScoredProduct
from src.database.connect import get_conn

logger = logging.getLogger("tools.semantic_filter")


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


def _filter_by_ids(product_ids: list[str]) -> dict:
    """Filter products by a list of IDs — dùng khi previous_ids được cung cấp."""
    if not product_ids:
        return {"status": "success", "total": 0, "products": [], "filter_applied": {"type": "semantic_filter"}}

    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in product_ids)
        query = f"""
            SELECT id, name, description, categories, price_units, price_nanos
            FROM products WHERE id IN ({placeholders})
            ORDER BY name
        """
        cur.execute(query, product_ids)
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
        return {"status": "success", "total": len(products), "products": products}
    finally:
        conn.close()


@tool
async def semantic_filter(query: str, previous_ids: Optional[list[str]] = None) -> str:
    """
    Tìm kiếm sản phẩm theo ngữ nghĩa (dùng Bedrock RAG semantic search).
    Hỗ trợ tiếng Việt và tiếng Anh.
    Nếu previous_ids=None, tìm từ tất cả sản phẩm.
    Nếu previous_ids != None, tìm trong subset đó.
    Trả về JSON: {status, total, products[], filter_applied}
    """
    try:
        # Use Bedrock RAG strategy directly for semantic search
        rag_strategy = BedrockRAGStrategy()
        
        if not rag_strategy.should_run(SearchQuery(raw=query)):
            logger.warning("[semantic_filter] BEDROCK_KB_ID not configured, falling back to SQL search")
            return await _fallback_sql_search(query, previous_ids)

        sq = SearchQuery(raw=query)
        results = await rag_strategy.search(sq)

        if not results:
            return json.dumps({
                "status": "success",
                "total": 0,
                "products": [],
                "filter_applied": {"type": "semantic", "query": query},
            }, ensure_ascii=False)

        # Filter by previous_ids if provided
        if previous_ids:
            id_set = set(previous_ids)
            results = [sp for sp in results if sp.product.id in id_set]

        products_json = []
        for sp in results:
            p = sp.product
            units = getattr(p.price_usd, "units", 0)
            nanos = getattr(p.price_usd, "nanos", 0)
            cents = nanos // 10_000_000
            cats = p.categories
            if isinstance(cats, str):
                cats = [c.strip() for c in cats.split(",") if c.strip()]
            products_json.append({
                "id": p.id,
                "name": p.name,
                "price": f"${units}.{cents:02d}" if (units or cents) else "$0.00",
                "description": p.description,
                "categories": cats,
            })

        return json.dumps({
            "status": "success",
            "total": len(products_json),
            "products": products_json,
            "filter_applied": {"type": "semantic", "query": query},
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("[semantic_filter] error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": f"Lỗi: {str(e)[:200]}", "total": 0, "products": []})


async def _fallback_sql_search(query: str, previous_ids: Optional[list[str]] = None) -> str:
    """Fallback SQL search when Bedrock RAG is not available."""
    try:
        from src.tools.search.query_analyzer import QueryAnalyzerPipeline
        from src.tools.search.synonym_cache import SynonymCache
        
        analyzer = QueryAnalyzerPipeline(SynonymCache())
        entities = analyzer.analyze(query)
        
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            
            # Build WHERE clause
            where_parts = []
            params = []
            
            if entities.get("category"):
                where_parts.append("LOWER(categories) LIKE ?")
                params.append(f"%{entities['category'].lower()}%")
            
            if entities.get("keywords"):
                kw_parts = []
                for kw in entities["keywords"]:
                    kw_parts.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(categories) LIKE ?)")
                    kw_lower = kw.lower()
                    params.extend([f"%{kw_lower}%", f"%{kw_lower}%", f"%{kw_lower}%"])
                if kw_parts:
                    where_parts.append("(" + " OR ".join(kw_parts) + ")")
            
            if previous_ids:
                placeholders = ",".join("?" for _ in previous_ids)
                where_parts.append(f"id IN ({placeholders})")
                params.extend(previous_ids)
            
            where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
            
            query_sql = f"""
                SELECT id, name, description, categories, price_units, price_nanos
                FROM products {where_clause}
                ORDER BY name
            """
            cur.execute(query_sql, params)
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
            
            return json.dumps({
                "status": "success",
                "total": len(products),
                "products": products,
                "filter_applied": {"type": "semantic", "query": query},
            }, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        logger.error("[semantic_filter] fallback error | %s", e, exc_info=True)
        return json.dumps({"status": "error", "message": f"Lỗi fallback: {str(e)[:200]}", "total": 0, "products": []})


from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="semantic_filter",
    description=(
        "Tìm kiếm sản phẩm theo ngữ nghĩa từ mô tả, tên, danh mục. "
        "Hỗ trợ tiếng Việt và tiếng Anh. Dùng RAG + SQL matching để có kết quả chính xác nhất. "
        "Dùng khi user mô tả sản phẩm bằng ngôn ngữ tự nhiên, "
        "VD: 'kính thiên văn cho người mới bắt đầu', 'beginner telescope', 'sách về thiên văn học'. "
        "Nếu cần kết hợp với category/price filter, dùng multi_filter."
    ),
    is_write=False,
    input_schema={"type": "object", "properties": {
        "query": {"type": "string", "description": "Câu mô tả bằng tiếng Việt hoặc tiếng Anh"},
        "previous_ids": {"type": "array", "items": {"type": "string"}, "description": "Danh sách product_id để filter (từ filter trước trong chain)"},
    }, "required": ["query"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"}, "total": {"type": "integer"},
        "products": {"type": "array"}, "filter_applied": {"type": "object"},
    }},
    examples=[
        {"input": {"query": "beginner astronomy telescope"}, "output": {"status": "success", "total": 3}},
        {"input": {"query": "book about constellations"}, "output": {"status": "success", "total": 2}},
        {"input": {"query": "night vision observation equipment"}, "output": {"status": "success", "total": 4}},
    ],
    retry_config={"max_retries": 2, "backoff": [0.5]},
), fn=semantic_filter)