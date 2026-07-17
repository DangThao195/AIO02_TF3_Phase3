# Executor Design — DAG Runner + Reflection

> **Phase 1 — Core Architecture** | *Files: `graph/nodes/tool_executor.py`, `graph/nodes/reflection.py`*

## DAG Runner

**File:** `graph/nodes/tool_executor.py`

### Interface
```python
async def tool_executor_node(state: ShoppingState) -> dict:
    """
    Input:  state.plan (DAGPlan), state.tool_results,
            state.session_id, state.user_id
    Output: {tool_results, errors, retry_count,
             pending_action, node_durations}
    """
```

### Execution Algorithm
```
node_map = index by node.id
done = set()
node_outputs = {}

while len(done) < len(plan.nodes):
    ready = [n for n in plan.nodes
             if n.id not in done
             and all(dep in done for dep in n.depends_on)]

    if not ready and len(done) < len(plan.nodes):
        raise DeadlockError("DAG deadlock detected")

    results = await asyncio.gather(
        *[execute_node(n, node_outputs, state) for n in ready],
        return_exceptions=True
    )

    for node, result in zip(ready, results):
        if isinstance(result, Exception):
            errors[node.id] = str(result)
            continue
        if node.condition:
            branch = evaluate_condition(result, node.condition)
            if branch == "ask_user":
                state.pending_action = {"type": "ask_user", ...}
                break  # pause DAG
            elif branch == "stop":
                break
        done.add(node.id)
        node_outputs[node.id] = result
```

### `execute_node` Steps
1. **Resolve variable references** — thay `$steps[x].path`, `$session.*`, `$input.entities.*`, `$memory.*`, `$first(...)`, `$exists(...)`, `$safe_index(...)`
2. **L3 Validate** — `validate_tool_call(tool_name, resolved_args, user_id)`
3. **Cache check** — read tool + cache hit → return cached
4. **Execute with retry** — gọi `ToolRegistry.get_fn(tool).ainvoke(args)`
5. **Normalize output** — price units/nanos → string
6. **Cache set** — if read tool
7. **Return** `(normalized_dict, source)`

### Variable Reference Resolver
| Syntax | Resolve | Fail → |
|---|---|---|
| `$steps[N].path` | `node_outputs[N]` → JSON path | node fail |
| `$session.field` | `state.get(field)` | node fail |
| `$input.entities.field` | `state.entities.get(field)` | node fail |
| `$memory.field` | `state.planner_memory.get(field)` | node fail |
| `$first(path, default)` | `path[0]` nếu list, else default | default |
| `$exists(path)` | Boolean: path tồn tại | False |
| `$safe_index(path, i, default)` | `path[i]` nếu i hợp lệ | default |

Default parsing: `null`/`None` → `None`; `true`/`false` → bool; số → int/float.

### Conditional Branching
```json
{"on": "total", "==0": "ask_user", ">1": "ask_choose", "default": "continue"}
```
Actions: `ask_user` → pause graph; `stop` → dừng DAG; `continue` → chạy tiếp.

### Retry Config
| Tool type | Retries | Backoff |
|---|---|---|
| Read (search, product, review, currency, shipping, cart, recommend) | 2 | 0.5s, 1s |
| Write (add_to_cart) | 1 | 0.5s |
| Checkout | 0 | — |

### Resource Limits (enforced)
| Limit | Value | Action |
|---|---|---|
| Max tool calls | 8 nodes | Trim plan trước execute |
| Max DAG depth | 5 levels | Flatten nếu vượt |
| Max parallel nodes | 4 | Batch `asyncio.gather` |
| Tool timeout | 2s (shipping: 3s) | Retry → error |
| LLM timeout | TGB: 3s, Verifier: 4s, Gate: 2s | Fallback |

---

## Reflection Node

**File:** `graph/nodes/reflection.py`

### Interface
```python
async def reflection_node(state: ShoppingState) -> dict:
    """
    Input:  state.tool_results, state.errors, state.plan_confidence,
            state.semantic_hallucination_detected, state.replan_count
    Output: {reflection_result, replan_count, reflection_issues,
             node_durations}
    """
```

### Trigger Checks (sequential, first match wins)

| # | Check | Condition | Issue |
|---|---|---|---|
| 1 | Zero result | Any tool returns `total=0` / empty list | `zero_result` |
| 2 | Tool errors | ≥2 errors in same DAG run | `tool_errors` |
| 3 | Low confidence | `plan_confidence < 0.5` | `low_confidence` |
| 4 | Semantic gate | `semantic_hallucination_detected == True` | `semantic_gate_fail` |

### Decision
```
if replan_count >= 2:
    reflection_result = "pass"     # force pass — giới hạn replan
elif any_issue_detected:
    reflection_result = "replan"
    replan_count += 1
else:
    reflection_result = "pass"
```

### Partial Replan Protocol
Khi `reflection_result = "replan"`, graph route ngược về `task_graph_builder`:
1. TGB nhận `state.reflection_issues` + `state.tool_results`
2. TGB chỉ sinh node thay thế cho node lỗi (giữ nguyên node OK)
3. Executor chỉ chạy node mới, không replay node OK

```
Graph: tool_executor → reflection
                         ├── pass → response_verifier
                         └── replan → task_graph_builder (partial)
                                         └── tool_executor (only new nodes)
```

### Skip Conditions
| Condition | Behavior |
|---|---|
| `replan_count >= 2` | Force pass |
| Không có tool_results | Auto pass |
| Guardrail violation trước đó | Auto pass (giữ nguyên guardrail message) |
| `pending_action` tồn tại | Auto pass (chờ confirm) |
