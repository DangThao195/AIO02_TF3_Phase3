"""
graph/nodes/tool_executor.py — ToolExecutor node (centralized).

Một node dùng chung cho tất cả tool calls trong các workflow.
Mỗi workflow tạo instance với tool_name cụ thể.

Thực hiện theo thứ tự:
  1. L4: Validate tool call (allow-list, parameter bounds, user isolation)
  2. Cache check (CacheStore)
  3. Execute với retry strategy per-tool
  4. Truthfulness guard (preserve exact message cho missing-item/empty-cart)
  5. Cache set (chỉ read-only tools)
  6. Accumulate errors vào state["errors"]
"""

from __future__ import annotations

import asyncio
import time
import json
import logging
from typing import Any, Optional, TYPE_CHECKING

from src.guardrails.tool_validator import validate_tool_call
from src.memory.store import CacheStore
from src.tools import (
    search_products_v2,
    get_categories,
    get_all_products,
    get_product_id,
    get_product_reviews_tool,
    add_to_cart_tool,
    get_cart_tool,
    check_cart_item_tool,
    get_recommendations_tool,
    convert_currency_tool,
    get_shipping_quote_tool,
)

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.tool_executor")

# ── Tool registry ──
TOOLS_MAP: dict[str, Any] = {
    "search_products_v2":       search_products_v2,
    "get_categories":           get_categories,
    "get_all_products":         get_all_products,
    "get_product_id":           get_product_id,
    "get_product_reviews_tool": get_product_reviews_tool,
    "add_to_cart_tool":         add_to_cart_tool,
    "get_cart_tool":            get_cart_tool,
    "check_cart_item_tool":     check_cart_item_tool,
    "get_recommendations_tool": get_recommendations_tool,
    "convert_currency_tool":    convert_currency_tool,
    "get_shipping_quote_tool":  get_shipping_quote_tool,
}

# ── Write tools (không cache) ──
WRITE_TOOLS = {"add_to_cart_tool", "get_cart_tool", "get_shipping_quote_tool"}

# ── Retry strategy per tool: (max_retries, fallback_strategy) ──
RETRY_STRATEGY: dict[str, tuple[int, Optional[str]]] = {
    "search_products_v2":       (2, "retry_broader"),
    "get_product_id":           (1, None),
    "get_recommendations_tool": (1, None),
    "get_product_reviews_tool": (1, None),
    "convert_currency_tool":    (2, None),
    "get_shipping_quote_tool":  (2, None),
    "check_cart_item_tool":     (1, None),
    "add_to_cart_tool":         (1, None),
}

# ── Truthfulness guard patterns ──
_DIRECT_RETURN_PATTERNS = (
    "not found",
    "không tìm thấy",
    "không tồn tại",
    "không có trong giỏ hàng",
    "empty cart",
    "giỏ hàng trống",
    "đang trống",
    "không có sản phẩm",
    "không có mặt hàng",
    "no products",
    "cart is empty",
    "out of stock",
    "hết hàng",
)

# Shared cache store instance (singleton per process)
_cache_store: Optional[CacheStore] = None

def _get_cache_store() -> CacheStore:
    global _cache_store
    if _cache_store is None:
        _cache_store = CacheStore()
    return _cache_store


# ──────────────────────────────────────────────────────────────────
# ToolExecutor
# ──────────────────────────────────────────────────────────────────

