# Shopping Copilot — Implementation Plan v3.2

> Dựa trên: `docs/design/agentic_design.md` v3.2 + toàn bộ tài liệu thiết kế trong `docs/design/`
> Mục tiêu: độ tương đồng 99% với tài liệu — giữ nguyên những gì đã đúng, xây mới những gì còn thiếu.

---

## Tổng quan trạng thái hiện tại

### ✅ Đã build — GIỮ NGUYÊN
| Module | File | Ghi chú |
|---|---|---|
| Guardrails L1–L6 | `src/guardrails/` | Tất cả 6 lớp hoạt động |
| Memory store | `src/memory/store.py` | SessionStore + InMemoryCacheStore |
| FastAPI server | `src/main.py` | 4 endpoints + chatbot UI |
| Proto compiled | `src/protos/` | demo_pb2 |
| Tools — search | `src/tools/search/` | Multi-strategy orchestrator |
| Tools — cart | `src/tools/cart_tool.py` | 4 cart tools |
| Tools — catalog | `src/tools/catalog_tool.py` | get_categories, get_all_products |
| Tools — product | `src/tools/product_tool.py` | get_product_details_tool |
| Tools — product_id | `src/tools/product_id_tool.py` | get_product_id |
| Tools — review | `src/tools/review_tool.py` | get_product_reviews_tool |
| Tools — recommend | `src/tools/recommendation_tool.py` | get_recommendations_tool |
| Tools — currency | `src/tools/currency_tool.py` | convert_currency_tool |
| Tools — shipping | `src/tools/shipping_tool.py` | get_shipping_quote_tool |
| LLM client | `src/llm/llm.py` | Bedrock Nova Lite + MockLLMClient |
| Input guard node | `src/graph/nodes/input_guard.py` | Giữ từ v2 |
| Answer generator | `src/graph/nodes/answer_generator.py` | Giữ từ v2 |
| Confirmation node | `src/graph/nodes/confirmation.py` | Giữ từ v2 |

### ⏳ Chưa build — CẦN TẠO MỚI
| Module | File | Spec tại |
|---|---|---|
| ToolRegistry + ToolSpec | `src/tools/registry.py` | agentic_design §6.1 |
| Graph state v3.2 | `src/graph/state.py` | state_design.md |
| Graph edges | `src/graph/edges.py` | agentic_design §2 |
| Intent Parser | `src/graph/nodes/intent_parser.py` | planner_design §7.1 |
| Task Graph Builder | `src/graph/nodes/task_graph_builder.py` | planner_design §7.2 |
| Tool Executor (DAG Runner) | `src/graph/nodes/tool_executor.py` | executor_design §8 |
| Reflection Node | `src/graph/nodes/reflection.py` | executor_design §8.5 |
| Response Verifier | `src/graph/nodes/response_verifier.py` | verifier_design.md |
| Hallucination Guard | `src/graph/nodes/hallucination_guard.py` | hallucination_design.md |
| Fallback Generator | `src/graph/nodes/fallback_generator.py` | hallucination_design.md |
| Gate Node (shared) | `src/graph/gates/gate_node.py` | gate_layer_design.md |
| Routing Gate | `src/graph/gates/routing_gate.py` | gate_layer_design §1 |
| Plan Validity Gate | `src/graph/gates/plan_validity_gate.py` | gate_layer_design §2 |
| Semantic Hallucination Gate | `src/graph/gates/semantic_hallucination_gate.py` | gate_layer_design §3 |
| Confirm Parse Gate | `src/graph/gates/confirm_parse_gate.py` | gate_layer_design §4 |
| Replan Gate | `src/graph/gates/replan_gate.py` | gate_layer_design §5 |
| CacheManager 2-layer | `src/memory/cache_manager.py` | cache_design §13.12 |
| Redis store | `src/memory/redis_store.py` | cache_design §13.12 |

| Service config | `src/tools/service_config.py` | config_design.md |

### 🔄 Cần cập nhật
| Module | File | Thay đổi |
|---|---|---|
| Main graph | `src/graph/main_graph.py` | Thêm nodes mới + DAG edges + reflection loop |
| Prompt | `src/llm/prompt.py` | Thêm TGB_PROMPT, VERIFIER_PROMPT, INTENT_PROMPT, gate prompts |
| Tools __init__ | `src/tools/__init__.py` | Thêm ToolRegistry.register() cho mỗi tool |

---

## Kế hoạch triển khai theo Phase


---

## Phase 0 — Nền tảng (Prerequisites)

Mục tiêu: tạo các building block mà tất cả phase sau phụ thuộc vào.

### 0.1 `src/tools/registry.py` — ToolRegistry + ToolSpec

Tạo mới hoàn toàn. Đây là singleton registry cho toàn bộ tool metadata.

```python
# Interface cần implement (agentic_design §6.1)
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    is_write: bool = False
    examples: list[dict] = field(default_factory=list)
    retry_config: dict = field(default_factory=lambda: {"max_retries": 1})

class ToolRegistry:
    _specs: dict[str, ToolSpec] = {}
    _fns: dict[str, Any] = {}

    @classmethod def register(cls, spec, fn=None): ...
    @classmethod def get_spec(cls, name): ...
    @classmethod def get_fn(cls, name): ...
    @classmethod def get_all_specs(cls): ...
    @classmethod def get_all_schemas_text(cls) -> str: ...
    @classmethod def clear(cls): ...  # dùng trong test
```

Mỗi tool file tự gọi `ToolRegistry.register(spec, fn=tool_fn)` ở module-level (sau khi define `@tool`). Không cần sửa `tools/__init__.py` để register — chỉ cần import.

### 0.2 Đăng ký ToolSpec cho tất cả tools hiện có

Thêm `ToolSpec` + `ToolRegistry.register()` vào cuối mỗi tool file. Dựa trên bảng schema trong `docs/design/tools/`.

| File | ToolSpec cần thêm |
|---|---|
| `tools/search/__init__.py` | `search_products_v2` — đã có draft, cần align với registry |
| `tools/cart_tool.py` | `add_to_cart_tool`, `update_cart_item_tool`, `get_cart_tool`, `check_cart_item_tool` |
| `tools/catalog_tool.py` | `get_categories`, `get_all_products` |
| `tools/product_tool.py` | `get_product_details_tool` |
| `tools/product_id_tool.py` | `get_product_id` |
| `tools/review_tool.py` | `get_product_reviews_tool` |
| `tools/recommendation_tool.py` | `get_recommendations_tool` |
| `tools/currency_tool.py` | `convert_currency_tool` |
| `tools/shipping_tool.py` | `get_shipping_quote_tool` |

### 0.3 `src/graph/state.py` — ShoppingState v3.2

Viết lại hoàn toàn từ v2. Xoá các field cũ, thêm field mới theo `state_design.md`.

**Xoá (v2 fields):**
`pending_workflows`, `current_workflow_index`, `workflow_results`, `current_product_id`, `resolved_product_name`, `candidate_products`

