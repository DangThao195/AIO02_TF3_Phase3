# Response Verifier Design — Template-First Strategy

> **Phase 2 — Response & Safety** | *File: `graph/nodes/response_verifier.py`*

## Interface

```python
async def response_verifier_node(state: ShoppingState) -> dict:
    """
    Input:  state.tool_results (dict[node_id, normalized_result])
            state.messages[-1] (user query)
            state.entities
            state.complexity_score (optional, will compute if absent)
    Output: {final_answer, complexity_score, node_durations}
    """
```

## Strategy Decision Tree

```
tool_results keys?
  │
  ├── Chỉ get_cart_tool ───────────────► template "cart" / "cart_empty"   [deterministic]
  ├── Chỉ get_shipping_quote_tool ─────► template "shipping"              [deterministic]
  ├── Chỉ convert_currency_tool ───────► template "currency"              [deterministic]
  ├── Chỉ get_product_reviews_tool ────► template "reviews" / "reviews_none" [deterministic]
  ├── Chỉ search_products_v2
  │     ├── total == 0 ────────────────► template "search_none"
  │     ├── total ≤ 3 ─────────────────► template "search_single"
  │     └── total > 3 ─────────────────► LLM summarize
  ├── Multi-tool (review + recommend) ─► complexity > 0.5 → LLM | ≤ 0.5 → template ghép
  ├── Có pending_action ───────────────► template "confirm"
  └── Không có tool_results ───────────► giữ nguyên final_answer từ guardrail
```

## Complexity Scoring

| Factor | Condition | Points |
|---|---|---|
| Query length | >20 từ: +0.2; >10 từ: +0.1 | 0–0.2 |
| Số tool gọi | Mỗi tool +0.1, max +0.3 | 0–0.3 |
| Result size | >10 items: +0.2; >5 items: +0.1 | 0–0.2 |
| Write action | Có pending action | +0.1 |

Clamp tối đa 1.0. Nếu `complexity ≤ 0.5` → template path; `> 0.5` → LLM path.

### Temperature Selection
| complexity | temperature |
|---|---|
| < 0.2 | 0.1 |
| < 0.5 | 0.3 |
| < 0.8 | 0.4 |
| ≥ 0.8 | 0.6 |

## Template Set

Full templates in `TEMPLATES` dict (xem agentic_design.md §10). Mỗi loại có 2–3 variants, **random chọn** để tránh robotic.

### Template Variables
| Template | Variables |
|---|---|
| `cart` | `{count}`, `{items}`, `{total}` |
| `cart_empty` | — |
| `shipping` | `{destination}`, `{cost}`, `{days}`, `{provider}` |
| `currency` | `{amount}`, `{from}`, `{converted}`, `{to}`, `{rate}` |
| `reviews` | `{avg}`, `{total}`, `{top_review}` |
| `reviews_none` | — |
| `confirm` | `{quantity}`, `{product_name}` |
| `search_single` | `{count}`, `{product_list}` |
| `search_none` | — |

### Product List Formatting
```python
def format_product_list(products: list[dict], max_count: int = 5) -> str:
    """Format: 'Tent XYZ ($99.99), Stove ABC ($49.99) và 3 sản phẩm khác'"""
    items = [f"{p['name']} ({p['price']})" for p in products[:max_count]]
    if len(products) > max_count:
        items.append(f"và {len(products) - max_count} sản phẩm khác")
    return ", ".join(items)
```

## LLM Path

### Verifier Prompt
```
Tool results: {tool_results_text}

Quy tắc:
1. CHỈ dùng thông tin trong tool results — KHÔNG thêm chi tiết không có.
2. Giữ nguyên giá cả ($99.99), tên sản phẩm, số lượng.
3. KHÔNG markdown, emoji, technical terms.
4. Xưng hô "tôi" — "bạn", lịch sự, gần gũi.
5. Trả lời bằng tiếng Việt.

Khách hàng hỏi: {user_query}
Trả lời:
```
- `temperature` động theo complexity
- `max_tokens=1200`
- timeout 4s

### `tool_results_text` Format
```python
def format_tool_results(results: dict) -> str:
    lines = []
    for node_id, data in results.items():
        tool_name = data.get("_tool", node_id)
        lines.append(f"[{tool_name}]")
        if "products" in data:
            for p in data["products"]:
                lines.append(f"  - {p['name']} | {p['price']} | {p.get('description','')}")
        elif "items" in data:
            for item in data["items"]:
                lines.append(f"  - {item['name']} x{item['quantity']} | {item['price']}")
        elif "converted_amount" in data:
            lines.append(f"  {data['original_amount']} {data['from']} → {data['converted_amount']} {data['to']} (rate: {data['rate']})")
        else:
            lines.append(f"  {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines)
```

## Skip Conditions

| Condition | Action |
|---|---|
| Không có tool_results | Giữ nguyên `final_answer` (guardrail message) |
| Có guardrail violations | Giữ nguyên message guardrail |
| LLM unavailable/timeout | Dùng raw tool results text |
| Write tool pending | Giữ nguyên confirm message |
| FallbackGenerator đã chạy | Không chạy — answer đã grounded |

## Graph Edge

```
tool_executor → RESPONSE_VERIFIER → hallucination_guard → ...
```