class ToolExecutor:
    """
    Centralized tool execution node.

    Usage:
        node = ToolExecutor("search_products_v2")
        # Trong workflow:
        builder.add_node("search_products", node)
    """

    def __init__(self, tool_name: str, args_builder=None):
        """
        Args:
            tool_name: Tên tool trong TOOLS_MAP
            args_builder: callable(state) -> dict
                Hàm tạo args từ state. Nếu None, dùng _default_args_builder.
        """
        if tool_name not in TOOLS_MAP:
            raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOLS_MAP.keys())}")

        self.tool_name = tool_name
        self.tool_fn = TOOLS_MAP[tool_name]
        max_retries, fallback = RETRY_STRATEGY.get(tool_name, (1, None))
        self.max_retries = max_retries
        self.fallback_strategy = fallback
        self._args_builder = args_builder or self._default_args_builder

        logger.debug("[TOOL_EXECUTOR] Init: tool=%s, retries=%d", tool_name, max_retries)

    def _default_args_builder(self, state: "ShoppingState") -> dict:
        """
        Default: build args từ entities + state fields phổ biến.
        Mỗi workflow có thể override bằng custom args_builder.
        """
        entities = state.get("entities", {})
        args: dict = {}

        # Map common entity fields sang tool args
        if "product_name" in entities:
            args["query"] = entities["product_name"]
            args["product_name"] = entities["product_name"]

        if "category" in entities:
            args["category"] = entities["category"]

        if "quantity" in entities:
            args["quantity"] = entities["quantity"]

        if "price_min" in entities:
            args["price_min"] = entities["price_min"]
        if "price_max" in entities:
            args["price_max"] = entities["price_max"]

        if "currency" in entities:
            args["currency_code"] = entities["currency"]

        # product_id từ state
        if state.get("current_product_id"):
            args["product_id"] = state["current_product_id"]

        # user_id cho cart tools
        user_id = state.get("user_id", "anonymous")
        if self.tool_name in ("add_to_cart_tool", "get_cart_tool", "check_cart_item_tool"):
            args["user_id"] = user_id

        return args

    def _should_return_directly(self, result: Any) -> bool:
        """Truthfulness guard: trả về True khi result chứa thông báo nghiệp vụ rõ ràng."""
        if result is None:
            return False

        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False)
            except (TypeError, ValueError):
                return False

        text = result.strip().lower()
        return any(pattern in text for pattern in _DIRECT_RETURN_PATTERNS)

    async def _retry_broader(self, args: dict) -> Any:
        """Fallback strategy cho search: tìm rộng hơn (bỏ bớt filter)."""
        broader_args = {"query": args.get("query", args.get("product_name", ""))}
        return await self.tool_fn.ainvoke(broader_args)

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()
        user_id = state.get("user_id", "anonymous")
        retry_count = state.get("retry_count", 0)
        call_id = f"{self.tool_name}:{retry_count}"

        # Build args từ state
        args = self._args_builder(state)
        cache_store = _get_cache_store()

        logger.info(
            "[TOOL_EXECUTOR] tool=%s | args=%s | session=%s",
            self.tool_name, str(args)[:200], state.get("session_id", "")
        )

        # ── 1. L4: Validate ──
        try:
            validation = validate_tool_call(self.tool_name, args, user_id)
            if not validation.is_valid:
                logger.warning(
                    "[TOOL_EXECUTOR] L4 BLOCK | tool=%s | reason=%s",
                    self.tool_name, validation.blocked_reason
                )
                return {
                    "tool_results": {call_id: {"error": validation.blocked_reason, "source": "L4_block"}},
                    "guardrail_violations": [{
                        "guardrail": "L4",
                        "type": validation.violation_type,
                        "detail": validation.blocked_reason,
                    }],
                    "node_durations": {f"ToolExecutor:{self.tool_name}": _ms(t0)},
                }
        except Exception as e:
            logger.error("[TOOL_EXECUTOR] Validation exception: %s", e)

        # ── 2. Cache check ──
        if self.tool_name not in WRITE_TOOLS:
            cached = cache_store.get(self.tool_name, args)
            if cached:
                logger.debug("[TOOL_EXECUTOR] Cache HIT | tool=%s", self.tool_name)
                return {
                    "tool_results": {call_id: {"result": cached, "source": "cache"}},
                    "node_durations": {f"ToolExecutor:{self.tool_name}": _ms(t0)},
                }

        # ── 3. Execute với retry ──
        result = None
        last_error = None
        for attempt in range(self.max_retries):
            try:
                result = await self.tool_fn.ainvoke(args)
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "[TOOL_EXECUTOR] Attempt %d/%d failed | tool=%s | err=%s",
                    attempt + 1, self.max_retries, self.tool_name, str(e)[:100]
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))

        if last_error is not None:
            # Tất cả retries đã thất bại
            if self.fallback_strategy == "retry_broader":
                try:
                    result = await self._retry_broader(args)
                    logger.info("[TOOL_EXECUTOR] Broader retry succeeded | tool=%s", self.tool_name)
                    last_error = None
                except Exception as e2:
                    last_error = e2

            if last_error is not None:
                err_msg = str(last_error)[:200]
                logger.error("[TOOL_EXECUTOR] All retries failed | tool=%s | err=%s", self.tool_name, err_msg)
                return {
                    "tool_results": {call_id: {"error": err_msg, "source": "exception"}},
                    "errors": [{"node": f"ToolExecutor:{self.tool_name}", "error": err_msg}],
                    "node_durations": {f"ToolExecutor:{self.tool_name}": _ms(t0)},
                }

        # ── 4. Truthfulness guard ──
        if self._should_return_directly(result):
            logger.debug("[TOOL_EXECUTOR] Truthfulness guard: preserve direct | tool=%s", self.tool_name)
            return {
                "tool_results": {call_id: {"result": result, "source": "grpc", "direct": True}},
                "final_answer": result,  # Preserve exact message
                "node_durations": {f"ToolExecutor:{self.tool_name}": _ms(t0)},
            }

        # ── 5. Cache set (read-only) ──
        if self.tool_name not in WRITE_TOOLS and result is not None:
            try:
                cache_store.set(self.tool_name, args, result if isinstance(result, str) else json.dumps(result))
            except Exception as e:
                logger.debug("[TOOL_EXECUTOR] Cache set error: %s", e)

        logger.info(
            "[TOOL_EXECUTOR] OK | tool=%s | result=%.100s | %dms",
            self.tool_name, str(result)[:100], _ms(t0)
        )

        return {
            "tool_results": {call_id: {"result": result, "source": "grpc"}},
            "node_durations": {f"ToolExecutor:{self.tool_name}": _ms(t0)},
        }


def _ms(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000
