# HallucinationGuard & FallbackGenerator Design

> **Phase 2 — Response & Safety** | *Files: `graph/nodes/hallucination_guard.py`, `graph/nodes/fallback_generator.py`*

## HallucinationGuard

**File:** `graph/nodes/hallucination_guard.py`

### Interface
```python
async def hallucination_guard_node(state: ShoppingState) -> dict:
    """
    Input:  state.final_answer (từ ResponseVerifier, LLM path only)
            state.tool_results
            state.pending_action
    Output: {groundedness_score, hallucination_detected,
             fallback_used, node_durations}
    """
```

### Core Rule: Chỉ chạy khi `complexity_score > 0.5`
Template path (complexity ≤ 0.5) luôn grounded 100% → auto PASS, bỏ qua check.

### Groundedness Score Algorithm
Bắt đầu từ 1.0, mỗi violation trừ penalty. Clamp [0, 1].

| # | Check | Mechanism | Penalty |
|---|---|---|---|
| 1 | **Price** | Regex `\$\d+(?:\.\d{2})?` → mỗi price exact match với tool_results | -0.15 each |
| 2 | **Entity** | Noun phrase (token viết hoa + bigram) → check trong known_products/categories | -0.40 |
| 3 | **Entity (zero-result)** | Nếu search total=0 → mọi noun phrase violation | -0.50 |
| 4 | **Count** | Regex `(\d+)\s*(sản phẩm\|kết quả\|đánh giá\|món)` → exact number match | -0.15 |
| 5 | **Score** | Regex `(\d+\.?\d*)\s*/?\s*5` → match ±0.1 tolerance | -0.15 |
| 6 | **Action confirm** | Regex `(đã thêm\|đã xoá\|đã cập nhật)` → chỉ nếu confirmed | -0.15 |
| 7 | **Semantic attribute** | Regex `(có\|được\|sử dụng\|phù hợp\|chất liệu\|tính năng\|màu\|công dụng)` → claim phải trong description/name | -0.25 |

### Entity Extraction Strategies
```
1. Token viết hoa: "Telescope", "Camping Stove" → check in known set
2. Bigram trong known set: "Camping Stove" → check in answer
3. Category từ known set: "Outdoor", "Camping" → check in answer
```

Known set build từ `tool_results`: gom all `products[].name`, `products[].categories`, `items[].name`.

### Decision
```
groundedness_score >= 0.8 → PASS → hallucination_detected = False
groundedness_score < 0.8  → FAIL → hallucination_detected = True, final_answer = None
```

### Edge Cases
| Condition | Behavior |
|---|---|
| `complexity ≤ 0.5` (template) | Auto PASS, score=1.0 |
| Không có tool_results | Auto PASS, score=1.0 |
| Answer trống | Auto PASS |
| known set rỗng + total=0 | Mọi noun phrase → entity violation (-0.50) |
| known set rỗng + total>0 | No entity violations (không có đối chiếu) |
| Guardrail violation trước | Giữ nguyên guardrail message |

---

## FallbackGenerator

**File:** `graph/nodes/fallback_generator.py`

### Interface
```python
async def fallback_generator_node(state: ShoppingState) -> dict:
    """
    Input:  state.tool_results
            state.pending_action
            state.hallucination_detected (must be True)
    Output: {final_answer, fallback_used, node_durations}
    """
```

### Strategy
1. Xác định tool types từ `tool_results` keys
2. Nếu `pending_action.status == "pending"` → template confirm
3. Nếu single tool → chọn template tương ứng
4. Nếu multi tool → ghép template các single tool

### Template Selection Logic
```python
def select_fallback_template(tool_types: list[str], data: dict) -> str:
    # Priority: confirm > single tool > multi tool ghép
    if data.get("pending_action"):
        return render_template("confirm", data)

    if len(tool_types) == 1:
        return render_single_tool_template(tool_types[0], data)

    parts = []
    for t in tool_types:
        parts.append(render_single_tool_template(t, data))
    return " ".join(parts)
```

### Single Tool Templates (3–4 variants each, random choice)
| Tool type | Variant examples |
|---|---|
| search (0 results) | "Tôi không tìm thấy sản phẩm nào phù hợp." / "Rất tiếc, không có sản phẩm nào khớp yêu cầu." |
| search (≤5 items) | "Tôi tìm thấy {n} sản phẩm: {list}." |
| search (>5 items) | "Tôi tìm thấy {n} sản phẩm, trong đó có {list}. Bạn muốn xem thêm?" |
| cart (empty) | "Giỏ hàng của bạn hiện đang trống." |
| cart (has items) | "Giỏ hàng có {count} món: {items}. Tổng cộng {total}." |
| reviews (none) | "Sản phẩm này chưa có đánh giá nào." |
| reviews | "Sản phẩm được đánh giá {avg}/5 sao. {top_review}" |
| recommend | "Gợi ý dành cho bạn: {products}." |
| currency | "{amount} {from} tương đương {converted} {to} (tỷ giá {rate})." |
| shipping | "Phí vận chuyển ước tính {cost}, giao trong {days} ngày." |
| confirm | "Vui lòng xác nhận: thêm {quantity} {product_name} vào giỏ hàng." |

### Graph Edge
```
response_verifier → HALLUCINATION_GUARD
                       │ pass (≥ 0.8)
                       ▼
                  answer_generator → END
                       │ fail (< 0.8)
                       ▼
                  FALLBACK_GENERATOR → answer_generator → END

Route function: state.hallucination_detected → "fail" | "pass"
```

### Cost
| Component | Cost | Latency |
|---|---|---|
| HallucinationGuard | $0 (rule-based regex) | < 3ms |
| FallbackGenerator | $0 (template render) | < 1ms |
