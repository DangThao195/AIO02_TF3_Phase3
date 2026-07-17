# Planner Design — 2-Layer Planner (Intent Parser + TGB)

> **Phase 1 — Core Architecture** | *Files: `graph/nodes/intent_parser.py`, `graph/nodes/task_graph_builder.py`*

## Layer 1: Intent Parser

**File:** `graph/nodes/intent_parser.py`

### Interface
```python
async def intent_parser_node(state: ShoppingState) -> dict:
    """
    Input:  state.messages[-1] (user query)
            state.planner_memory (ngữ cảnh)
    Output: {intent, entities, confidence, source, node_durations}
    """
```

### Thuật toán
1. Lấy query từ `state.messages[-1].content`
2. **Rule-based match** (zero-cost): chạy 9 regex pattern sets
3. **LLM fallback** (nếu `confidence < 0.8`): gọi LLM với prompt <100 tokens
4. Output: `{intent, entities, confidence, source}`

### Rule Patterns (9 intents)

| Intent | Pattern key | Score logic |
|---|---|---|
| `cart_view` | `xem\|giỏ\|cart\|co.*giỏ` | full match → 1.0, substring → 0.8 |
| `cart_add` | `thêm\|add\|cho.*vào\|bỏ.*vào` | |
| `search` | `tìm\|search\|kiếm\|find` | |
| `review` | `review\|đánh giá\|nhận xét\|sao` | |
| `recommend` | `gợi ý\|recommend\|suggest\|tương tự` | |
| `currency` | `VND\|JPY\|EUR\|đổi.*tiền\|convert` | |
| `shipping` | `ship\|vận chuyển\|giao.*hàng\|phí.*ship` | |
| `checkout` | `thanh toán\|checkout\|mua\|đặt.*hàng\|order` | |
| `greeting` | `^(hi\|hello\|chào\|hey\|ok)` | → intent `agent` |

### Entity Extraction (rule-based)
| Entity | Pattern | Field |
|---|---|---|
| quantity | `(\d+)\s*(cái\|chiếc\|tents?\|items?)` | `entities.quantity` |
| max_price | `dưới\|under\|< \$?(\d+)` | `entities.max_price` |
| min_price | `trên\|over\|> \$?(\d+)` | `entities.min_price` |

### LLM Fallback Prompt
```
Xác định intent và entities từ câu hỏi mua sắm.
Intents: search, review, recommend, cart_add, cart_view, shipping, currency, checkout, greeting, unknown
Trả JSON: {"intent": "...", "entities": {"product_name": "...", ...}, "confidence": 0.0-1.0}
Query: {query}
```
- `temperature=0.0`, `max_tokens=100`, `response_format=json_object`

### Error Handling
| Case | Behavior |
|---|---|
| Rule không match intent nào | → LLM fallback |
| LLM cũng fail/timeout | → `intent="unknown"`, `confidence=0.0` |
| Entity extraction rỗng | → `entities={}`, executor resolve runtime |

---

## Layer 2: Task Graph Builder

**File:** `graph/nodes/task_graph_builder.py`

### Interface
```python
async def task_graph_builder_node(state: ShoppingState) -> dict:
    """
    Input:  state.intent, state.entities, state.planner_memory
            ToolRegistry (all schemas)
    Output: {plan, plan_step_index, current_goal,
             planner_reasoning, plan_confidence, node_durations}
    """
```

### DAGPlan Schema
```python
class DAGNode(TypedDict):
    id: str                    # "node_0", "node_1"
    tool: str                  # ToolRegistry name
    description: str           # Why this tool
    depends_on: list[str]      # Node IDs phải chạy trước
    condition: Optional[dict]  # {"on":"total","==0":"ask_user"}
    confidence: float          # 0.0–1.0

class DAGPlan(TypedDict):
    nodes: list[DAGNode]
    edges: list[tuple[str, str]]  # (from, to)
```

### Prompt Building
```python
TGB_PROMPT.format(
    tool_schemas_text=ToolRegistry.get_all_schemas_text(),
    user_query=query,
    intent=intent,
    entities=json.dumps(entities),
    planner_memory=format_memory(planner_memory),
)
```
- `temperature=0.2`, `response_format=json_object`, timeout=3s

### Validation Rules
| Check | Fail → |
|---|---|
| Tool name không trong ToolRegistry | Ghi error, bỏ node đó |
| `depends_on` ID không tồn tại | Ghi error, sửa thành `[]` |
| Self-reference loop | Ghi error, bỏ node |
| Empty nodes + confidence > 0 | Force `confidence=0` |
| > 8 nodes | Trim node confidence thấp nhất |

### Planner Memory Context
```python
def format_memory(memory: dict) -> str:
    if not memory or all(v is None for v in memory.values()):
        return "(không có dữ liệu phiên trước)"
    parts = []
    if memory.get("last_search"):
        parts.append(f"Lần trước bạn tìm: {memory['last_search']}")
    if memory.get("last_product_id"):
        parts.append(f"Product ID vừa xem: {memory['last_product_id']}")
    if memory.get("current_cart_items", 0) > 0:
        parts.append(f"Giỏ hàng có {memory['current_cart_items']} món")
    return "; ".join(parts)
```

### Confidence Scoring
- `overall_confidence = average(nodes[i].confidence)`
- `plan_confidence < 0.3` → route sang `ask_user` (không execute)

### Error Handling
| Case | Behavior |
|---|---|
| LLM trả JSON không parse được | Retry 1 lần; fail → plan rỗng |
| DAG validation lỗi > 50% nodes | Plan rỗng, `plan_confidence=0` |
| Timeout (>3s) | Plan rỗng, fallback template response |
| Tool denied (order, charge, etc.) | Plan rỗng, trả lời thẳng |
