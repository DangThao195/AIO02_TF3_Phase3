import json
import logging
from typing import Optional

logger = logging.getLogger("tools.product_resolver")


async def resolve_product_id(
    product_name: str,
    search_results: Optional[list] = None,
) -> Optional[str]:
    if not product_name or not product_name.strip():
        return None

    from src.tools.search.orchestrator import SearchOrchestrator
    from src.tools.search.tracer import SearchTracer

    if search_results:
        for p in search_results:
            name = p.get("name", "") if isinstance(p, dict) else getattr(p, "name", "")
            pid = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
            if product_name.lower() in name.lower():
                return pid

    tracer = SearchTracer()
    orch = SearchOrchestrator()
    result = await orch.search(product_name, tracer=tracer)

    if result.products and len(result.products) > 0:
        sp = result.products[0]
        return sp.product.id

    import sqlite3, os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(root, "server-test", "shopping.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM products WHERE LOWER(name) LIKE ? LIMIT 1",
            (f"%{product_name.lower()}%",),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception as e:
        logger.warning(f"product_resolver sqlite fallback failed: {e}")

    return None
