# State Design — ShoppingState v3.2

> **Phase 1 — Core Architecture** | *File: `graph/state.py`*

## ShoppingState (`TypedDict`, `total=False`)

### Core message history
```
messages: Annotated[list[BaseMessage], add_messages]
```

### Planner (§7)
| Field | Type | Reducer | Note |
|---|---|---|---|
| `plan` | `dict` | — | DAGPlan `{nodes, edges}` |
| `plan_step_index` | `int` | — | Resume position |
| `current_goal` | `str` | — | Intent hiện tại |
| `planner_reasoning` | `str` | — | TGB reasoning log |
| `plan_confidence` | `float` | — | 0.0–1.0 |

### Entities
| Field | Type | Note |
|---|---|---|
| `intent` | `str` | `search\|review\|cart\|shipping\|currency\|agent\|unknown` |
| `entities` | `dict` | Raw entities từ Intent Parser |
| `resolved_entities` | `dict` | Resolved (product_id thực tế) |

### Tool results
| Field | Type | Reducer | Note |
|---|---|---|---|
| `tool_results` | `dict` | `merge_tool_results` | `{node_id: normalized_result}` |
| `tool_history` | `list` | `accumulate_tool_history` | Cross-turn history |

### Dependency graph
```
dependency_graph: dict   # {node_id: [dep_node_ids]} runtime tracking
```

### Response Verifier / Hallucination Guard
```
complexity_score: float          # 0.0–1.0
final_answer: str
groundedness_score: float
hallucination_detected: bool     # True → fallback route
fallback_used: bool
```

### Gate Layer (Nova Lite)
```
gate_decisions: dict                     # {gate_name: {decision, reason}}
semantic_hallucination_detected: bool    # True → replan
replan_count: int                        # ≤ 1 per request
```

### Reflection
```
reflection_result: str       # "pass" | "replan"
reflection_issues: list      # [{type, node, detail}]
```

### Confidence / Retry
```
confidence: float       # 0.0–1.0 overall
retry_count: int
```

### Planner Memory (ngắn hạn)
```
planner_memory: dict = {
    "last_search": str,
    "last_product_id": str,
    "current_cart_items": int,
    "last_intent": str,
}
```

### Session
```
session_id: str
user_id: str
trace_id: str
```

### Confirmation
```
pending_action: Optional[dict]   # {token, action, params}
confirmed: bool                  # resume signal
```

### Guardrail / Error / Telemetry
```
guardrail_violations: list
errors: Annotated[dict, accumulate_errors]
node_durations: Annotated[dict, merge_node_durations]
```

## Reducers

| Reducer | Logic |
|---|---|
| `merge_tool_results` | `existing.copy()` → chỉ nhận key chưa tồn tại |
| `accumulate_errors` | `existing + updates` |
| `accumulate_tool_history` | `existing + updates` (giới hạn 6 turns) |
| `merge_node_durations` | `result[node] = existing.get(node, 0) + ms` |

## State Flow qua Graph

```
START → input_guard → intent_parser → task_graph_builder → [plan_validity_gate]
         → tool_executor → reflection → [pass] → response_verifier
                                       → [replan] → task_graph_builder (partial)
         → hallucination_guard → [pass] → answer_generator → END
                               → [fail] → fallback_generator → answer_generator → END
```

## Migration từ v2 → v3.2

| Remove | Add |
|---|---|
| `pending_workflows` | `plan` (DAGPlan) |
| `current_workflow_index` | `plan_step_index` |
| `workflow_results` | `plan_confidence`, `planner_reasoning` |
| `current_product_id` | `resolved_entities` |
| `resolved_product_name` | `dependency_graph` |
| `candidate_products` | `groundedness_score`, `hallucination_detected` |
| | `gate_decisions`, `semantic_hallucination_detected` |
| | `reflection_result`, `reflection_issues` |
| | `planner_memory`, `tool_history` |
| | `confidence` |
