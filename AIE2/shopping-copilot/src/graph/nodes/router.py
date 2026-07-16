"""
graph/nodes/router.py — Router node.

Phase 1: Router đơn giản — đặt intent = "agent" (stub).
Phase 2: IntentClassifier node sẽ set intent trước khi Router chạy.

Router node không thay đổi intent, chỉ log và pass-through.
Conditional edge route_to_workflow() đọc intent từ state để quyết định workflow.
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.router")


class Router:
    """
    Router node: đọc intent từ state, log routing decision.

    Phase 1: intent luôn là "agent" (set bởi default_state hoặc IntentClassifier stub).
    Phase 2: IntentClassifier đã set intent trước → Router chỉ log và pass-through.
    """

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()
        intent = state.get("intent", "agent")
        intent_source = state.get("intent_source", "default")
        session_id = state.get("session_id", "")

        logger.info(
            "[ROUTER] session=%s | intent=%s | source=%s",
            session_id, intent, intent_source,
        )

        # Router không thay đổi state — chỉ pass-through
        # Conditional edge route_to_workflow() sẽ đọc intent từ state
        return {
            "node_durations": {"Router": (time.monotonic_ns() - t0) // 1_000_000},
        }
