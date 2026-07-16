"""
graph/nodes/get_product_id.py — GetProductIDNode.

Shared node dùng chung cho Review, Recommend, Cart, Shipping workflows.
Lookup product_id từ product_name trong entities.

Output: state["current_product_id"]
"""

from __future__ import annotations

import json
import time
import logging
from typing import TYPE_CHECKING

from src.tools.product_id_tool import get_product_id

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.get_product_id")


class GetProductIDNode:
    """
    Node tra cứu product_id từ product_name.

    Input:  state["entities"]["product_name"]
    Output: state["current_product_id"] (None nếu không tìm thấy)

    Kết quả None → workflow route về "skip" edge (xem edges.py).
    """

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        entities = state.get("entities", {})
        product_name = entities.get("product_name")

        if not product_name:
            logger.warning("[GET_PRODUCT_ID] Không có product_name trong entities")
            return {
                "current_product_id": None,
                "errors": [{"node": "GetProductID", "error": "No product_name in entities"}],
                "node_durations": {"GetProductID": _ms(t0)},
            }

        logger.info("[GET_PRODUCT_ID] Looking up: product_name=%s", product_name)

        try:
            result = await get_product_id.ainvoke({"product_name": product_name})

            # Parse result — có thể là JSON string hoặc plain string
            product_id = None
            if isinstance(result, str):
                try:
                    data = json.loads(result)
                    product_id = data.get("product_id") or data.get("id")
                except (json.JSONDecodeError, AttributeError):
                    # Nếu result là plain product_id string
                    if result and len(result) < 100 and "not found" not in result.lower():
                        product_id = result.strip()

            elif isinstance(result, dict):
                product_id = result.get("product_id") or result.get("id")

            if product_id:
                logger.info("[GET_PRODUCT_ID] Found: %s → %s", product_name, product_id)
            else:
                logger.warning("[GET_PRODUCT_ID] Not found: %s", product_name)

            return {
                "current_product_id": product_id,
                "node_durations": {"GetProductID": _ms(t0)},
            }

        except Exception as e:
            logger.error("[GET_PRODUCT_ID] Error: %s", e)
            return {
                "current_product_id": None,
                "errors": [{"node": "GetProductID", "error": str(e)[:200]}],
                "node_durations": {"GetProductID": _ms(t0)},
            }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000
