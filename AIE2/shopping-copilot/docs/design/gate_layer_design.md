# Gate Layer Design — Semantic Decision Gates (Nova Lite)

> **Phase 2 — Response & Safety** | *Files: `graph/gates/gate_node.py`, `graph/gates/*.py`*

## Shared Gate Node Interface

**File:** `graph/gates/gate_node.py`

```python
@dataclass
class GateResult:
    decision: bool              # True = Yes, False = No
    reason: Optional[str]       # Only for high-risk gates
    latency_ms: float
    tokens: dict                # {input: int, output: int}

async def gate_node(
    question: str,
    context: str,
    want_reason: bool = False,
    timeout: float = 2.0,
) -> GateResult:
    """
    Gọi Amazon Nova Lite (amazon.nova-lite-v1:0) với binary classification.
    
    System prompt:
        "Bạn là bộ phân loại nhị phân. Chỉ trả lời đúng 1 từ: YES hoặc NO."
        (+ reason line nếu want_reason)
    
    Parameters:
        temperature = 0.0
        max_tokens = 3 (hoặc 25 nếu có reason)
    
    Parse:
        text.upper().startswith("YES") → decision = True
        text.upper().startswith("NO")  → decision = False
        dòng sau "\n" → reason
    
    Fallback:
        try: await gate_node(...)
        except (TimeoutError, BedrockError):
            return GateResult(
                decision=DEFAULT_DECISIONS[gate_name],
                reason="gate_unavailable"
            )
    """
```

## 5 Gates

### 1. `routing_gate` — Fast Path Detection
| Field | Value |
|---|---|
| Position | Trước Intent Parser |
| Trigger | L2a regex không match rõ ràng |
| Question | "Câu hỏi mua sắm này có match một pattern đơn giản (cart view, search, greeting) không?" |
| `want_reason` | False |
| Default decision | `False` (đi LLM path — an toàn) |
| Cost | ~$0.000009/call |

### 2. `plan_validity_gate` — DAG Validity Check
| Field | Value |
|---|---|
| Position | Sau TGB, trước Tool Executor |
| Trigger | `len(plan.nodes) > 1` (plan đơn bước bỏ qua) |
| Question | "DAG plan này có đủ step để trả lời intent gốc, không thiếu dependency cần thiết không?" |
| Context | `intent`, `entities`, `plan` JSON, tool names |
| `want_reason` | True |
| Default decision | `True` (plan valid — không block) |
| Cost | ~$0.000029/call |

### 3. `semantic_hallucination_gate` — Semantic Claim Check
| Field | Value |
|---|---|
| Position | Sau HallucinationGuard, chỉ khi rule-based PASS |
| Trigger | Mỗi claim còn lại sau rule-based check |
| Question | "Claim '<claim_text>' có thực sự được suy ra từ tool output này, hay LLM tự suy diễn?" |
| Context | Tool output snippet gốc |
| `want_reason` | True |
| Default decision | `False` (hallucination — dùng fallback template, an toàn) |
| Cost | ~$0.000019/claim |

**Luồng chạy:**
```
response → HallucinationGuard (rule-based, $0)
               │ pass
               ├── không còn claim nào → PASS (không gọi semantic gate)
               └── còn N claims cần kiểm tra ngữ nghĩa
                    → asyncio.gather(semantic_gate(c1), ..., semantic_gate(cN))
                         → tất cả PASS → answer giữ nguyên
                         → bất kỳ FAIL nào → semantic_hallucination_detected = True
```

### 4. `confirm_parse_gate` — NL Confirm Parse
| Field | Value |
|---|---|
| Position | `POST /api/confirm` handler |
| Trigger | User gửi reply text thay vì click nút |
| Question | "Phản hồi của user có phải là đồng ý xác nhận hành động không?" |
| Context | User reply + action description |
| `want_reason` | False |
| Default decision | `True` (thiên về confirm — UX tốt hơn) |
| Cost | ~$0.000006/call |

### 5. `replan_gate` — Replan Decision
| Field | Value |
|---|---|
| Position | Reflection node, khi có lỗi/0 kết quả |
| Trigger | Tool trả `total=0` hoặc ≥2 errors |
| Question | "Kết quả hiện tại có đạt được goal ban đầu không, hay cần lập kế hoạch lại?" |
| Context | Goal, tool_results tóm tắt, errors |
| `want_reason` | True |
| Default decision | `False` (không replan — giữ nguyên kết quả) |
| Cost | ~$0.000025/call |

### Gate Execution trong Graph
```
                                   ┌─ routing_gate (trước Planner)
                                   │
Intent Parser → TGB → plan_validity_gate (nếu multi-node)
                         │ valid
                         ▼
                  Tool Executor → Reflection
                                    │ need replan? → replan_gate
                                    │                 │ Yes → TGB (partial)
                                    │                 │ No  → ResponseVerifier
                                    ▼
                  ResponseVerifier → HallucinationGuard → semantic_hallucination_gate (per claim)
                                                              │ PASS → answer_generator
                                                              │ FAIL → fallback_generator
```

## Default Decisions (Fallback khi Gate timeout/lỗi)

| Gate | Default | Rationale |
|---|---|---|
| `routing_gate` | `False` (không phải fast path) | An toàn, đi LLM path |
| `plan_validity_gate` | `True` (plan valid) | Không block request vô cớ |
| `semantic_hallucination_gate` | `False` (hallucination detected) | Thiên về fallback, an toàn |
| `confirm_parse_gate` | `True` (confirmed) | UX: không từ chối nhầm confirm |
| `replan_gate` | `False` (không replan) | Tránh loop vô hạn |

## Cost Summary

| Gate | Input tokens | Output tokens | Cost/call | Trigger rate |
|---|---|---|---|---|
| routing_gate | ~150 | 1 | ~$0.000009 | ~20% request |
| plan_validity_gate | ~400 | ~20 | ~$0.000029 | ~40% request |
| semantic_hallucination_gate | ~250/claim | ~18 | ~$0.000019/claim | ~1-2 claims, ~15% request |
| confirm_parse_gate | ~100 | 1 | ~$0.000006 | ~5% request |
| replan_gate | ~350 | ~18 | ~$0.000025 | ~8% request |

**Typical cost per request**: **~$0.00002–0.00004** (chỉ semantic_hallucination_gate chạy trên 1-2 claim, các gate khác skip do rule đã đủ tự tin).

**Worst case**: ~$0.0001 (routing + plan_validity + 2 semantic + replan — hiếm gặp).
