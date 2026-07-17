# API Server Design

> **Phase 3 — Integration & Production** | *File: `main.py`*

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Send message → get reply |
| `POST` | `/api/confirm` | Confirm pending write action |
| `GET` | `/health` | Health check |
| `GET` | `/` | Server info |
| `GET` | `/chatbot` | Chatbot HTML UI |

## Request/Response Schemas

### `POST /api/chat`

**Request:**
```json
{
  "message": "find telescopes under $200",
  "session_id": "550e8400-e29b-...",
  "user_id": "user_abc123"
}
```

**Response (ok):**
```json
{
  "status": "ok",
  "reply": "Tôi tìm thấy 2 sản phẩm: Telescope XYZ ($199.99), ...",
  "session_id": "550e8400-e29b-...",
  "steps": [
    {"action": "Phân loại ý định", "status": "ok", "detail": "", "duration_ms": 2},
    {"action": "Công cụ: search_products_v2", "status": "ok", "detail": "2 results", "duration_ms": 450}
  ]
}
```

**Response (pending — write action needs confirm):**
```json
{
  "status": "pending",
  "reply": "Vui lòng xác nhận: thêm 2 Telescope XYZ vào giỏ hàng.",
  "token": "eyJ...",
  "session_id": "550e8400-e29b-..."
}
```

**Response (error — guardrail blocked):**
```json
{
  "status": "error",
  "reply": "Yêu cầu chứa nội dung không phù hợp.",
  "session_id": "550e8400-e29b-..."
}
```

### `POST /api/confirm`

**Request:**
```json
{
  "session_id": "550e8400-e29b-...",
  "token": "eyJ..."
}
```

**Response:**
```json
{
  "status": "ok",
  "reply": "✅ Đã thêm 2 Telescope XYZ vào giỏ hàng!"
}
```

**Response (error):**
```json
{
  "status": "error",
  "reply": "Token không hợp lệ hoặc đã hết hạn."
}
```

### `GET /health`
```json
{"status": "ok", "service": "shopping-copilot"}
```

### `GET /`
```json
{
  "service": "Shopping Copilot API",
  "version": "1.0.0",
  "team": "AIO02 — TF3",
  "endpoints": {
    "chat": "POST /api/chat",
    "confirm": "POST /api/confirm",
    "health": "GET /health"
  }
}
```

## Graph Invocation Flow

### `POST /api/chat`
```python
graph = build_graph()
config = {"configurable": {"thread_id": session_id}}
result = await graph.ainvoke({
    "messages": [HumanMessage(content=req.message)],
    "session_id": req.session_id,
    "user_id": req.user_id,
    "trace_id": str(uuid.uuid4()),
}, config)

# 1. Check guardrail violations → error
if result.guardrail_violations:
    return ChatResponse(status="error", reply=violation.detail, ...)

# 2. Check interrupt (write confirm pending)
if result.__interrupt__:
    pending = interrupt_value.pending_action
    return ChatResponse(status="pending", reply=pending.message,
                        token=pending.token, ...)

# 3. Normal response
return ChatResponse(status="ok", reply=result.final_answer, ...)
```

### `POST /api/confirm`
```python
# 1. Verify HMAC token
is_valid, action_data = verify_confirmation_token(req.token)
if not is_valid:
    return ConfirmResponse(status="error", reply="Token không hợp lệ hoặc đã hết hạn.")

# 2. Resume graph from checkpoint
result = await graph.ainvoke(
    Command(resume={"confirmed": True}),
    config={"configurable": {"thread_id": req.session_id}}
)
return ConfirmResponse(status="ok", reply=result.get("final_answer"))
```

## Steps Tracking

`_build_steps(state)` đọc `node_durations` + `errors` + `tool_results` → trả về list step. Mỗi step có:

| Field | Type | Source |
|---|---|---|
| `action` | string | `_STEP_LABELS` map |
| `status` | `ok`/`error`/`block`/`pending` | errors + violations |
| `detail` | string | Error message / tool result preview |
| `duration_ms` | int | `node_durations[node_key]` |

## Error Handling

| Case | HTTP Status | Response |
|---|---|---|
| Graph execution error | 200 | `{status:"error", reply:"Lỗi hệ thống: ..."}` |
| Guardrail violation | 200 | `{status:"error", reply:"Yêu cầu bị từ chối."}` |
| Invalid confirm token | 200 | `{status:"error", reply:"Token không hợp lệ..."}` |
| L6 Fallback (never-crash) | 200 | Luôn trả friendly message |
| Internal server error | 500 | `{"detail": "Internal Server Error"}` |

## Configuration

| Env | Default | Description |
|---|---|---|
| `PORT` | `8001` | Server port |
| `MOCK_EKS` | `false` | Mock EKS gRPC services |