**Thêm (v3.2 fields):**
```
plan: dict                      # DAGPlan {nodes, edges}
plan_step_index: int
current_goal: str
planner_reasoning: str
plan_confidence: float
intent: str
entities: dict
resolved_entities: dict
tool_results: Annotated[dict, merge_tool_results]
tool_history: Annotated[list, accumulate_tool_history]
dependency_graph: dict
complexity_score: float
final_answer: str
groundedness_score: float
hallucination_detected: bool
fallback_used: bool
gate_decisions: dict
semantic_hallucination_detected: bool
replan_count: int
reflection_result: str          # "pass" | "replan"
reflection_issues: list
confidence: float
retry_count: int
planner_memory: dict            # last_search, last_product_id, last_product_name,
                                # last_results_ids, mentioned_products,
                                # current_cart_items, last_intent
session_id: str
user_id: str
trace_id: str
pending_action: Optional[dict]
confirmed: bool
guardrail_violations: list
errors: Annotated[dict, accumulate_errors]
node_durations: Annotated[dict, merge_node_durations]
```

**Reducers cần implement:**
- `merge_tool_results(existing, update)` — chỉ nhận key chưa tồn tại
- `accumulate_errors(existing, update)` — append
- `accumulate_tool_history(existing, update)` — append, giới hạn 6 turns
- `merge_node_durations(existing, update)` — cộng dồn ms theo node

### 0.4 `src/llm/prompt.py` — Thêm các prompt mới

Giữ `REWRITE_SEARCH_QUERY_PROMPT` và `SYSTEM_PROMPT` hiện có. Thêm:

```python
TGB_PROMPT = """..."""          # Task Graph Builder — spec §11
VERIFIER_PROMPT = """..."""     # Response Verifier — spec §11
INTENT_PROMPT = """..."""       # Intent Parser LLM fallback — spec §11
# Gate prompts (per gate) — spec §11 §4
GATE_SYSTEM_PROMPT = "Bạn là bộ phân loại nhị phân. Chỉ trả lời đúng 1 từ: YES hoặc NO."
GATE_QUESTIONS = {
    "routing_gate": "...",
    "plan_validity_gate": "...",
    "semantic_hallucination_gate": "...",
    "confirm_parse_gate": "...",
    "replan_gate": "...",
}
```

Prompt TGB dùng `{tool_schemas_text}` build động từ `ToolRegistry.get_all_schemas_text()` — không hardcode schema.

### 0.5 `src/tools/service_config.py`

Tạo nếu chưa tồn tại (đang có trong `__pycache__` nên có thể đã có). Đảm bảo chứa tất cả địa chỉ service theo `config_design.md`:

```python
CATALOG_ADDR = os.environ.get("CATALOG_ADDR", "localhost:3550")
CART_ADDR    = os.environ.get("CART_ADDR",    "localhost:7070")
REVIEWS_ADDR = os.environ.get("REVIEWS_ADDR", "localhost:9090")
RECO_ADDR    = os.environ.get("RECO_ADDR",    "localhost:8081")
CURRENCY_ADDR= os.environ.get("CURRENCY_ADDR","localhost:7001")
SHIPPING_ADDR= os.environ.get("SHIPPING_ADDR","http://localhost:50052")
```

---

## Phase 1 — Core Architecture (2-Layer Planner + DAG Executor + Reflection)

Mục tiêu: xây dựng luồng chính của graph v3.2.

### 1.1 `src/graph/nodes/intent_parser.py` — Intent Parser

Tạo mới. Spec: `planner_design.md §Layer 1`.

**Interface:**
```python
async def intent_parser_node(state: ShoppingState) -> dict:
    # Output: {intent, entities, confidence, node_durations}
```

**Thuật toán (theo đúng spec):**
1. Lấy query từ `state.messages[-1].content`
2. Rule-based match — 9 regex pattern sets (cart_view, cart_add, search, review, recommend, currency, shipping, checkout, greeting)
3. Entity extraction rule-based: quantity, max_price, min_price
4. Nếu confidence < 0.8 → LLM fallback với `INTENT_PROMPT` (temperature=0.0, max_tokens=100)
5. **ReferenceResolver** (stage cuối): đọc `planner_memory`, match 6 regex reference patterns → inject entities.product_id nếu user nói "nó", "cái đầu tiên", v.v.
6. Error cases: LLM fail → intent="unknown", confidence=0.0

**Rule patterns 9 intents** — implement đúng theo bảng trong `planner_design.md`.

**Reference patterns** — implement đúng 6 patterns trong `agentic_design §7.3`:
- `nó|cái này|cái đó` → `last_product_id`
- `cái đầu tiên|thứ 1|first` → `last_results_ids[0]`
- `thứ hai|thứ ba|2|3` → `last_results_ids[N]`
- `thêm.*(vào)?giỏ` → `last_product_id` + `quantity=1`
- `review|đánh giá|nhận xét` → `last_product_id`
- `so.*với|vs|hay` → `mentioned_products`

### 1.2 `src/graph/nodes/task_graph_builder.py` — Task Graph Builder

Tạo mới. Spec: `planner_design.md §Layer 2`.

**Interface:**
```python
async def task_graph_builder_node(state: ShoppingState) -> dict:
    # Output: {plan, plan_step_index, current_goal, planner_reasoning,
    #          plan_confidence, node_durations}
```

**Thuật toán:**
1. **Template Matcher (zero-cost)** — kiểm tra 7 template patterns trước khi gọi LLM:

| # | Intent | Entities | Template DAG |
|---|---|---|---|
| 1 | `cart_view` | — | `[get_cart_tool]` |
| 2 | `cart_add` | có `product_id` | `[add_to_cart_tool]` |
| 3 | `cart_add` | không có `product_id` | `[search→add_to_cart]` |
| 4 | `search` | — | `[search_products_v2]` |
| 5 | `review` | có `product_id` | `[get_product_reviews_tool]` |
| 6 | `review` | không có `product_id` | `[search→review]` |
| 7 | `recommend` | — | `[search→recommend]` |

2. Template match → trả DAG ngay (không gọi LLM)
3. No match → **LLM path**: build `TGB_PROMPT` với `ToolRegistry.get_all_schemas_text()` + `format_memory(planner_memory)` → gọi LLM (temperature=0.2, timeout=5s)
4. **RepairLayer** sau LLM: fuzzy match tool name, fix `depends_on` ID sai, thêm `confidence=0.8` nếu thiếu, bỏ self-reference loop, sinh `description` từ ToolSpec
5. **Validation**: kiểm tra tool name trong ToolRegistry, depends_on hợp lệ, max 8 nodes
6. `plan_confidence = average(nodes[i].confidence)`; nếu < 0.3 → plan rỗng → route `ask_user`
7. Error cases: LLM không parse được → retry 1 lần; timeout → plan rỗng

**`format_memory(memory: dict) -> str`** — implement đúng theo spec:
```python
# Nếu last_search → "Lần trước bạn tìm: ..."
# Nếu last_product_id → "Product ID vừa xem: ..."
# Nếu current_cart_items > 0 → "Giỏ hàng có N món"
# Nếu rỗng → "(không có dữ liệu phiên trước)"
```

### 1.3 `src/graph/nodes/tool_executor.py` — DAG Runner

Tạo mới. Spec: `executor_design.md §DAG Runner`.

**Interface:**
```python
async def tool_executor_node(state: ShoppingState) -> dict:
    # Output: {tool_results, errors, retry_count, pending_action, node_durations}
```

