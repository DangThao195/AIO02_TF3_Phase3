# Resource Limits & Production Guardrails

> **Phase 3 — Integration & Production** | *Enforced in: `graph/nodes/tool_executor.py`, `llm/llm.py`, `guardrails/`*

## Hard Limits

| Limit | Value | Enforced At | Action When Exceeded |
|---|---|---|---|
| Max tool calls / request | **8 nodes** | Tool Executor (trước execute) | Trim nodes confidence thấp nhất |
| Max DAG depth | **5 levels** | Tool Executor (validation) | Flatten dependency chain |
| Max parallel nodes / batch | **4 nodes** | `asyncio.gather` batching | Split into batches of 4 |
| Max replan / request | **1 time** | `graph/nodes/reflection.py` | Force pass after 1 replan |
| Max conversation history | **6 turns** or **2000 tokens** | `SessionStore` | Sliding window |
| Planner memory size | **20 KB** / session | `state.planner_memory` | Chỉ lưu fields cố định |
| Search results | Top **20** | Search tool | Limit trong gRPC query |
| Recommendation results | Top **5** | Recommend tool | Limit trong gRPC query |
| Review results | Top **10** | Review tool | Limit trong gRPC query |
| Max response length | **1200 tokens** (~900 chữ) | Response Verifier | Truncate / template |

## Timeouts

| Component | Timeout | Fallback |
|---|---|---|
| TGB (LLM) | **5s** | Plan rỗng → template response |
| Response Verifier (LLM) | **4s** | Template fallback |
| Semantic Gate (Nova Lite) | **2s** | `DEFAULT_DECISION` |
| Default tool (gRPC) | **2s** | Retry → error |
| Shipping (REST) | **3s** | Retry → error |
| Recommendation (gRPC) | **2s** | Retry → error |
| Search (gRPC) | **2s** | Retry → error |
| P95 end-to-end | **< 5s** | Template response ngay, background nếu cần |

## Retry Strategy

| Tool Type | Max Retries | Backoff | Notes |
|---|---|---|---|
| Read tools | **2** | 0.5s, 1s exponential | search, product, review, recommend, currency, cart, shipping |
| Write tools (add_to_cart) | **1** | 0.5s | Tránh duplicate |
| Checkout | **0** | — | Fail → báo user, không retry mù |

## LLM Timeout Implementation

```python
# llm/llm.py
async def llm_call(prompt: str, timeout: float = 3.0, **kwargs) -> str:
    try:
        result = await asyncio.wait_for(
            _bedrock_client.invoke_model(body=...),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.warning(f"[LLM] Timeout after {timeout}s")
        raise
```

## Rate Limiter (L1)

**File:** `guardrails/rate_limiter.py` — giữ nguyên v2.

| Giới hạn | Value |
|---|---|
| Requests/minute/user | **10** |
| Requests/day/user | **200** |
| Estimated tokens/day/user | **50,000** |

**Lưu ý:** Mặc định chạy global limiter qua Redis (sorted set); fallback in-memory per-pod khi Redis unavailable. Chi tiết: `cache_design.md` Global Rate Limiter.

## Validation Flow per Tool Call (L3)

```
Executor → validate_tool_call(tool_name, args, user_id):
  1. Tool name trong ToolRegistry.allow_list?
  2. user_id == args.user_id (nếu có)?
  3. args bounds hợp lệ (quantity <= 99, min_price >= 0)?
  4. Tool không thuộc DENIED_ACTIONS?
  → Nếu fail: ghi error, không execute
```

## Implementation Checklist

- [ ] Max tool calls check trong `tool_executor.py` — trim nodes trước execute
- [ ] Max DAG depth check — flatten chain
- [ ] Max parallel batching — `asyncio.gather` batch size 4
- [ ] Replan limit trong `graph/nodes/reflection.py` — `replan_count >= 1` → force pass
- [ ] LLM timeout — `asyncio.wait_for` trong `llm.py`
- [ ] Tool timeout — per-tool config trong retry config
- [ ] P95 < 5s — monitoring + template fallback
- [x] Rate limiter global (Redis sorted set) + fallback per-pod — `cache_design.md` Global Rate Limiter
