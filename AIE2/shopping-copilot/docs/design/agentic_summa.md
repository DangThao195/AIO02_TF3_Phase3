# Shopping Copilot — Agentic Design Tóm tắt

> **Bản tóm tắt** — Đọc để có cái nhìn tổng quan.  
> **Phải đọc bản đầy đủ** [`agentic_design.md`](agentic_design.md) nếu muốn implement, debug, hoặc hiểu chi tiết từng module.

---

## Kiến trúc tổng thể

**2-Layer Planner + DAG-based Tool Executor + Reflection + Template-First Response + Semantic Decision Gate Layer (Nova Lite)**

```
User → [Guardrail L1-L2] → Intent Parser (rule → LLM fallback)
                         → Task Graph Builder (LLM chọn tool + nối DAG)
                         → Tool Executor (DAG runner, parallel, conditional)
                         → Reflection (pass / partial replan)
                         → Response Verifier (template-first / LLM)
                         → HallucinationGuard + Semantic Gate
                         → Answer Generator → User
```

### Lớp Planner 2 tầng

| Layer | Chức năng | Output |
|---|---|---|
| **Intent Parser** | Rule-based regex (fast path) → LLM fallback nếu không rõ | `{intent, entities, confidence}` |
| **Task Graph Builder** | LLM chọn tool từ ToolRegistry + nối edge dependency | `DAGPlan {nodes, edges, confidence}` |

Không như v2 dùng workflow cố định: DAG cho phép chạy song song node độc lập, conditional branching, và partial replan khi node lỗi.

### DAG Executor & Reflection

- Chạy DAG theo thứ tự topological, node không dependency chạy song song qua `asyncio.gather`
- Resolve variable references tại runtime (`$steps[node].path`, `$first()`, `$safe_index()`, `$exists()`)
- Conditional branching: dừng/hỏi user/tiếp tục dựa trên tool result
- Retry per-tool (read: 2 lần, write: 0-1 lần, checkout: 0)
- Reflection kiểm tra kết quả → **partial replan** (chỉ sửa node lỗi, không restart full DAG)

### Template-First Response

~60% request (cart, shipping, currency, reviews, search ≤3 items) dùng **template trực tiếp từ tool output** — không gọi LLM. LLM chỉ gọi khi cần summarize/compare/explain (complexity > 0.5).

### HallucinationGuard & Semantic Gate

| Lớp | Cost | Cơ chế |
|---|---|---|
| **HallucinationGuard** (rule-based) | $0 | Regex check: price, entity, count, score, action, semantic attribute — groundedness ≥80% |
| **Semantic Decision Gate** (Nova Lite) | ~$0.00002/request | Binary Yes/No cho hallucination ngữ nghĩa, plan validity, replan decision — ép output tối giản, temperature=0.0 |

### 6 Guardrail Layers

| Layer | Bảo vệ | Vị trí |
|---|---|---|
| L1: Rate Limiter | Spam | `input_guard` |
| L2a: Regex Input | Prompt injection | `input_guard` |
| L2b: Bedrock Guardrail | Semantic threat (optional) | `input_guard` |
| L3: Tool Validator | Allow-list, bounds, user isolation | `tool_executor` |
| L4: Confirmation Gate | Write action (HMAC token) | `tool_executor` |
| L5: Output Filter | PII & system info redaction | `answer_generator` |
| L6: Fallback | Never-crash wrapper | Wraps graph |

---

## State & Cache

**State** (`ShoppingState`): messages, plan (DAG), intent + entities, tool_results, planner_memory (ngắn hạn), groundedness_score, gate_decisions, reflection_result, confirmation fields.

**Cache** (Redis, 3 logical DBs): Planner cache (DB0, 5p), Tool cache (DB1: search/product/currency/shipping/recommend, 10-60p), Session cache (DB2, 30p).

---

## Resource Limits

- Max 8 tool calls / request
- Max DAG depth 5 levels
- Max 4 parallel nodes / batch
- Max 1 replan / request
- P95 latency < 5s
- LLM timeout: TGB 3s, Verifier 4s, Gate 2s

---

## Operating Costs

| Path | Cost/request | Latency |
|---|---|---|
| Template (cart/shipping/currency/review) | ~$0.00001 | ~300ms |
| Complex search (>3 items) | ~$0.00004 | ~1000ms |
| Multi-tool + gates typical | ~$0.00008 | ~1500ms |
| Worst case (replan + gates) | ~$0.00015 | ~2500ms |

---

> ⚠️ **Cảnh báo**: Bản tóm tắt này chỉ liệt kê ý chính.  
> **Để implement bất kỳ module nào (nodes, gates, tools, guardrails, cache, state, prompt), phải đọc bản đầy đủ** tại [`agentic_design.md`](agentic_design.md) — nơi có đầy đủ: interface contract, JSON schema, thuật toán từng bước, template set, edge routing, test cases, và trade-off phân tích.

---

*Tóm tắt từ agentic_design.md v3.2 — AIO02 TF3, 2026-07-17*
