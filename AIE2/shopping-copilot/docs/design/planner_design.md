# Planner Design — 2-Layer Planner (Intent Parser + TGB)

> **Phase 1 — Core Architecture** | *Files: `graph/nodes/intent_parser.py`, `graph/nodes/task_graph_builder.py`*
>
> **Cập nhật v3.3:** Intent parser chuyển từ regex-first sang **LLM-first**. Routing gate không còn bypass intent parser.
> Xem `docs/design/prompt_design.md` §3 cho system prompt đầy đủ.

## Layer 1: Intent Parser

**File:** `graph/nodes/intent_parser.py`

### Interface
```python
async def intent_parser_node(state: dict) -> dict:
    """
    Input:  state.messages[-1] (user query)
            state.planner_memory (ngữ cảnh cross-turn)
            ToolRegistry (tool schemas cho context)
    Output: {intent, entities, confidence, node_durations}
    """
```

### Input Schema (`IntentParserInput`)

| Trường | Type | Nguồn | Mô tả |
|--------|------|-------|-------|
| `user_query` | `str` | `state.messages[-1].content` | Câu hỏi hiện tại |
| `conversation_history` | `list[dict]` | `state.messages[-5:]` | 5 turn gần nhất `{role, content}` |
| `planner_memory` | `dict` | `state.planner_memory` | Bộ nhớ cross-turn |
| `available_intents` | `list[str]` | Hằng số | Danh sách intent được phép |
| `available_tools` | `list[dict]` | `ToolRegistry` | Tool + mô tả ngắn |

### Output Schema (`IntentParserOutput`)

```python
class IntentEntities(BaseModel):
    product_name: Optional[str] = None       # Tên sản phẩm
    product_id: Optional[str] = None         # ID sản phẩm (từ reference)
    quantity: Optional[int] = None           # Số lượng
    min_price: Optional[float] = None        # Giá tối thiểu
    max_price: Optional[float] = None        # Giá tối đa
    from_currency: Optional[str] = None      # Tiền gốc
    to_currency: Optional[str] = None        # Tiền đích
    amount: Optional[float] = None           # Số tiền
    address: Optional[str] = None            # Địa chỉ giao
    category: Optional[str] = None           # Danh mục
    product_names: Optional[list[str]] = None  # DS sản phẩm (compare)
    sort_by: Optional[str] = None            # price / rating / newest
    sort_order: Optional[str] = None         # asc / desc
    product_name_a: Optional[str] = None     # SP 1 (compare)
    product_name_b: Optional[str] = None     # SP 2 (compare)

class IntentParserOutput(BaseModel):
    intent: str                    # IntentType enum value
    entities: IntentEntities       # Entities trích xuất
    confidence: float              # 0.0–1.0
    reasoning: Optional[str] = None  # Giải thích (log/debug)
```

### Thuật toán

1. Lấy query từ `state.messages[-1].content`
2. Build prompt với `INTENT_SYSTEM_PROMPT` + history + memory + tool schemas
3. **LLM-first** (gọi LLM với `temperature=0.0`, `max_tokens=300`):
   - LLM phân tích intent + entities từ query + context
   - LLM tự xử lý reference resolution qua planner_memory
   - Output: JSON theo `IntentParserOutput` schema
4. **Entity override** (nếu LLM bỏ sót entities rule-based dễ bắt):
   - `_MAX_PRICE_PAT`, `_MIN_PRICE_PAT`, `_QTY_PAT`, `_CURRENCY_PAT` vẫn chạy để override/gap-fill
5. **Regex fallback** (nếu LLM fail/timeout): chạy rule-based patterns như cũ → `confidence=0.6`

### Danh sách Intent (14 intents)

| Intent | Khi nào dùng | Ví dụ |
|--------|-------------|-------|
| `search` | Tìm sản phẩm theo từ khóa/giá/danh mục | *"tai nghe chống ồn dưới $50"* |
| `product_qa` | Hỏi về chất lượng, đặc điểm từ review thật | *"pin dùng bao lâu?"* |
| `cart_view` | Xem giỏ hàng | *"xem giỏ"* |
| `cart_add` | Thêm sản phẩm vào giỏ | *"thêm 2 cái vào giỏ"* |
| `cart_update` | Sửa số lượng / xóa khỏi giỏ | *"sửa thành 3"*, *"bỏ cái đó"* |
| `recommend` | Gợi ý sản phẩm tương tự / mua kèm | *"sản phẩm tương tự"* |
| `compare` | So sánh 2 sản phẩm | *"so sánh A và B"* |
| `currency` | Quy đổi tiền tệ | *"50 usd bằng bao nhiêu vnd"* |
| `shipping` | Tính phí / thời gian vận chuyển | *"phí ship đến Hà Nội"* |
| `greeting` | Chào hỏi, giới thiệu | *"xin chào"*, *"bạn là ai"* |
| `overview` | Hỏi cửa hàng bán gì | *"cửa hàng bán gì"* |
| `product_detail` | Xem thông tin chi tiết sản phẩm | *"cho xem thông tin sản phẩm X"* |
| `checkout` | Đặt hàng / thanh toán (từ chối) | *"đặt hàng"*, *"mua ngay"* |
| `unknown` | Không xác định | *(hỏi ngoài phạm vi)* |

