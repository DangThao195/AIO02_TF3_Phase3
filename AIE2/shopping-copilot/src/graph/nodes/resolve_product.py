"""
graph/nodes/resolve_product.py — ResolveProductNode (centralized).

Centralized product resolution node.
Flow: product_name → search_products_v2 (fuzzy) → extract match
      → get_product_id (canonical) → current_product_id

Được gọi trong main_graph SAU entity_extractor và TRƯỚC router.
Tất cả workflows downstream đều dùng current_product_id từ state.

Input:  state["entities"]["product_name"]
Output: state["current_product_id"]
        state["resolved_product_name"]
"""

from __future__ import annotations

import json
import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.resolve_product")


class ResolveProductNode:
    """
    Node tra cứu product_id tập trung.
    Dùng search_products_v2 để fuzzy match, sau đó get_product_id để lấy canonical ID.

    Nếu không có product_name trong entities → skip (không set gì).
    Nếu search không tìm thấy → current_product_id = None.
    """

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        entities = state.get("entities", {})
        product_name = entities.get("product_name")

        if not product_name:
            logger.debug("[RESOLVE_PRODUCT] No product_name in entities, skipping")
            return {"node_durations": {"ResolveProduct": _ms(t0)}}

        logger.info("[RESOLVE_PRODUCT] Resolving: product_name=%s", product_name)

        # ── Step 1: search_products_v2 (fuzzy match) ──
        from src.tools import search_products_v2

        exact_name = product_name
        products = []

        try:
            search_result = await search_products_v2.ainvoke({"query": product_name})
            data = json.loads(search_result) if isinstance(search_result, str) else search_result
            products = data.get("products", [])

            if products:
                best = products[0]
                exact_name = best.get("name", product_name)
                logger.info(
                    "[RESOLVE_PRODUCT] Search found: '%s' → best match: '%s'",
                    product_name, exact_name
                )
            else:
                logger.warning("[RESOLVE_PRODUCT] Search returned 0 products for: %s", product_name)
        except Exception as e:
            logger.warning("[RESOLVE_PRODUCT] search_products_v2 error: %s", e)

        # ── Step 2: get_product_id (canonical ID) ──
        from src.tools import get_product_id

        product_id = None
        try:
            pid_result = await get_product_id.ainvoke({"product_name": exact_name})

            if isinstance(pid_result, str):
                try:
                    data = json.loads(pid_result)
                    product_id = data.get("product_id") or data.get("id")
                except (json.JSONDecodeError, AttributeError):
                    if pid_result and len(pid_result) < 100 and "not found" not in pid_result.lower():
                        product_id = pid_result.strip()

            elif isinstance(pid_result, dict):
                product_id = pid_result.get("product_id") or pid_result.get("id")

            if product_id:
                logger.info("[RESOLVE_PRODUCT] Resolved: '%s' → %s", exact_name, product_id)
            else:
                logger.warning("[RESOLVE_PRODUCT] get_product_id returned not found: %s", exact_name)
        except Exception as e:
            logger.error("[RESOLVE_PRODUCT] get_product_id error: %s", e)

        return {
            "current_product_id": product_id,
            "resolved_product_name": exact_name if product_id else None,
            "node_durations": {"ResolveProduct": _ms(t0)},
        }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000