**Core algorithm — topological execution:**
```
node_map = index by node.id
done = set()
node_outputs = {}

while len(done) < len(plan.nodes):
    ready = [n for n in nodes if n.id not in done
             and all(dep in done for dep in n.depends_on)]
    if not ready → DeadlockError
    results = await asyncio.gather(*[execute_node(n) for n in ready],
                                   return_exceptions=True)
    for node, result in zip(ready, results):
        if exception → errors[node.id] = str(e); continue
        if node.condition → evaluate_condition → ask_user/stop/continue
        done.add(node.id); node_outputs[node.id] = result
```

**`execute_node` — 7 bước tuần tự:**
1. Resolve variable references (`$steps[id].path`, `$session.*`, `$input.entities.*`, `$memory.*`, `$first()`, `$exists()`, `$safe_index()`)
2. L3 validate: `validate_tool_call(tool_name, resolved_args, user_id)`
3. Cache check: nếu read tool + cache hit → return cached
4. Execute with retry: `ToolRegistry.get_fn(tool_name).ainvoke(args)` — retry config theo tool type
5. Normalize output: price_units + price_nanos → `"$X.XX"`, picture → image, categories TEXT → array
6. Cache set: nếu read tool
7. Return `(normalized_dict, source)`

**Variable Reference Resolver** — implement 7 syntax patterns đúng theo `executor_design §Variable Reference Resolver`.

**Retry config:**
- Read tools: max_retries=2, backoff=[0.5, 1.0]
- Write tools (add_to_cart): max_retries=1, backoff=[0.5]
- Checkout: max_retries=0

**Resource limits (enforced trong executor):**
- Max 8 nodes → trim nodes confidence thấp trước khi chạy
- Max DAG depth 5 → flatten nếu vượt
- Max 4 parallel nodes → batch asyncio.gather
- Tool timeout 2s (shipping: 3s)

**Write tool flow (L4 confirmation):**
- Gọi write tool → nhận `{status: "pending", token: "...", message: "..."}`
- Set `state.pending_action` → PAUSE graph (LangGraph interrupt)
- Khi resume (confirmed=True): đọc params từ `pending_action` → gọi gRPC thật → ghi kết quả

**Planner memory update sau mỗi node:**
Sau khi node search/get_product/get_cart/get_recommendations chạy xong:
```python
# Cập nhật planner_memory
memory["last_search"] = query nếu search
memory["last_product_id"] = products[0].id nếu có
memory["last_product_name"] = products[0].name
memory["last_results_ids"] = [p.id for p in products[:5]]
memory["mentioned_products"] = accumulate product IDs
memory["current_cart_items"] = item_count nếu cart tool
memory["last_intent"] = state.intent
```

### 1.4 `src/graph/nodes/reflection.py` — Reflection Node

Tạo mới. Spec: `executor_design.md §Reflection Node`.

**Interface:**
```python
async def reflection_node(state: ShoppingState) -> dict:
    # Output: {reflection_result, replan_count, reflection_issues, node_durations}
```

**4 trigger checks (sequential, first match wins):**
1. Zero result: tool nào trả `total=0` hoặc empty list → `zero_result`
2. Tool errors: `len(errors) >= 2` → `tool_errors`
3. Low confidence: `plan_confidence < 0.5` → `low_confidence`
4. Semantic gate: `semantic_hallucination_detected == True` → `semantic_gate_fail`

**Decision logic:**
```python
if replan_count >= 2:
    reflection_result = "pass"  # force pass — giới hạn replan
elif any_issue:
    reflection_result = "replan"
    replan_count += 1
else:
    reflection_result = "pass"
```

**Skip conditions** (auto pass):
- Không có tool_results
- Guardrail violation đã có
- `pending_action` tồn tại

### 1.5 `src/graph/edges.py` — Edge routing functions

Tạo mới. Tập hợp tất cả edge routing functions cho graph.

```python
def route_after_input_guard(state) -> str:
    # violations → "blocked"; pass → "intent_parser"

def route_after_intent_parser(state) -> str:
    # confidence < 0.3 → "ask_user"; pass → "task_graph_builder"
    # Hoặc routing_gate nếu cần fast path detection

def route_after_plan_validity_gate(state) -> str:
    # gate decision False (invalid) → "ask_user"; True → "tool_executor"

def route_after_reflection(state) -> str:
    # reflection_result == "replan" → "task_graph_builder"
    # pass → "response_verifier"

def route_after_hallucination_guard(state) -> str:
    # hallucination_detected True → "fallback_generator"
    # semantic_hallucination_detected True → "fallback_generator"
    # pass → "answer_generator"
```

### 1.6 `src/graph/main_graph.py` — Cập nhật build_graph()

Cập nhật graph để wire tất cả nodes mới. Graph topology theo spec `agentic_design §2`:

```
START → input_guard → intent_parser → task_graph_builder
    → [plan_validity_gate] → tool_executor → reflection
        → [pass] → response_verifier → hallucination_guard
            → [pass] → answer_generator → END
            → [fail] → fallback_generator → answer_generator → END
        → [replan] → task_graph_builder (partial)
```

**Nodes cần add:**
```python
graph.add_node("intent_parser", intent_parser_node)
graph.add_node("task_graph_builder", task_graph_builder_node)
graph.add_node("plan_validity_gate", plan_validity_gate_node)
graph.add_node("tool_executor", tool_executor_node)
graph.add_node("reflection", reflection_node)
graph.add_node("response_verifier", response_verifier_node)
graph.add_node("hallucination_guard", hallucination_guard_node)
graph.add_node("fallback_generator", fallback_generator_node)
```

**Edges:**
```python
graph.add_edge("input_guard", "intent_parser")
graph.add_edge("intent_parser", "task_graph_builder")
graph.add_edge("task_graph_builder", "plan_validity_gate")
graph.add_conditional_edges("plan_validity_gate", route_after_plan_validity_gate,
    {"tool_executor": "tool_executor", "ask_user": "response_verifier"})
graph.add_edge("tool_executor", "reflection")
graph.add_conditional_edges("reflection", route_after_reflection,
    {"replan": "task_graph_builder", "pass": "response_verifier"})
graph.add_edge("response_verifier", "hallucination_guard")
graph.add_conditional_edges("hallucination_guard", route_after_hallucination_guard,
    {"answer_generator": "answer_generator", "fallback_generator": "fallback_generator"})
graph.add_edge("fallback_generator", "answer_generator")
graph.add_edge("answer_generator", END)
```

**Xoá các node/edge cũ** không còn dùng trong v3.2: `IntentClassifier`, `EntityExtractor`, `ResolveProduct`, `Router`, `ResponseEditor`, các workflow subgraphs.

---

## Phase 2 — Response & Safety (Verifier + Hallucination + Gates)

Mục tiêu: xây dựng lớp kiểm tra chất lượng câu trả lời.

### 2.1 `src/graph/nodes/response_verifier.py` — Template-First Verifier

Tạo mới. Spec: `verifier_design.md`.

**Interface:**
```python
async def response_verifier_node(state: ShoppingState) -> dict:
    # Output: {final_answer, complexity_score, node_durations}
```

**Complexity scoring** (clamp [0, 1]):
```
query length > 20 từ → +0.2; > 10 từ → +0.1
số tool gọi: mỗi tool +0.1, max +0.3
result size > 10 items → +0.2; > 5 → +0.1
có pending_action → +0.1
```