### Phân biệt các intent dễ nhầm

| Cặp dễ nhầm | Cách phân biệt |
|-------------|----------------|
| `greeting` vs `overview` | Chỉ greeting khi user chào hoặc hỏi về khả năng bot. *"bạn bán gì"* → overview |
| `greeting` vs `search` | *"có sản phẩm quần áo không"* → search, không phải greeting |
| `product_qa` vs `review` | review: xem rating/số sao. product_qa: hỏi đáp grounded từ nội dung review (*"có tốt không"*, *"chất lượng thế nào"*) |
| `search` vs `overview` | overview: không có từ khóa cụ thể. search: có tên SP, giá, danh mục |

### Multi-turn Context

- Nếu user dùng *"nó"*, *"cái này"*, *"cái đầu tiên"* → LLM tự tra `planner_memory.last_product_id`
- Nếu user nói *"thêm vào giỏ"* không có tên SP → LLM lấy `last_product_id`
- planner_memory gửi kèm prompt dưới dạng text formatted

### Error Handling

| Case | Behavior |
|---|---|
| LLM parse fail (exception) | Retry 1 lần; fail → **regex fallback** → `intent="unknown"`, `confidence=0.0` |
| LLM JSON malformed | Retry parse; fail → regex fallback |
| LLM timeout (>3s) | → regex fallback, `confidence=0.5` |
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

### Plan Template Matcher (Zero-Cost Path)

Trước khi gọi LLM, TGB kiểm tra intent + entities vào **11 template** phổ biến:

| # | Intent | Entities | Template DAG |
|---|---|---|---|
| 1 | `cart_view` | — | `[get_cart_tool]` |
| 2 | `cart_add` | có `product_id` | `[add_to_cart_tool]` |
| 3 | `cart_add` | không có `product_id` | `[search_products_v2 → add_to_cart_tool]` |
| 4 | `search` | — | `[search_products_v2]` |
| 5 | `overview` | — | `[search_products_v2(query="danh mục")]` |
| 6 | `review` | có `product_id` | `[get_product_reviews_tool]` |
| 7 | `review` | không có `product_id` | `[search_products_v2 → get_product_reviews_tool]` |
| 8 | `product_qa` | — | `[search_products_v2 → get_product_reviews_tool → LLM tổng hợp]` |
| 9 | `product_detail` | — | `[get_product_id → get_product_details_tool]` |
| 10 | `cart_update` | — | `[update_cart_item_tool]` (cần confirmation) |
| 11 | `compare` | — | `[search_products_v2(A) → search_products_v2(B) → reviews(A) → reviews(B)]` |

**Mở rộng:** (giữ nguyên từ v3.2)
| # | Intent | Entities | Template DAG |
|---|---|---|---|
| 12 | `recommend` | có `product_id` | `[get_recommendations_tool]` |
| 13 | `recommend` | không có `product_id` | `[search_products_v2 → get_recommendations_tool]` |
| 14 | `currency` | — | `[convert_currency_tool]` |
| 15 | `shipping` | — | `[get_shipping_quote_tool]` |
| 16 | `greeting` | — | `[]` (empty — no tools) |
| 17 | `checkout` | — | `[]` (empty — decline) |

Template match → dùng DAG template ngay (zero-cost, không gọi LLM). No match → fallback xuống LLM path.

Combo intent (ví dụ review + recommend cùng lúc) cũng có thể được template hoá bằng cách ghép 2 template đơn.

### Prompt Building (LLM Path)
```python
TGB_PROMPT.format(
    tool_schemas_text=ToolRegistry.get_all_schemas_text(),
    user_query=query,
    intent=intent,
    entities=json.dumps(entities),
    planner_memory=format_memory(planner_memory),
)
```
- `temperature=0.2`, `response_format=json_object`, timeout=**5s**

### RepairLayer (Auto-Fix sau LLM)

Sau khi LLM trả DAG, RepairLayer tự sửa các lỗi nhẹ trước khi validate:

| Lỗi | Cách sửa |
|---|---|
| Tool name sai chính tả | Fuzzy match với ToolRegistry keys |
| `depends_on` ID không tồn tại | Sửa thành `[]` (chạy độc lập) |
| Confidence field thiếu | Gán mặc định `0.8` |
| Self-reference loop | Bỏ node đó |
| Node không có `description` | Tự sinh từ `ToolRegistry.get_spec(tool).description` |

### Validation Rules (sau Repair)
| Check | Fail → |
|---|---|
| Tool name không trong ToolRegistry (sau fuzzy) | Ghi error, bỏ node |
| `depends_on` ID vẫn không tồn tại | Ghi error, bỏ node |
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
| Timeout (>5s) | Plan rỗng, fallback template response |
| Tool denied (order, charge, etc.) | Plan rỗng, trả lời thẳng |
