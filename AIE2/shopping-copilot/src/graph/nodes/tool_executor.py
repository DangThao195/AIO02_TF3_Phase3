"""
graph/nodes/tool_executor.py — DAG Runner (Tool Executor Node)

Topological execution của DAG plan:
- Resolve variable references ($steps[id].*, $input.entities.*, $memory.*, $session.*)
- L3 validate mỗi tool call
- Cache check/set cho read tools
- Retry theo config
- Write tool → LangGraph interrupt() để chờ confirm
- Planner memory update sau mỗi node
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
_MAX_PARALLEL = 4


def _normalize_price_output(data: Any) -> Any:
    """Normalize price fields trong tool output."""
    if isinstance(data, dict):
        # units + nanos → price string
        if "price_units" in data and "price_nanos" in data:
            units = data.get("price_units", 0)
            nanos = data.get("price_nanos", 0)
            cents = nanos // 10_000_000
            data = dict(data)
            data["price"] = f"${units}.{cents:02d}"
            data.pop("price_units", None)
            data.pop("price_nanos", None)
        # picture → image
        if "picture" in data and "image" not in data:
            data = dict(data)
            data["image"] = data.pop("picture")
        # categories TEXT → array
        if "categories" in data and isinstance(data["categories"], str):
            data = dict(data)
            data["categories"] = [c.strip() for c in data["categories"].split(",") if c.strip()]
        return {k: _normalize_price_output(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_normalize_price_output(item) for item in data]
    return data


def _resolve_json_path(path: str, data: Any) -> Any:
    """Resolve JSON path như products[0].id → data['products'][0]['id']."""
    parts = path.split(".")
    current = data
    for part in parts:
        arr_match = re.match(r"(\w+)\[(\d+)\]", part)
        if arr_match:
            key, idx = arr_match.group(1), int(arr_match.group(2))
            current = (current or {}).get(key, [])
            current = current[idx] if isinstance(current, list) and len(current) > idx else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _safe_first(path_expr: str, default_expr: str, node_outputs: dict) -> str:
    """$first(path, default): lấy phần tử đầu tiên, fallback default."""
    m = re.match(r"steps\[(\w+)\]\.(.+)", path_expr)
    if m:
        node_id = m.group(1)
        json_path = m.group(2)
        data = node_outputs.get(node_id, {})
        result = _resolve_json_path(json_path, data)
        if isinstance(result, list) and result:
            return str(result[0])
    return _parse_default(default_expr)


def _safe_exists(path_expr: str, node_outputs: dict) -> bool:
    """$exists(path): check field tồn tại."""
    m = re.match(r"steps\[(\w+)\]\.(.+)", path_expr)
    if m:
        node_id = m.group(1)
        json_path = m.group(2)
        data = node_outputs.get(node_id, {})
        result = _resolve_json_path(json_path, data)
        return result is not None
    return False


def _safe_index(path_expr: str, index: int, default_expr: str, node_outputs: dict) -> str:
    """$safe_index(path, i, default): index an toàn, không IndexError."""
    m = re.match(r"steps\[(\w+)\]\.(.+)", path_expr)
    if m:
        node_id = m.group(1)
        json_path = m.group(2)
        data = node_outputs.get(node_id, {})
        arr = _resolve_json_path(json_path, data)
        if isinstance(arr, list) and 0 <= index < len(arr):
            return str(arr[index])
    return _parse_default(default_expr)


def _parse_default(expr: str) -> str:
    """Parse default value: null → '', number → str(number), string → string."""
    expr = expr.strip().strip("'\"")
    if expr.lower() in ("null", "none", ""):
        return ""
    return expr


def _evaluate_condition(result: dict, condition: dict) -> str:
    """Evaluate condition expression. Return: 'ask_user' | 'stop' | 'continue'."""
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


def _parse_condition_value(s: str):
    """Parse '0' → 0, 'ask_user' → 'ask_user'."""
    s = s.strip().strip("'\"")
    try:
        return int(s) if s.isdigit() else float(s.replace(",", ""))
    except ValueError:
        return s


def _build_cache_key(tool_name: str, args: dict) -> str | None:
    """Sinh cache key theo naming convention trong cache_design.md."""
    if tool_name == "search_products_v2":
        query = args.get("query", "")
        return f"search:{hashlib.sha256(query.lower().encode()).hexdigest()[:16]}"
    if tool_name == "get_product_details_tool":
        return f"product:{args.get('product_id', '')}"
    if tool_name == "convert_currency_tool":
        return f"currency:{args.get('from_currency', 'USD')}:{args.get('to_currency', 'VND')}"
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
    """Get TTL for tool cache in seconds."""
    if tool_name == "search_products_v2":
        return 600
    if tool_name in ("get_product_details_tool", "get_product_id"):
        return 1800
    if tool_name in ("convert_currency_tool", "get_shipping_quote_tool"):
        return 3600
    if tool_name == "get_recommendations_tool":
        return 900
    return 300


def _compute_dag_depth(nodes: list, edges: list) -> int:
    """Tính độ sâu lớn nhất của DAG (number of edges in longest path)."""
    depths: dict = {}
    adj: dict = {n["id"]: [] for n in nodes}
    for f, t in edges:
        adj[f].append(t)

    def dfs(nid: str) -> int:
        if nid in depths:
            return depths[nid]
        if not adj[nid]:
            depths[nid] = 0
            return 0
        depths[nid] = 1 + max(dfs(child) for child in adj[nid])
        return depths[nid]

    if not nodes:
        return 0
    return max(dfs(n["id"]) for n in nodes)


def _resolve_value(val: Any, node_outputs: dict, state: dict) -> Any:
    """Resolve variable references trong args."""
    if not isinstance(val, str):
        return val

    # $steps[id].path
    def resolve_step(m):
        node_id = m.group(1)
        path = m.group(2).strip(".")
        result = node_outputs.get(node_id, {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                return val
        for part in path.split("."):
            # Handle array index like products[0]
            arr_match = re.match(r"(\w+)\[(\d+)\]", part)
            if arr_match:
                key, idx = arr_match.group(1), int(arr_match.group(2))
                result = result.get(key, []) if isinstance(result, dict) else []
                result = result[idx] if isinstance(result, list) and len(result) > idx else {}
            elif isinstance(result, dict):
                result = result.get(part, "")
            else:
                result = ""
        return result

    val = re.sub(r'\$steps\[(\w+)\]([\.\w\[\]]+)', resolve_step, val)

    # $input.entities.*
    entities = state.get("entities") or {}
    val = re.sub(
        r'\$input\.entities\.(\w+)',
        lambda m: str(entities.get(m.group(1), "")),
        val,
    )

    # $input.query
    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""
    val = val.replace("$input.query", query)

    # $session.*
    val = re.sub(
        r'\$session\.(\w+)',
        lambda m: str(state.get(m.group(1), "")),
        val,
    )

    # $memory.*
    memory = state.get("planner_memory") or {}
    val = re.sub(
        r'\$memory\.(\w+)',
        lambda m: str(memory.get(m.group(1), "")),
        val,
    )

    # $first(path, default=None) — lấy phần tử đầu tiên
    val = re.sub(
        r'\$first\(([^,]+),\s*default=([^)]+)\)',
        lambda m: _safe_first(m.group(1).strip(), m.group(2).strip(), node_outputs),
        val,
    )

    # $exists(path) — kiểm tra field tồn tại
    val = re.sub(
        r'\$exists\(([^)]+)\)',
        lambda m: str(_safe_exists(m.group(1).strip(), node_outputs)),
        val,
    )

    # $safe_index(path, index, default=None) — index an toàn
    val = re.sub(
        r'\$safe_index\(([^,]+),\s*(\d+),\s*default=([^)]+)\)',
        lambda m: _safe_index(m.group(1).strip(), int(m.group(2)), m.group(3).strip(), node_outputs),
        val,
    )

    return val


def _resolve_args(args: dict, node_outputs: dict, state: dict) -> dict:
    """Resolve tất cả args của một node."""
    resolved = {}
    for k, v in args.items():
        resolved[k] = _resolve_value(v, node_outputs, state)
    # Inject user_id nếu tool cần
    if "user_id" not in resolved:
        resolved["user_id"] = state.get("user_id", "anonymous")
    return resolved


async def _execute_tool(tool_name: str, args: dict, timeout: float = 2.0) -> Any:
    """Execute một tool với timeout."""
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
    """Cập nhật planner_memory sau khi tool chạy xong."""
    memory = dict(memory) if memory else {}
    plan = state.get("plan") or {}
    memory["last_goal"] = plan.get("goal", "")

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            return memory

    if tool_name == "search_products_v2":
        products = result.get("products", [])
        if products:
            memory["last_product_id"] = products[0].get("id", "")
            memory["last_product_name"] = products[0].get("name", "")
            memory["last_results_ids"] = [p.get("id") for p in products[:5] if p.get("id")]
            mentioned = memory.get("mentioned_products", [])
            for p in products[:5]:
                pid = p.get("id")
                if pid and pid not in mentioned:
                    mentioned.append(pid)
            memory["mentioned_products"] = mentioned

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

    elif tool_name == "get_cart_tool":
        memory["current_cart_items"] = result.get("item_count", 0)

    return memory


async def tool_executor_node(state: dict) -> dict:
    """
    DAG Runner — thực thi tất cả nodes trong plan theo thứ tự topological.
    Output: {tool_results, errors, retry_count, pending_action, node_durations, planner_memory}
    """
    t0 = time.time()

    plan = state.get("plan") or {}
    nodes = plan.get("nodes", [])
    edges = plan.get("edges", [])

    # Nếu không có nodes (greeting, ask_user, v.v.)
    if not nodes:
        return {
            "tool_results": {},
            "errors": [],
            "retry_count": 0,
            "node_durations": {"tool_executor": int((time.time() - t0) * 1000)},
        }

    # Trim nếu vượt max
    if len(nodes) > _MAX_NODES:
        nodes = sorted(nodes, key=lambda n: n.get("confidence", 0), reverse=True)[:_MAX_NODES]

    # Phase 4.9: Enforce Max DAG Depth = 5
    depth = _compute_dag_depth(nodes, edges)
    if depth > 5:
        logger.warning("[tool_executor] DAG depth %d > 5 — flattening", depth)
        for n in nodes:
            n["depends_on"] = []

    user_id = state.get("user_id", "anonymous")
    planner_memory = dict(state.get("planner_memory") or {})
    tool_results: dict = {}
    errors: list = []
    retry_count = 0
    node_outputs: dict = {}
    done: set = set()
    node_map = {n["id"]: n for n in nodes}
    total_duration: dict = {}
    tool_had_pending: bool = False
    pending_action: dict | None = None

    # ── Topological execution ──
    max_iterations = len(nodes) + 2
    iteration = 0

    while len(done) < len(nodes) and iteration < max_iterations:
        iteration += 1

        # Find ready nodes
        ready = [
            n for n in nodes
            if n["id"] not in done
            and all(dep in done for dep in n.get("depends_on", []))
        ]

        if not ready:
            if len(done) < len(nodes):
                remaining = [n["id"] for n in nodes if n["id"] not in done]
                errors.append({"node": "tool_executor", "error": f"Deadlock: {remaining}"})
            break

        # Batch parallel (max 4)
        for batch_start in range(0, len(ready), _MAX_PARALLEL):
            batch = ready[batch_start:batch_start + _MAX_PARALLEL]

            async def execute_one(node: dict):
                nid = node["id"]
                tool_name = node.get("tool", "")
                raw_args = node.get("args", {})
                nt0 = time.time()

                # Resolve args
                args = _resolve_args(raw_args, node_outputs, state)
                # Ensure user_id for cart/review tools
                if tool_name in ("get_cart_tool", "check_cart_item_tool",
                                  "add_to_cart_tool", "update_cart_item_tool"):
                    args["user_id"] = user_id

                # L3 validate
                try:
                    from src.guardrails.tool_validator import validate_tool_call
                    validation = validate_tool_call(tool_name, args, user_id)
                    if not validation.is_valid:
                        return nid, None, validation.blocked_reason, None
                except Exception:
                    pass

                # Phase 4.2: Cache check for read tools
                from src.tools.registry import ToolRegistry
                spec = ToolRegistry.get_spec(tool_name)
                is_read = spec and not spec.is_write
                cache_key = None
                if is_read:
                    cache_key = _build_cache_key(tool_name, args)
                    if cache_key:
                        try:
                            from src.memory.cache_manager import CacheManager
                            cache_mgr = CacheManager()
                            cached = await cache_mgr.get(cache_key, "tool")
                            if cached is not None:
                                logger.debug("[cache] HIT tool=%s key=%s", tool_name, cache_key)
                                return nid, cached, None, None
                        except Exception:
                            pass

                # Determine timeout
                if tool_name == "search_products_v2":
                    timeout = 15.0
                elif tool_name == "get_shipping_quote_tool":
                    timeout = 3.0
                else:
                    timeout = 2.0

                # Retry config with exponential backoff
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
                    return nid, None, last_err or "Tool execution failed", None

                # Phase 4.2: Cache set for read tools (inside execute_one before returning)
                try:
                    if is_read and cache_key:
                        from src.memory.cache_manager import CacheManager
                        cache_mgr = CacheManager()
                        ttl = _get_cache_ttl(tool_name)
                        await cache_mgr.set(cache_key, result, "tool", ttl)
                except Exception:
                    pass

                return nid, result, None, None

            results = await asyncio.gather(*[execute_one(n) for n in batch],
                                           return_exceptions=True)

            for node, outcome in zip(batch, results):
                nid = node["id"]
                tool_name = node.get("tool", "")

                if isinstance(outcome, Exception):
                    errors.append({"node": nid, "error": str(outcome)})
                    done.add(nid)
                    continue

                nid_out, result, err, pending_info = outcome

                if err:
                    errors.append({"node": nid, "error": err})
                    done.add(nid)
                    continue

                # Parse result
                parsed = result
                if isinstance(result, str):
                    try:
                        parsed = json.loads(result)
                    except Exception:
                        parsed = {"raw": result}

                # Normalize
                parsed = _normalize_price_output(parsed)
                node_outputs[nid] = parsed

                # Phase 4.5: Conditional branching — evaluate node condition
                condition = node.get("condition")
                if condition:
                    data = parsed if isinstance(parsed, dict) else {}
                    branch = _evaluate_condition(data, condition)
                    if branch == "ask_user":
                        msg = data.get("message", "Vui lòng cung cấp thêm thông tin.")
                        pending = {"action": tool_name, "args": node.get("args", {}), "message": msg}
                        tool_results[tool_name] = parsed
                        # Set pending_action — interrupt will happen in confirmation_node
                        tool_had_pending = True
                        pending_action = pending
                        done.add(nid)
                        continue
                    elif branch == "stop":
                        done.add(nid)
                        continue

                # Write tool → check for pending
                if isinstance(parsed, dict) and parsed.get("status") == "pending":
                    token = parsed.get("token", "")
                    message = parsed.get("message", "")
                    pending = {
                        "action": tool_name,
                        "args": node.get("args", {}),
                        "token": token,
                        "message": message,
                    }
                    tool_results[tool_name] = parsed
                    # Set pending_action — no interrupt here, will be handled by confirmation_node
                    tool_had_pending = True
                    pending_action = pending
                    done.add(nid)
                    continue

                # Store result
                tool_results[tool_name] = parsed

                # Update planner memory
                planner_memory = _update_planner_memory(planner_memory, tool_name, parsed, state)

                done.add(nid)

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[tool_executor] done=%d/%d errors=%d pending=%s (%dms)",
                len(done), len(nodes), len(errors), bool(tool_had_pending), duration_ms)

    return {
        "tool_results": tool_results,
        "errors": errors,
        "retry_count": retry_count,
        "pending_action": pending_action,
        "planner_memory": planner_memory,
        "node_durations": {**total_duration, "tool_executor": duration_ms},
    }