**Template-First Decision Tree** (đúng theo `verifier_design.md`):
- `get_cart_tool` only → template "cart" / "cart_empty"
- `get_shipping_quote_tool` only → template "shipping"
- `convert_currency_tool` only → template "currency"
- `get_product_reviews_tool` only → template "reviews" / "reviews_none"
- `search_products_v2` only: total==0 → "search_none"; total≤3 → "search_single"; total>3 → LLM
- `pending_action` → template "confirm"
- multi-tool: complexity ≤ 0.5 → template ghép; > 0.5 → LLM

**Template set** — implement đầy đủ `TEMPLATES` dict với 2–3 variants mỗi loại, random choice:
```python
TEMPLATES = {
    "cart": ["Giỏ hàng của bạn có {count} món: {items}. Tổng cộng {total}.", ...],
    "cart_empty": ["Giỏ hàng của bạn hiện đang trống.", ...],
    "shipping": ["Phí vận chuyển đến {destination}: {cost}, giao trong {days} ngày.", ...],
    "currency": ["{amount} {from} tương đương {converted} {to} (tỷ giá {rate}).", ...],
    "reviews": ["Sản phẩm được đánh giá {avg}/5 sao từ {total} đánh giá. {top_review}", ...],
    "reviews_none": ["Sản phẩm này chưa có đánh giá nào.", ...],
    "confirm": ["Vui lòng xác nhận: thêm {quantity} {product_name} vào giỏ hàng.", ...],
    "search_single": ["Tôi tìm thấy {count} sản phẩm: {product_list}.", ...],
    "search_none": ["Tôi không tìm thấy sản phẩm nào phù hợp.", ...],
}
```

**`format_product_list(products, max_count=5)`:**
```python
# "Tent XYZ ($99.99), Stove ABC ($49.99) và 3 sản phẩm khác"
```

**LLM path** (khi complexity > 0.5):
- Dùng `VERIFIER_PROMPT` với `tool_results_text` format theo spec
- temperature động: <0.2 → 0.1; <0.5 → 0.3; <0.8 → 0.4; ≥0.8 → 0.6
- max_tokens=1200, timeout=4s
- Fallback khi LLM lỗi: dùng raw tool results text

**Skip conditions:**
- Không có tool_results → giữ `final_answer` từ guardrail
- Guardrail violations → giữ nguyên
- LLM unavailable → template fallback
- FallbackGenerator đã chạy → không chạy lại

### 2.2 `src/graph/nodes/hallucination_guard.py` — HallucinationGuard

Tạo mới. Spec: `hallucination_design.md §HallucinationGuard`.

**Interface:**
```python
async def hallucination_guard_node(state: ShoppingState) -> dict:
    # Output: {groundedness_score, hallucination_detected, fallback_used, node_durations}
```

**Core rule: Chỉ chạy khi `complexity_score > 0.5`**. Template path → auto PASS, score=1.0.

**6 exact deterministic checks** (bắt đầu từ 1.0, trừ penalty, clamp [0,1]):

| Check | Cơ chế | Penalty |
|---|---|---|
| Price | Regex `\$\d+(?:\.\d{2})?` → exact match với tool_results | -0.15 each |
| Entity list | set intersection answer tokens ∩ known_set từ tool_results | -0.40 |
| Entity zero-result | search total=0 → mọi entity token là violation | -0.50 |
| Count | Regex `(\d+)\s*(sản phẩm\|kết quả\|đánh giá\|món)` | -0.15 |
| Score | Regex `(\d+\.?\d*)\s*/?\s*5` → match ±0.1 tolerance | -0.15 |
| Action confirm | Regex `(đã thêm\|đã xoá\|đã cập nhật)` chỉ khi confirmed | -0.15 |

**Entity verification (list intersection):**
1. Build `known_set` từ `products[].name`, `products[].categories`, `items[].name`
2. Extract candidate tokens từ answer (danh từ 3+ ký tự, loại stop words VI+EN)
3. Token không trong known_set → entity violation
4. Nếu known_set rỗng + total>0 → skip entity check

**Decision:**
```
score >= 0.8 → PASS → semantic_hallucination_gate (nếu còn claims)
score < 0.8  → FAIL → hallucination_detected = True → FallbackGenerator
```

**Edge cases** theo đúng bảng trong spec.

### 2.3 `src/graph/nodes/fallback_generator.py` — FallbackGenerator

Tạo mới. Spec: `hallucination_design.md §FallbackGenerator`.

**Interface:**
```python
async def fallback_generator_node(state: ShoppingState) -> dict:
    # Output: {final_answer, fallback_used, node_durations}
```

**Strategy:** Xác định tool types từ `tool_results` keys → chọn template phù hợp → render.

**Template selection logic:**
1. Nếu `pending_action` → template "confirm"
2. Single tool → template tương ứng
3. Multi tool → ghép template từng tool

**Single tool templates** (3–4 variants, random choice) — implement đầy đủ 10 loại theo `hallucination_design.md §Template`.

**`select_fallback_template(tool_types, data)`** — implement đúng priority theo spec.

### 2.4 `src/graph/gates/gate_node.py` — Shared Gate Interface

Tạo mới. Spec: `gate_layer_design.md §Shared Gate Node Interface`.

```python
@dataclass
class GateResult:
    decision: bool
    reason: Optional[str]
    latency_ms: float
    tokens: dict  # {input: int, output: int}

async def gate_node(
    question: str,
    context: str,
    want_reason: bool = False,
    timeout: float = 2.0,
) -> GateResult:
    """
    Gọi Amazon Nova Lite với binary classification.
    System: "Bạn là bộ phân loại nhị phân. Chỉ trả lời đúng 1 từ: YES hoặc NO."
    temperature=0.0, max_tokens=3 (25 nếu want_reason)
    Parse: text.upper().startswith("YES") → True
    Fallback khi timeout/error: return GateResult(decision=DEFAULT_DECISIONS[gate_name])
    """
```

**DEFAULT_DECISIONS:**
```python
DEFAULT_DECISIONS = {
    "routing_gate": False,              # an toàn — đi LLM path
    "plan_validity_gate": True,         # không block vô cớ
    "semantic_hallucination_gate": False, # thiên về fallback
    "confirm_parse_gate": True,         # UX: không từ chối nhầm
    "replan_gate": False,               # tránh loop vô hạn
}
```

### 2.5 `src/graph/gates/` — 5 Gate Nodes

Tạo 5 files. Mỗi file implement 1 gate node dùng `gate_node()` từ `gate_node.py`.

**`routing_gate.py`** — Position: trước Intent Parser (optional, chỉ khi L2a không match rõ)
```python
async def routing_gate_node(state) -> dict:
    # question: "Câu hỏi mua sắm này có match pattern đơn giản không?"
    # want_reason=False, timeout=2.0
    # Default: False (đi LLM path)
```

**`plan_validity_gate.py`** — Position: sau TGB, chỉ khi `len(plan.nodes) > 1`
```python
async def plan_validity_gate_node(state) -> dict:
    # question: "DAG plan có đủ step, không thiếu dependency không?"
    # context: intent + entities + plan JSON
    # want_reason=True, timeout=2.0
    # gate_decisions["plan_validity_gate"] = {decision, reason}
```

