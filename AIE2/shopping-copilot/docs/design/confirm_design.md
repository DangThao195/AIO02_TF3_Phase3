# Write + Confirm Flow Design

> **Phase 3 — Integration & Production** | *Files: `guardrails/confirmation.py`, `graph/nodes/confirmation.py`, `main.py`*

## Architecture

```
User: "add 2 telescopes to my cart"
  → TGB: DAG [search → add_to_cart]
  → Executor: search OK → add_to_cart gọi request_confirmation()
       → {status:"PENDING", token:"eyJ...", message:"Xác nhận thêm 2x telescope?"}
       → PAUSE graph → Interrupt → trả token về API
  → API: trả về {status:"pending", reply, token, session_id}
  → User click Confirm → POST /api/confirm {session_id, token}
  → main.py: verify token → graph.ainvoke(Command(resume={"confirmed": True}))
  → Executor resume: gọi AddItem gRPC → response_verifier → END
```

## Confirmation Token (HMAC Stateless)

Giữ nguyên implementation hiện tại ở `guardrails/confirmation.py`:

```
Token = base64(payload_json) + "." + HMAC-SHA256(payload, SECRET_KEY)
Payload: {user_id, action, params, exp (Unix + 300s)}
```

### Actions
| Action | Classification | Behavior |
|---|---|---|
| `AddItem` | `CONFIRM_REQUIRED` | Tạo token, PAUSE graph |
| `EmptyCart` | `DENIED` | Từ chối ngay, không tạo token |
| `PlaceOrder` | `DENIED` | Từ chối ngay |
| `Charge` | `DENIED` | Từ chối ngay |
| Other (read actions) | `APPROVED` | Chạy ngay, không confirm |

## Confirmation Node (Graph Node)

**File:** `graph/nodes/confirmation.py`

### Interface
```python
async def confirmation_node(state: ShoppingState) -> dict:
    """
    Input:  state.pending_action (token, action, params)
            state.confirmed (bool, resume signal)
    Output: {tool_results, pending_action (cleared if confirmed),
             confirmed (reset to False), node_durations}
    """
```

### Flow
```
1. Nếu state.confirmed == True:
   - Đọc action từ state.pending_action
   - Gọi gRPC AddItem thật đến CartService
   - Xoá pending_action
   - Ghi kết quả vào tool_results
   - Set confirmed = False (reset)
   
2. Nếu state.pending_action tồn tại và confirmed == False:
   - Graph đang ở PAUSE state → chờ user confirm
   - (Không làm gì, LangGraph tự duy trì checkpoint)

3. Nếu không có pending_action:
   - PASS (không có gì cần confirm)
```

### Graph Integration
```
tool_executor → đọc tool result
  ├── status == "pending" → set pending_action → PAUSE (interrupt)
  └── status != "pending" → tiếp tục DAG

Sau khi resume:
  confirmation_node (kiểm tra confirmed flag)
    → nếu confirmed → execute action → ghi kết quả → tiếp tục
    → nếu không → return pending_action
```

## API Integration

### `POST /api/chat`
```
if result.get("__interrupt__"):
    pending = interrupt_value.pending_action
    return ChatResponse(status="pending", reply=pending.message,
                        token=pending.token, session_id)
else:
    return ChatResponse(status="ok", reply=result.final_answer, session_id)
```

### `POST /api/confirm`
```python
# 1. Verify token
is_valid, action_data = verify_confirmation_token(req.token)
if not is_valid:
    return ConfirmResponse(status="error", reply="Token không hợp lệ hoặc đã hết hạn.")

# 2. Resume graph
result = await graph.ainvoke(Command(resume={"confirmed": True}), config)
return ConfirmResponse(status="ok", reply=result.get("final_answer"))
```

## State Fields
| Field | Type | Purpose |
|---|---|---|
| `pending_action` | `Optional[dict]` | `{token, action, params, message}` |
| `confirmed` | `bool` | Resume signal từ `/api/confirm` |

## V2 → V3.2 Changes
- V2: Confirmation dùng `SessionStore.pending_confirmation` (JSON file persist) + `LangGraph.interrupt()`
- **V3.2: Giữ nguyên** — cơ chế HMAC + interrupt đã hoạt động. Chỉ đảm bảo compatibility với DAG Executor mới (read `pending_action` từ state, set khi write tool trả pending, resume đúng checkpoint).
