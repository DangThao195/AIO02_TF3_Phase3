"""
graph/nodes/tool_executor.py — Sequential Tool Executor with Entity Extractor

Thuật toán:
1. Duyệt plan (flat list) theo thứ tự
2. Với mỗi tool:
   a. Entity Extractor (LLM) → trích xuất params từ query + context
   b. L3 validate
   c. Cache check/set cho read tools
   d. Execute với retry + timeout
   e. Update planner_memory + reference tables
   f. Feed kết quả vào context cho tool kế tiếp
3. Write tool → pending_action → confirmation node
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any


logger = logging.getLogger("graph.tool_executor")

_MAX_NODES = 8


def _normalize_price_output(data: Any) -> Any:
    """Normalize price fields trong tool output."""
    if isinstance(data, dict):
        if "price_units" in data and "price_nanos" in data:
            units = data.get("price_units", 0)
            nanos = data.get("price_nanos", 0)
            cents = nanos // 10_000_000
            data = dict(data)
            data["price"] = f"${units}.{cents:02d}"
            data.pop("price_units", None)
            data.pop("price_nanos", None)
        if "picture" in data and "image" not in data:
            data = dict(data)
            data["image"] = data.pop("picture")
        if "categories" in data and isinstance(data["categories"], str):
            data = dict(data)
            data["categories"] = [c.strip() for c in data["categories"].split(",") if c.strip()]
        return {k: _normalize_price_output(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_normalize_price_output(item) for item in data]
    return data


def _build_cache_key(tool_name: str, args: dict) -> str | None:
    filter_tools = {"category_filter", "price_filter", "semantic_filter", "multi_filter"}
    if tool_name in filter_tools:
        query = args.get("query") or args.get("name") or str(args)
        return f"{tool_name}:{hashlib.sha256(query.lower().encode()).hexdigest()[:16]}"
    if tool_name == "get_product_details_tool":
        return f"product:{args.get('product_id', '')}"
    if tool_name == "convert_currency_tool":
        amount = str(args.get("amount", args.get("amount_units", "0")))
        return f"currency:{args.get('from_currency', 'USD')}:{args.get('to_currency', 'VND')}:{amount}"
    if tool_name == "get_shipping_quote_tool":
        zip_code = str(args.get("zip_code", ""))
        total = str(args.get("cart_total", "0"))
        raw = zip_code + total
        return f"shipping:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
    if tool_name == "get_recommendations_tool":
        pid = str(args.get("product_id", "all"))
        limit = args.get("limit", 5)
        return f"recommend:{pid}:{limit}"
    if tool_name in ("get_cart_tool", "get_categories", "get_all_products", "get_product_id"):
        return f"{tool_name}:{hashlib.sha256(str(sorted(args.items())).encode()).hexdigest()[:16]}"
    return None


def _get_cache_ttl(tool_name: str) -> int:
    filter_tools = {"category_filter", "price_filter", "semantic_filter", "multi_filter"}
    if tool_name in filter_tools:
        return 600
    if tool_name in ("get_product_details_tool", "get_product_id"):
        return 1800
    if tool_name in ("convert_currency_tool", "get_shipping_quote_tool"):
        return 3600
    if tool_name == "get_recommendations_tool":
        return 900
    return 300


def _parse_condition_value(s: str):
    s = s.strip().strip("'\"")
    try:
        return int(s) if s.isdigit() else float(s.replace(",", ""))
    except ValueError:
        return s


def _evaluate_condition(result: dict, condition: dict) -> str:
    if not condition:
        return "continue"
    on_field = condition.get("on", "")
    value = result.get(on_field)
    for key, action in condition.items():
        if key == "on":
            continue
        if key.startswith("=="):
            threshold = _parse_condition_value(key[2:])
            if value == threshold:
                return action
        elif key.startswith(">"):
            threshold = _parse_condition_value(key[1:])
            if value is not None and float(value) > float(threshold):
                return action
        elif key.startswith("<"):
            threshold = _parse_condition_value(key[1:])
            if value is not None and float(value) < float(threshold):
                return action
        elif key == "default":
            return action
    return "continue"


async def _execute_tool(tool_name: str, args: dict, timeout: float = 2.0) -> Any:
    from src.tools.registry import ToolRegistry
    fn = ToolRegistry.get_fn(tool_name)
    if fn is None:
        raise ValueError(f"Tool '{tool_name}' not found in registry")

    async def _run():
        if hasattr(fn, "ainvoke"):
            return await fn.ainvoke(args)
        coro = getattr(fn, "coroutine", None)
        if coro is not None:
            return await coro(**args)
        func = fn.func if hasattr(fn, "func") else fn
        if asyncio.iscoroutinefunction(func):
            return await func(**args)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(**args))

    return await asyncio.wait_for(_run(), timeout=timeout)


def _update_planner_memory(memory: dict, tool_name: str, result: Any, state: dict) -> dict:
    memory = dict(memory) if memory else {}
    plan = state.get("plan") or {}
    memory["last_goal"] = plan.get("goal", "")

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            return memory

    if tool_name in ("category_filter", "price_filter", "semantic_filter", "multi_filter"):
        products = result.get("products", [])
        if products:
            pid = products[0].get("id", "")
            pname = products[0].get("name", "")
            memory["last_searched_product_id"] = pid
            memory["last_searched_product_name"] = pname
            memory["last_product_id"] = pid
            memory["last_product_name"] = pname
            memory["last_results_ids"] = [p.get("id") for p in products[:5] if p.get("id")]
            mentioned = memory.get("mentioned_products", [])
            for p in products[:5]:
                pid = p.get("id")
                if pid and pid not in mentioned:
                    mentioned.append(pid)
            memory["mentioned_products"] = mentioned[-50:]

        messages = state.get("messages", [])
        if messages:
            q = messages[-1].content if hasattr(messages[-1], "content") else ""
            memory["last_search"] = q

    elif tool_name in ("get_product_details_tool", "get_product_reviews_tool", "get_recommendations_tool"):
        product = result.get("product", {})
        pid = product.get("id") or result.get("product_id", "")
        if pid:
            memory["last_product_id"] = pid
            memory["last_product_name"] = product.get("name", "")

    elif tool_name == "add_to_cart_tool":
        pid = result.get("product_id", "")
        if pid:
            memory["last_product_id"] = pid
            memory["last_product_name"] = result.get("product_name", "")

    elif tool_name == "get_cart_tool":
        if result.get("status") == "success":
            memory["current_cart_items"] = result.get("item_count", 0)
        else:
            logger.warning("[_update_planner_memory] get_cart_tool returned error, preserving current_cart_items=%s",
                           memory.get("current_cart_items"))

    return memory


def _extract_items_from_result(tool_name: str, result: dict) -> list[dict]:
    items = []
    if tool_name in ("category_filter", "price_filter", "semantic_filter", "multi_filter"):
        for p in result.get("products", []):
            items.append({"index": len(items) + 1, "id": p.get("id", ""), "name": p.get("name", "")})
    elif tool_name == "get_product_details_tool":
        p = result.get("product", result)
        if p.get("id"):
            items.append({"index": 1, "id": p.get("id", ""), "name": p.get("name", "")})
    elif tool_name == "get_all_products":
        for p in result.get("products", []):
            items.append({"index": len(items) + 1, "id": p.get("id", ""), "name": p.get("name", "")})
    elif tool_name == "get_recommendations_tool":
        for rec in result.get("recommendations", []):
            items.append({"index": len(items) + 1, "id": rec.get("id", ""), "name": rec.get("name", "")})
    elif tool_name == "get_cart_tool":
        for item in result.get("items", []):
            items.append({"index": len(items) + 1, "id": item.get("product_id", ""), "name": item.get("name", "")})
    elif tool_name in ("get_product_reviews_tool",):
        p_name = result.get("product_name", result.get("product", {})).get("name", "")
        if result.get("product_id"):
            items.append({"index": 1, "id": result.get("product_id", ""), "name": p_name})
    return items


def _build_reference_table(items: list[dict]) -> dict:
    table: dict = {}
    ordinal_map = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
    n = len(items)
    for i, item in enumerate(items):
        pos = i + 1
        if pos in ordinal_map:
            table[ordinal_map[pos]] = item
        table[str(pos)] = item
        if pos == n:
            table["last"] = item
    return table


def _update_references(state_refs: dict, tool_name: str, result: dict) -> dict:
    items = _extract_items_from_result(tool_name, result)
    if not items:
        return state_refs or {}

    refs = dict(state_refs) if state_refs else {}
    now = time.time()

    last_outputs = list(refs.get("last_tool_outputs") or [])
    last_outputs.append({
        "type": _tool_output_type(tool_name),
        "items": items,
        "tool_name": tool_name,
        "timestamp": now,
    })
    refs["last_tool_outputs"] = last_outputs[-5:]

    new_table = _build_reference_table(items)
    existing_table = dict(refs.get("reference_table") or {})
    for k, v in new_table.items():
        existing_table[k] = v
    refs["reference_table"] = existing_table

    registry = dict(refs.get("entity_registry") or {})
    for item in items:
        name = (item.get("name") or "").strip().lower()
        if name and len(name) > 2:
            registry[name] = {"id": item.get("id", ""), "type": _entity_type(tool_name), "source_tool": tool_name}
    refs["entity_registry"] = registry

    stack = list(refs.get("reference_stack") or [])
    stack.append({
        "type": _tool_output_type(tool_name),
        "items": items,
        "tool_name": tool_name,
        "timestamp": now,
    })
    refs["reference_stack"] = stack[-5:]

    table = refs.get("reference_table", {})
    if len(table) > 20:
        digit_keys = [k for k in table if isinstance(k, str) and k.isdigit()]
        for k in sorted(digit_keys)[:-10]:
            table.pop(k, None)

    registry = refs.get("entity_registry", {})
    if len(registry) > 50:
        keys = list(registry.keys())
        for k in keys[:-50]:
            registry.pop(k, None)

    return refs


def _tool_output_type(tool_name: str) -> str:
    if tool_name in ("category_filter", "price_filter", "semantic_filter", "multi_filter"):
        return "product_list"
    if tool_name == "get_product_details_tool":
        return "product_detail"
    if tool_name == "get_product_reviews_tool":
        return "review_list"
    if tool_name == "get_recommendations_tool":
        return "recommendation_list"
    if tool_name == "get_cart_tool":
        return "cart"
    if tool_name == "get_all_products":
        return "product_list"
    return "generic"


def _entity_type(tool_name: str) -> str:
    if tool_name in ("category_filter", "price_filter", "semantic_filter", "multi_filter", "get_product_details_tool", "get_all_products"):
        return "product"
    if tool_name in ("get_recommendations_tool",):
        return "recommendation"
    if tool_name == "get_cart_tool":
        return "cart_item"
    return "generic"


async def _extract_tool_params(
    query: str,
    tool_name: str,
    previous_results: dict,
    planner_memory: dict,
) -> dict:
    """
    Entity Extractor — gọi LLM để trích xuất params cho tool từ query + context.
    Fast path: tool không cần params → trả về {}.
    """
    from src.tools.registry import ToolRegistry

    spec = ToolRegistry.get_spec(tool_name)
    if not spec:
        return {}

    input_schema = spec.input_schema or {}
    props = input_schema.get("properties", {})

    # Fast path: tool không cần tham số
    if not props:
        return {}

    from src.llm.llm import get_llm_client
    from src.llm.prompt import TOOL_PARAM_EXTRACTOR_PROMPT

    llm = get_llm_client()

    previous_text = ""
    if previous_results:
        lines = []
        for name, res in previous_results.items():
            if isinstance(res, dict):
                preview = {k: v for k, v in list(res.items())[:4]}
                lines.append(f"[{name}]: {json.dumps(preview, ensure_ascii=False)[:200]}")
            else:
                lines.append(f"[{name}]: {str(res)[:200]}")
        previous_text = "\n".join(lines)

    mem_text = json.dumps(planner_memory, ensure_ascii=False)[:300] if planner_memory else "(không có)"

    prompt = TOOL_PARAM_EXTRACTOR_PROMPT.format(
        user_query=query,
        tool_name=tool_name,
        tool_description=spec.description[:120],
        tool_input_schema=json.dumps(input_schema, ensure_ascii=False),
        previous_results=previous_text or "(chưa có tool nào chạy)",
        planner_memory=mem_text,
    )

    try:
        resp = llm.invoke(prompt, temperature=0.1, max_tokens=400)
        text = resp.content if hasattr(resp, "content") else str(resp)
        text = text.strip()
        m = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        params = json.loads(text) if text else {}
        if not isinstance(params, dict):
            params = {}
        return params
    except Exception as e:
        logger.warning("[entity_extractor] LLM extract failed for %s: %s", tool_name, e)
        return {}


async def tool_executor_node(state: dict) -> dict:
    """
    Sequential Tool Executor — duyệt plan theo thứ tự, entity_extract → execute → feed-forward.
    Output: {tool_results, errors, retry_count, pending_action, node_durations, planner_memory}
    """
    t0 = time.time()

    plan = state.get("plan") or {}
    nodes = plan.get("nodes", [])

    if not nodes:
        return {
            "tool_results": {},
            "errors": [],
            "retry_count": 0,
            "last_tool_outputs": [],
            "reference_table": {},
            "reference_stack": [],
            "entity_registry": {},
            "node_durations": {"tool_executor": int((time.time() - t0) * 1000)},
        }

    if len(nodes) > _MAX_NODES:
        nodes = sorted(nodes, key=lambda n: n.get("confidence", 0), reverse=True)[:_MAX_NODES]

    user_id = state.get("user_id", "anonymous")
    planner_memory = dict(state.get("planner_memory") or {})
    reference_refs = {
        "last_tool_outputs": list(state.get("last_tool_outputs") or []),
        "reference_table": dict(state.get("reference_table") or {}),
        "reference_stack": list(state.get("reference_stack") or []),
        "entity_registry": dict(state.get("entity_registry") or {}),
    }
    tool_results: dict = {}
    errors: list = []
    retry_count = 0
    node_outputs: dict = {}
    previous_results: dict = {}
    total_duration: dict = {}
    tool_had_pending: bool = False
    pending_action: dict | None = None

    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""

    # ── Sequential execution ──
    for node in nodes:
        nid = node["id"]
        tool_name = node.get("tool", "")
        if not tool_name:
            continue

        nt0 = time.time()

        # 1. Entity Extractor → params
        args = await _extract_tool_params(
            query=query,
            tool_name=tool_name,
            previous_results=previous_results,
            planner_memory=planner_memory,
        )

        if tool_name in ("get_cart_tool", "check_cart_item_tool",
                          "add_to_cart_tool", "update_cart_item_tool"):
            args["user_id"] = user_id

        resolved_entities = state.get("resolved_entities") or {}
        if resolved_entities.get("product_id"):
            if tool_name in ("get_product_details_tool", "get_product_reviews_tool",
                              "add_to_cart_tool", "update_cart_item_tool",
                              "check_cart_item_tool", "get_recommendations_tool"):
                if not args.get("product_id"):
                    args["product_id"] = resolved_entities["product_id"]

        # 2. L3 validate
        try:
            from src.guardrails.tool_validator import validate_tool_call
            validation = validate_tool_call(tool_name, args, user_id)
            if not validation.is_valid:
                errors.append({"node": nid, "error": validation.blocked_reason})
                tool_results[tool_name] = {"status": "error", "message": validation.blocked_reason}
                node_outputs[nid] = {"status": "error", "message": validation.blocked_reason}
                continue
        except Exception:
            pass

        # 3. Cache check cho read tools
        from src.tools.registry import ToolRegistry
        spec = ToolRegistry.get_spec(tool_name)
        is_read = spec and not spec.is_write
        cache_key = None
        cached_result = None
        if is_read:
            cache_key = _build_cache_key(tool_name, args)
            if cache_key:
                try:
                    from src.memory.cache_manager import CacheManager
                    cache_mgr = CacheManager()
                    cached_result = await cache_mgr.get(cache_key, "tool")
                except Exception:
                    pass

        if cached_result is not None:
            logger.debug("[cache] HIT tool=%s key=%s", tool_name, cache_key)
            result = cached_result
        else:
            # 4. Execute with retry
            if tool_name in ("category_filter", "price_filter", "semantic_filter", "multi_filter"):
                timeout = 15.0
            elif tool_name == "get_shipping_quote_tool":
                timeout = 3.0
            else:
                timeout = 2.0

            retry_cfg = ToolRegistry.get_retry_config(tool_name)
            max_retries = retry_cfg.get("max_retries", 1)
            backoff = retry_cfg.get("backoff")
            if not backoff or len(backoff) < max_retries + 1:
                backoff = [0.5 * (2 ** i) for i in range(max_retries + 1)]

            result = None
            last_err = None
            for attempt in range(max_retries + 1):
                try:
                    result = await _execute_tool(tool_name, args, timeout=timeout)
                    break
                except Exception as e:
                    last_err = str(e)
                    if attempt < max_retries:
                        wait = backoff[min(attempt, len(backoff) - 1)]
                        await asyncio.sleep(wait)

            nd_ms = int((time.time() - nt0) * 1000)
            total_duration[f"tool_executor:{tool_name}"] = nd_ms

            if result is None:
                errors.append({"node": nid, "error": last_err or "Tool execution failed"})
                tool_results[tool_name] = {"status": "error", "message": last_err or "Tool execution failed"}
                node_outputs[nid] = {"status": "error", "message": last_err or "Tool execution failed"}
                continue

            # 5. Cache set cho read tools (only cache success)
            try:
                if is_read and cache_key:
                    parsed_check = result
                    if isinstance(result, str):
                        try:
                            parsed_check = json.loads(result)
                        except Exception:
                            pass
                    is_error = isinstance(parsed_check, dict) and parsed_check.get("status") == "error"
                    if not is_error:
                        from src.memory.cache_manager import CacheManager
                        cache_mgr = CacheManager()
                        ttl = _get_cache_ttl(tool_name)
                        await cache_mgr.set(cache_key, result, "tool", ttl)
            except Exception:
                pass

        # 6. Parse & normalize
        parsed = result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except Exception:
                parsed = {"raw": result}

        parsed = _normalize_price_output(parsed)
        node_outputs[nid] = parsed
        previous_results[tool_name] = parsed

        # 7. Conditional branching
        condition = node.get("condition")
        if condition:
            data = parsed if isinstance(parsed, dict) else {}
            branch = _evaluate_condition(data, condition)
            if branch == "ask_user":
                msg = data.get("message", "Vui lòng cung cấp thêm thông tin.")
                pending = {"action": tool_name, "args": args, "message": msg}
                tool_results[tool_name] = parsed
                tool_had_pending = True
                pending_action = pending
                continue
            elif branch == "stop":
                continue

        # 8. Write tool → pending
        if isinstance(parsed, dict) and parsed.get("status") == "pending":
            token = parsed.get("token", "")
            message = parsed.get("message", "")
            pending = {
                "action": tool_name,
                "args": args,
                "token": token,
                "message": message,
            }
            tool_results[tool_name] = parsed
            tool_had_pending = True
            pending_action = pending
            continue

        # 9. Store result
        tool_results[tool_name] = parsed

        # 10. Update planner memory
        planner_memory = _update_planner_memory(planner_memory, tool_name, parsed, state)

        # 11. Update reference resolution fields
        if isinstance(parsed, dict):
            reference_refs = _update_references(reference_refs, tool_name, parsed)

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[tool_executor] done=%d/%d errors=%d pending=%s (%dms)",
                len(tool_results), len(nodes), len(errors), bool(tool_had_pending), duration_ms)

    return {
        "tool_results": tool_results,
        "errors": errors,
        "retry_count": retry_count,
        "pending_action": pending_action,
        "planner_memory": planner_memory,
        "last_tool_outputs": reference_refs.get("last_tool_outputs", []),
        "reference_table": reference_refs.get("reference_table", {}),
        "reference_stack": reference_refs.get("reference_stack", []),
        "entity_registry": reference_refs.get("entity_registry", {}),
        "node_durations": {**total_duration, "tool_executor": duration_ms},
    }