**`semantic_hallucination_gate.py`** — Position: sau HallucinationGuard, per-claim
```python
async def semantic_hallucination_gate_node(state) -> dict:
    # Chạy asyncio.gather cho tất cả claims cần check
    # Nếu bất kỳ claim nào FAIL → semantic_hallucination_detected = True
    # want_reason=True, timeout=2.0 per claim
```

**`confirm_parse_gate.py`** — Position: POST /api/confirm handler (khi user gửi text thay vì click)
```python
async def confirm_parse_gate_node(state) -> dict:
    # question: "Phản hồi có phải đồng ý xác nhận không?"
    # want_reason=False, timeout=2.0
    # Default: True (thiên về confirm)
```

**`replan_gate.py`** — Position: Reflection node khi có lỗi/0 kết quả
```python
async def replan_gate_node(state) -> dict:
    # question: "Kết quả có đạt được goal không, hay cần replan?"
    # context: goal + tool_results tóm tắt + errors
    # want_reason=True, timeout=2.0
    # Default: False (không replan)
```

---

## Phase 3 — Integration & Production (Cache + Config + API update)

Mục tiêu: kết nối đầy đủ với Redis cache, cập nhật API, và đảm bảo production-readiness.

### 3.1 `src/memory/cache_manager.py` — CacheManager 2-layer

Tạo mới. Spec: `cache_design.md §CacheManager`.

```python
class CacheManager:
    """
    Layer 1 (primary): Redis — production
    Layer 2 (fallback): In-memory — khi Redis down
    Circuit breaker: CLOSED → OPEN (2 fail) → HALF-OPEN (30s) → CLOSED
    """
    def __init__(self, redis_url=None): ...
    async def _redis_healthy(self) -> bool: ...   # circuit breaker
    async def get(self, key, db_type) -> Optional[Any]: ...
    async def set(self, key, value, db_type, ttl) -> None: ...
    async def delete(self, key, db_type) -> None: ...
```

**Cache keys** theo spec:
```
planner:{sha256(query)[:16]}         TTL 5m   DB0
search:{sha256(lang+q+price+cat)[:16]} TTL 10m  DB1
product:{product_id}                  TTL 30m  DB1
currency:{from}:{to}                  TTL 60m  DB1
shipping:{sha256(zip+total)[:16]}     TTL 30m  DB1
recommend:{product_id}:{limit}        TTL 15m  DB1
session:{session_id}                  TTL 30m  DB2
```

**Điều kiện cache:** chỉ cache khi tool thành công, không phải write tool, confidence ≥ 0.9 cho plan.

### 3.2 `src/memory/redis_store.py` — RedisCacheStore

Tạo mới. Spec: `cache_design.md §RedisCacheStore`.

```python
class RedisCacheStore:
    def __init__(self, redis_url: str): ...
    async def get(self, key, db_type) -> Optional[Any]: ...
    async def set(self, key, value, db_type, ttl) -> None: ...
    async def delete(self, key, db_type) -> None: ...
    async def ping(self) -> bool: ...
    # Planner cache: chỉ cache nếu confidence >= 0.9
    # Invalidation: product update → xoá product:id + flush search:* + recommend:*
```

**Redis DB mapping:**
- `db_type="planner"` → DB0 (`noeviction`, 256MB)
- `db_type="tool"` → DB1 (`allkeys-lru`, 2GB)
- `db_type="session"` → DB2 (`volatile-ttl`, 512MB)

### 3.3 `src/memory/store.py` — Mở rộng InMemoryCacheStore

Thêm interface `get(key, db_type)` và `set(key, value, db_type, ttl)` vào `CacheStore` hiện có để compatible với `CacheManager`. Giữ nguyên `OrderedDict` LRU logic.

### 3.4 `src/guardrails/rate_limiter.py` — Global Rate Limiter (Redis)

Mở rộng rate_limiter hiện có. Spec: `cache_design.md §Global Rate Limiter`.

Thêm `RedisRateLimiter` class bên cạnh `InMemoryRateLimiter` hiện có:
```python
class RedisRateLimiter:
    def __init__(self, redis=None): ...
    async def check(self, user_id) -> RateLimitResult:
        # Redis available → global sorted set
        # Redis down → fallback per-pod in-memory
```

Redis sorted set approach:
```python
# key = f"ratelimit:{user_id}:{now // 86400}"
# zadd timestamp, zremrangebyscore old, zcard → count, expire 24h
```

Giữ nguyên `InMemoryRateLimiter` làm fallback.

### 3.5 `src/main.py` — Cập nhật API

Cập nhật `_build_steps()` và `_STEP_LABELS` để map sang node names mới của v3.2:

```python
_STEP_LABELS = {
    "input_guard": "Kiểm tra đầu vào",
    "intent_parser": "Phân tích ý định",
    "task_graph_builder": "Lập kế hoạch",
    "plan_validity_gate": "Kiểm tra kế hoạch",
    "tool_executor": "Thực thi công cụ",
    "reflection": "Kiểm tra kết quả",
    "response_verifier": "Xác nhận câu trả lời",
    "hallucination_guard": "Kiểm tra hallucination",
    "fallback_generator": "Tạo câu trả lời dự phòng",
    "answer_generator": "Tạo câu trả lời",
}
```

Đảm bảo `_build_steps()` đọc đúng `state.node_durations` với key format mới.

### 3.6 `src/graph/gates/__init__.py` + `src/graph/nodes/__init__.py`

Tạo các `__init__.py` để expose public API:
```python
# graph/gates/__init__.py
from .gate_node import gate_node, GateResult
from .routing_gate import routing_gate_node
from .plan_validity_gate import plan_validity_gate_node
from .semantic_hallucination_gate import semantic_hallucination_gate_node
from .confirm_parse_gate import confirm_parse_gate_node
from .replan_gate import replan_gate_node
```

---

## Chi tiết kỹ thuật quan trọng

### Price Normalization (áp dụng mọi nơi)
```python
def normalize_price(units: int, nanos: int, currency="USD") -> str:
    cents = nanos // 10_000_000
    if currency == "USD":
        return f"${units}.{cents:02d}"
    return f"{units}.{cents:02d} {currency}"
```

Áp dụng trong: `tool_executor.py` (normalize output), tất cả tool files (output schema), `response_verifier.py` (format_product_list).

### Guardrail mapping v3.2 (không thay đổi logic, chỉ đổi vị trí gọi)
```
L1 Rate Limiter   → input_guard node (giữ nguyên)
L2a Regex Filter  → input_guard node (giữ nguyên)
L2b Bedrock       → input_guard node (stub, giữ nguyên)
L3 Tool Validator → tool_executor.execute_node() step 2
L4 Confirmation   → tool_executor (write tool flow)
L5 Output Filter  → answer_generator node (giữ nguyên)
L6 Fallback       → @with_fallback wraps graph entry (giữ nguyên)
```

### LangGraph Checkpoint + Interrupt
- Dùng `MemorySaver` (hiện có) cho development
- Production → PostgreSQL checkpointer (roadmap)
- `interrupt()` tại write tool trong `tool_executor` → `Command(resume=...)` tại `/api/confirm`

