# AI API Contract - AIE2 Shopping Copilot

<!-- Owner: AIO02 | Signed by: AI Lead + CDO Leads | Date: 2026-07-14 -->

## Mục đích

Đặc tả các endpoint mà **AIE cung cấp** để CDO cấu hình routing (Ingress/ALB) và tích hợp vào hệ thống TechX Corp.

---

## Image

| Attribute | Value |
|---|---|
| **ECR Image** | `<ACCOUNT>.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:1.0-shopping-copilot` |
| **Port** | `8001` |
| **Health check** | `GET /chatbot` → HTTP 200 |

---

## Endpoints

### `POST /api/chat`
Nhận câu hỏi người dùng, trả về phản hồi từ AI Copilot.

**Request:**
```json
{ "message": "string", "session_id": "uuid", "user_id": "string" }
```

**Response thường (status = ok):**
```json
{ "status": "ok", "reply": "string (markdown)", "session_id": "uuid", "token": null }
```

**Response chờ xác nhận (status = pending — khi agent sắp ghi giỏ hàng):**
```json
{ "status": "pending", "reply": "string", "session_id": "uuid", "token": "jwt" }
```

---

### `POST /api/confirm`
Người dùng xác nhận hành động ghi (thêm vào giỏ hàng).

**Request:**
```json
{ "session_id": "uuid", "token": "jwt" }
```

**Response:**
```json
{ "status": "ok", "reply": "✅ Đã thêm vào giỏ hàng thành công!" }
```

---

### `GET /api/cart?user_id=<id>`
Lấy danh sách sản phẩm trong giỏ hàng của user (dùng cho sidebar UI).

**Response:**
```json
{ "user_id": "string", "items": [{ "product_id": "string", "name": "string", "price": "string", "quantity": 1 }] }
```

---

## Rate Limiting

AIE tự áp dụng giới hạn **10 requests/phút/user**. CDO không cần cấu hình thêm tại API Gateway.

## Error codes

| Code | Ý nghĩa |
|---|---|
| `200` | Thành công |
| `429` | Vượt rate limit — client nên hiển thị thông báo thử lại |
| `500` | Lỗi nội bộ AIE — CDO alert theo metric `copilot_request_latency_seconds{status_code="500"}` |