### DAGPlan JSON format (Executor cần đọc đúng)
```json
{
  "nodes": [
    {"id": "n0", "tool": "search_products_v2", "description": "...",
     "depends_on": [], "condition": null, "confidence": 0.95},
    {"id": "n1", "tool": "add_to_cart_tool", "description": "...",
     "depends_on": ["n0"], "condition": null, "confidence": 0.85}
  ],
  "edges": [["n0", "n1"]]
}
```

---

## Thứ tự triển khai khuyến nghị

```
Phase 0 (nền tảng — làm trước tiên):
  0.1 → src/tools/registry.py
  0.3 → src/graph/state.py
  0.4 → src/llm/prompt.py  (thêm TGB/VERIFIER/INTENT/GATE prompts)
  0.2 → Thêm ToolSpec vào tất cả tool files
  0.5 → src/tools/service_config.py (verify tồn tại)

Phase 1 (core — theo thứ tự dependency):
  1.1 → intent_parser.py       (phụ thuộc: state.py, prompt.py)
  1.2 → task_graph_builder.py  (phụ thuộc: registry.py, state.py, prompt.py)
  1.3 → tool_executor.py       (phụ thuộc: registry.py, state.py, guardrails)
  1.4 → reflection.py          (phụ thuộc: state.py)
  1.5 → edges.py               (phụ thuộc: tất cả nodes)
  1.6 → main_graph.py          (phụ thuộc: tất cả ở trên)

Phase 2 (response & safety):
  2.4 → gate_node.py           (shared, không phụ thuộc node khác)
  2.1 → response_verifier.py   (phụ thuộc: state.py, prompt.py)
  2.2 → hallucination_guard.py (phụ thuộc: state.py)
  2.3 → fallback_generator.py  (phụ thuộc: state.py)
  2.5 → 5 gate files           (phụ thuộc: gate_node.py)

Phase 3 (integration):
  3.1 → cache_manager.py
  3.2 → redis_store.py
  3.3 → store.py (mở rộng)
  3.4 → rate_limiter.py (mở rộng)
  3.5 → main.py (cập nhật labels)
   3.6 → graph/gates/__init__.py + graph/nodes/__init__.py
```

---

## Kiểm tra sau triển khai

### Smoke tests (chạy sau mỗi phase)
```bash
# Phase 0: registry import không lỗi
python -c "from src.tools.registry import ToolRegistry; from src.tools import all_shopping_tools; print(len(ToolRegistry.get_all_specs()), 'tools registered')"

# Phase 1: graph build không lỗi
python -c "from src.graph.main_graph import build_graph; g = build_graph(); print('Graph OK')"

# Phase 1+2: end-to-end test với mock
python scripts/test_langgraph.py --mock

# Full eval suite
python scripts/run_eval_suite.py
```

### Key test cases cần pass
| Test | Expected |
|---|---|
| "tìm kính thiên văn dưới 200 đô" → search intent | `intent=search`, DAG=[search_products_v2] |
| "thêm 2 cái vào giỏ" (sau search) | reference resolve → `product_id` từ memory |
| "add 2 tents to my cart" | DAG=[search→add_to_cart], status=pending |
| Prompt injection attempt | L2a block, `guardrail_violations` có entry |
| "thanh toán" / "checkout" | TGB trả plan rỗng, trả lời từ chối |
| search trả 0 kết quả | reflection → zero_result issue, replan hoặc thông báo |
| LLM timeout (TGB) | plan rỗng, template response |
| Cart view | template path, không gọi LLM verifier |

---

## File tree sau khi hoàn thành

```
src/
├── graph/
│   ├── __init__.py
│   ├── main_graph.py          🔄 cập nhật
│   ├── state.py               🔄 viết lại v3.2
│   ├── edges.py               ✨ mới
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── input_guard.py     ✅ giữ nguyên
│   │   ├── answer_generator.py ✅ giữ nguyên
│   │   ├── confirmation.py    ✅ giữ nguyên
│   │   ├── intent_parser.py   ✨ mới
│   │   ├── task_graph_builder.py ✨ mới
│   │   ├── tool_executor.py   ✨ mới
│   │   ├── reflection.py      ✨ mới
│   │   ├── response_verifier.py ✨ mới
│   │   ├── hallucination_guard.py ✨ mới
│   │   └── fallback_generator.py ✨ mới
│   └── gates/
│       ├── __init__.py        ✨ mới
│       ├── gate_node.py       ✨ mới
│       ├── routing_gate.py    ✨ mới
│       ├── plan_validity_gate.py ✨ mới
│       ├── semantic_hallucination_gate.py ✨ mới
│       ├── confirm_parse_gate.py ✨ mới
│       └── replan_gate.py     ✨ mới
├── tools/
│   ├── registry.py            ✨ mới
│   ├── service_config.py      ✅ verify
│   ├── [all tool files]       🔄 thêm ToolSpec
│   └── search/

├── memory/
│   ├── store.py               🔄 mở rộng interface
│   ├── cache_manager.py       ✨ mới
│   └── redis_store.py         ✨ mới
├── guardrails/
│   └── rate_limiter.py        🔄 thêm RedisRateLimiter
├── llm/
│   └── prompt.py              🔄 thêm TGB/VERIFIER/INTENT/GATE prompts
└── main.py                    🔄 cập nhật _STEP_LABELS + _build_steps
```

**Tổng: 15 file mới (✨) + 8 file cập nhật (🔄) + 3 file giữ nguyên quan trọng (✅)**

---

## Phase 4 — Sửa thiếu sót & Hoàn thiện (Code vs Spec)

Mục tiêu: đóng tất cả gap giữa code hiện tại và design spec (docs/design/). Các component đã được code nhưng chưa gắn kết, chưa tích hợp, hoặc chưa đúng spec.

> Nguồn gap: kết quả đối chiếu code vs toàn bộ `docs/design/` (trừ guardrail pipeline, evaluation).

---

### 4.1 Wire 4 Gate nodes vào graph

**Spec:** `gate_layer_design.md` (toàn bộ), `agentic_design.md §10.6`

**Hiện trạng:** 5 gate files đã code đầy đủ (gate_node.py, routing_gate, replan_gate, semantic_hallucination_gate, confirm_parse_gate), nhưng chỉ `plan_validity_gate` được đăng ký trong `main_graph.py`.

**Thay đổi:**

```
main_graph.py:
  - Import 4 gate nodes từ src.graph.gates
  - graph.add_node("routing_gate", routing_gate_node)
  - graph.add_node("replan_gate", replan_gate_node)
  - graph.add_node("semantic_hallucination_gate", semantic_hallucination_gate_node)

  edges.py:
  - Thêm route_after_routing_gate(state) → fast path "response_verifier" | LLM path "intent_parser"
  - route_after_reflection → intermediate replan_gate (không đi thẳng task_graph_builder)

hallucination_guard.py:
  - Sau khi rule-based PASS (score ≥ 0.8), nếu còn claims → gọi semantic_hallucination_gate_node
  - Thêm claim extraction + asyncio.gather per-claim check
```

| Gate | Vị trí mới | Edge | Khi fallback |
|------|-----------|------|-------------|
| `routing_gate` | Trước Intent Parser | pass → response_verifier (template); fail → intent_parser | False (đi LLM path) |
| `replan_gate` | Sau Reflection | YES → task_graph_builder; NO → response_verifier | False (không replan) |
| `semantic_hallucination_gate` | Sau HallucinationGuard (per-claim) | PASS → answer_generator; FAIL → fallback_generator | False (fallback) |

**File cần sửa:**
- `src/graph/main_graph.py` — import + add_node + add_edge
- `src/graph/edges.py` — thêm routing functions
- `src/graph/nodes/hallucination_guard.py` — gọi semantic gate khi PASS

---

### 4.2 Tích hợp Cache vào Tool Executor

**Spec:** `cache_design.md §4 CacheManager`, `executor_design.md §1` bước 3 + 6

**Hiện trạng:** CacheManager 2-layer (Redis + in-memory), RedisCacheStore, InMemoryCacheStore đã code xong. Tool Executor không gọi cache.

**Thay đổi trong `tool_executor.py` → `execute_one()`:**

```
Bước 3 (sau L3 validate, trước execute):
  Nếu read tool (is_write=False):
    cache_key = build_cache_key(tool_name, args)
    cached = await cache_manager.get(cache_key, "tool")
    if cached: return cached

Bước 6 (sau normalize output, trước return):
  Nếu read tool + result success:
    ttl = get_ttl_for_tool(tool_name)       # search=600, product=1800, v.v.
    await cache_manager.set(cache_key, result, "tool", ttl)
```

**Hàm build_cache_key:**
```python
def build_cache_key(tool_name: str, args: dict) -> str:
    """Sinh cache key theo naming convention trong cache_design.md."""
    if tool_name == "search_products_v2":
        query = args.get("query", "")
        return f"search:{sha256(query.lower())[:16]}"
    if tool_name == "get_product_details_tool":
        return f"product:{args.get('product_id', '')}"
    if tool_name == "convert_currency_tool":
        return f"currency:{args.get('from','USD')}:{args.get('to','VND')}"
    if tool_name == "get_shipping_quote_tool":
        zip_code = args.get("zip_code", "")
        total = args.get("cart_total", "0")
        return f"shipping:{sha256(zip_code + total)[:16]}"
    if tool_name == "get_recommendations_tool":
        pid = args.get("product_id", "all")
        limit = args.get("limit", 5)
        return f"recommend:{pid}:{limit}"
    if tool_name in ("get_cart_tool", "get_categories", "get_all_products", "get_product_id"):
        return f"{tool_name}:{sha256(str(sorted(args.items())))[:16]}"
    return None  # no cache
```

**File cần sửa:**
- `src/graph/nodes/tool_executor.py`

---

### 4.3 Đăng ký confirmation_node vào graph

**Spec:** `confirm_design.md §Confirmation Node`

**Hiện trạng:** `src/graph/nodes/confirmation.py` (88 dòng) code đầy đủ gRPC AddItem/update_cart, được export từ `__init__.py` nhưng không được `main_graph.py` đăng ký.

**Thay đổi:**

```python
# main_graph.py
from src.graph.nodes import confirmation_node
graph.add_node("confirmation", confirmation_node)

# Edge: tool_executor → confirmation → reflection
# Khi tool_executor gặp pending_action + interrupt:
#   Resume → graph vào confirmation node trước
#   Nếu confirmed=True → execute gRPC, clear pending_action, set final_answer
#   Nếu confirmed=False → skip, trả về pending_action message
```

**Luồng mới:**
```
tool_executor → interrupt (pending)
    → API trả token → user POST /api/confirm
    → graph resume → confirmation_node
        → confirmed=True  → gRPC AddItem → ghi tool_results → response_verifier
        → confirmed=False → skip → giữ nguyên pending
```

**File cần sửa:**
- `src/graph/main_graph.py`

---

### 4.4 Thêm Variable Reference Helpers (`$first`, `$exists`, `$safe_index`)

**Spec:** `agentic_design.md §8.2`

**Hiện trạng:** `_resolve_value()` trong tool_executor.py hỗ trợ `$steps`, `$session`, `$input.entities`, `$memory` nhưng thiếu 3 helpers an toàn.

**Thay đổi trong `tool_executor.py` → `_resolve_value()`:**

```python
import ast  # safe literal eval for defaults

def _resolve_value(val: Any, node_outputs: dict, state: dict) -> Any:
    # ... existing resolution for $steps, $session, $input, $memory ...

    # New helpers (chạy trước hoặc sau các pattern khác)

    # $first(path, default=None)
    val = re.sub(
        r'\$first\(([^,]+),\s*default=([^)]+)\)',
        lambda m: _safe_first(m.group(1).strip(), m.group(2).strip(), node_outputs),
        val,
    )

    # $exists(path)
    val = re.sub(
        r'\$exists\(([^)]+)\)',
        lambda m: str(_safe_exists(m.group(1).strip(), node_outputs)),
        val,
    )

    # $safe_index(path, index, default=None)
    val = re.sub(
        r'\$safe_index\(([^,]+),\s*(\d+),\s*default=([^)]+)\)',
        lambda m: _safe_index(m.group(1).strip(), int(m.group(2)), m.group(3).strip(), node_outputs),
        val,
    )

    return val


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
    if "steps[" in path_expr:
        # Parse dạng steps[n0].products
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
```

**File cần sửa:**
- `src/graph/nodes/tool_executor.py`

---

### 4.5 Implement Conditional Branching trong Tool Executor

**Spec:** `executor_design.md §1` — `condition` field thuộc DAGNode

**Hiện trạng:** DAGNode schema có `condition` field (VD: `{"on": "total", "==0": "ask_user", "default": "continue"}`), TGB sinh condition trong template, nhưng Executor không đọc/evaluate.

**Thay đổi trong `tool_executor.py`:**

```python
def _evaluate_condition(result: dict, condition: dict) -> str:
    """
    Evaluate condition expression.
    Return: "ask_user" | "stop" | "continue"
    """
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


# Trong execute_one(), sau khi có kết quả:
node = node_map[nid]  # node hiện tại
condition = node.get("condition")
if condition:
    branch = _evaluate_condition(result, condition)
    if branch == "ask_user":
        interrupt({"pending_action": {"type": "ask_user", "message": result.get("message", "")}})
        return {...}  # early return với pending
    elif branch == "stop":
        done.add(nid)
        continue  # dừng DAG, không chạy node khác
    # branch == "continue" → chạy bình thường
```

**File cần sửa:**
- `src/graph/nodes/tool_executor.py`

---

### 4.6 Implement RepairLayer cho Task Graph Builder

**Spec:** `planner_design.md §2` — RepairLayer (sau LLM, trước validation)

**Hiện trạng:** TGB gọi LLM → parse JSON → validate cơ bản → output. RepairLayer chưa tồn tại (không fuzzy match, không tự sửa depends_on).

**Thay đổi trong `task_graph_builder.py`:**

Thêm `_repair_plan(nodes: list, edges: list) -> tuple[list, list]` chạy ngay sau LLM output, trước validate:

```python
from difflib import get_close_matches


def _repair_plan(nodes: list, edges: list) -> tuple[list, list]:
    """
    RepairLayer: tự sửa lỗi nhẹ trong LLM output.
    Spec: planner_design.md §2 RepairLayer
    """
    from src.tools.registry import ToolRegistry
    valid_tools = set(ToolRegistry.get_all_specs().keys())

    repaired_nodes = []
    for node in nodes:
        n = dict(node)

        # 1. Fuzzy match tool name
        tool = n.get("tool", "")
        if tool not in valid_tools:
            matches = get_close_matches(tool, valid_tools, n=1, cutoff=0.7)
            if matches:
                logger.info("[repair] tool '%s' → '%s'", tool, matches[0])
                n["tool"] = matches[0]
            else:
                logger.warning("[repair] tool '%s' không tìm thấy — bỏ node", tool)
                continue

        # 2. Fix depends_on ID không tồn tại
        existing_ids = {nd["id"] for nd in nodes}
        n["depends_on"] = [dep for dep in n.get("depends_on", []) if dep in existing_ids]

        # 3. Gán confidence mặc định 0.8 nếu thiếu
        n.setdefault("confidence", 0.8)

        # 4. Sinh description từ ToolSpec nếu thiếu
        if not n.get("description"):
            spec = ToolRegistry.get_spec(tool)
            n["description"] = spec.description if spec else f"Run {tool}"

        # 5. Bỏ self-reference
        if n["id"] in n["depends_on"]:
            n["depends_on"] = [d for d in n["depends_on"] if d != n["id"]]

        repaired_nodes.append(n)

    # 6. Lọc edges: chỉ giữ cạnh mà cả from và to đều tồn tại trong repaired_nodes
    repaired_ids = {n["id"] for n in repaired_nodes}
    repaired_edges = [(f, t) for f, t in edges if f in repaired_ids and t in repaired_ids]

    return repaired_nodes, repaired_edges
```

**File cần sửa:**
- `src/graph/nodes/task_graph_builder.py`

---

### 4.7 Thêm observability metrics

**Spec:** `observability_design.md`

**Hiện trạng:** Chỉ có `node_durations` trong state.

**Thay đổi:**

```
main.py:
  - Thêm middleware metrics (end-to-end latency P50/P95/P99)
  - Counter cho guardrail violations, gate decisions, tool errors

hallucination_guard.py:
  - Counter: hallucination_passed / hallucination_failed

gate_node.py:
  - Counter: gate_calls per gate name, gate_decisions YES/NO, gate_timeouts

rate_limiter.py:
  - Counter: rate_limit_hits, rate_limit_blocked

confirm_design (tool_executor + confirmation):
  - Counter: confirm_pending, confirm_approved, confirm_denied, confirm_expired
```

**Implement middleware đơn giản:**
```python
# main.py
import time
from collections import defaultdict

_metrics = {
    "latencies": defaultdict(list),     # endpoint → [ms]
    "gate_decisions": defaultdict(int), # gate_name:decision → count
    "hallucination": defaultdict(int),  # pass/fail
    "tool_results": defaultdict(int),   # tool_name → count
}

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start) * 1000
    _metrics["latencies"][request.url.path].append(latency_ms)
    return response
```

**File cần sửa:**
- `src/main.py` — middleware + metrics endpoint
- `src/graph/nodes/hallucination_guard.py`
- `src/graph/gates/gate_node.py`
- `src/guardrails/rate_limiter.py`

---

### 4.8 Sửa lệch replan_count (max 1 theo spec)

**Spec:** `resource_limits_design.md` — max replan = 1

**Hiện trạng:** `reflection.py` dùng `if replan_count >= 2: force pass` (cho phép 2 lần).

**Sửa:**
```python
# reflection.py — dòng 66
if replan_count >= 1:        # thay vì >= 2
    reflection_result = "pass"
```

**File cần sửa:**
- `src/graph/nodes/reflection.py`

---

### 4.9 Enforce Max DAG Depth = 5

**Spec:** `resource_limits_design.md` — max DAG depth = 5 levels

**Hiện trạng:** Không kiểm tra.

**Thêm vào `tool_executor.py`:**

```python
def _compute_dag_depth(nodes: list, edges: list) -> int:
    """Tính độ sâu lớn nhất của DAG (longest path)."""
    node_map = {n["id"]: n for n in nodes}
    depths = {}
    adj = {n["id"]: [] for n in nodes}
    for f, t in edges:
        adj[f].append(t)

    def dfs(nid: str) -> int:
        if nid in depths:
            return depths[nid]
        if not adj[nid]:
            depths[nid] = 1
            return 1
        depths[nid] = 1 + max(dfs(child) for child in adj[nid])
        return depths[nid]

    if not nodes:
        return 0
    return max(dfs(n["id"]) for n in nodes)


# Trong tool_executor_node(), đầu hàm:
depth = _compute_dag_depth(nodes, plan.get("edges", []))
if depth > 5:
    logger.warning("[tool_executor] DAG depth %d > 5 — flattening", depth)
    # Flatten: removes all depends_on to make sequential
    for n in nodes:
        n["depends_on"] = []
```

**File cần sửa:**
- `src/graph/nodes/tool_executor.py`

---

### 4.10 Sửa type lệch errors reducer (dict → list)

**Spec:** `state_design.md`

**Hiện trạng:** Spec ghi `errors: Annotated[dict, accumulate_errors]`, code dùng `Annotated[list, accumulate_errors]`.

**Sửa spec** (code đúng, spec sai — list mới đúng cho accumulate):
- Sửa `state_design.md` dòng "`errors: Annotated[dict, accumulate_errors]`" → `Annotated[list, accumulate_errors]`

**File cần sửa:**
- `docs/design/state_design.md`

---

## Thứ tự triển khai Phase 4

```
Phase 4:
  4.8 → reflection.py          (sửa 1 dòng, nhanh nhất)
  4.10 → state_design.md        (sửa doc, không ảnh hưởng code)

  4.6 → task_graph_builder.py   (thêm RepairLayer — module mới)
  4.4 → tool_executor.py        (thêm helpers — mở rộng hàm có sẵn)
  4.5 → tool_executor.py        (conditional branching)
  4.9 → tool_executor.py        (DAG depth check)

  4.2 → tool_executor.py        (tích hợp cache — quan trọng)

  4.1 → main_graph.py + edges.py + hallucination_guard.py (wire gates)
  4.3 → main_graph.py           (wire confirmation_node)

  4.7 → main.py + các node     (observability metrics — cuối cùng)
```

## Tổng kết tất cả Phase

| Phase | Mục tiêu | Modules chính | Trạng thái |
|-------|---------|---------------|-----------|
| 0 | Nền tảng (ToolRegistry, State, Prompts, Config) | registry.py, state.py, prompt.py, service_config.py | ✅ |
| 1 | Core Architecture (Planner + DAG + Reflection) | intent_parser, TGB, executor, reflection, edges, main_graph | ✅ |
| 2 | Response & Safety (Verifier + Hallucination + Gates) | response_verifier, hallucination_guard, fallback_generator, 5 gates | ✅ |
| 3 | Integration (Cache + Rate limiter + API) | cache_manager, redis_store, rate_limiter, main.py | ✅ |
| 4 | Fix gaps (Wire gates + Cache integration + Helpers + ...) | tool_executor, main_graph, edges, hallucination_guard, task_graph_builder | ✅ |

> **Ghi chú:** flow1b (pgvector) đã được gỡ khỏi spec theo yêu cầu. RedisRateLimiter đã có sẵn trong `rate_limiter.py`.
