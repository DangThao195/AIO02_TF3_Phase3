# AI API Contract - Task force 02 (Phase 3)
**Dự án:** Shopping Copilot (AIE2)

<!-- Owner: Nhóm AI 02
     Signed by: AI Lead + CDO Leads
     Date signed: 2026-07-14
     🔒 FREEZE - no change without formal change request -->

## 1. Mục đích

Định nghĩa các **API Endpoints** mà Shopping Copilot (AIE) cung cấp cho ứng dụng Frontend (hoặc API Gateway của CDO tiêu thụ) để tương tác với người dùng. Hợp đồng này đóng vai trò là cầu nối giao tiếp giữa Client và AI Engine chạy trong EKS.

---

## 2. Versioning & Môi trường

* **Current version**: `v1.0` (trong path `/api/`)
* **Base URL nội bộ**: `http://shopping-copilot.aie-prod.svc.cluster.local:8001`
* **Breaking changes**: Khi thay đổi cấu trúc request/response bắt buộc, phiên bản mới sẽ được cập nhật lên `/api/v2/`. Phiên bản cũ sẽ được duy trì chạy song song tối thiểu 15 ngày để CDO cập nhật.

---

## 3. Rate Limiting (Giới hạn tần suất)

Để bảo vệ chi phí gọi AWS Bedrock, API Gateway sẽ áp dụng chính sách:
* **Per User (Dựa trên User ID):** Tối đa 10 requests/phút.
* **Global Rate Limit:** Tối đa 100 requests/phút trên toàn cụm.
* **Response khi vượt ngưỡng:** Trả về mã lỗi HTTP `429 Too Many Requests`.

---

## 4. Đặc tả chi tiết các Endpoints

### 4.1 Endpoint 1: `POST /api/chat`
**Mục đích:** Gửi câu hỏi của người dùng và nhận câu trả lời từ AI Copilot (ReAct Agent kết nối microservices).

#### Request Headers:
| Header | Type | Required | Description |
|---|---|---|---|
| `Content-Type` | string | ✓ | Phải là `application/json` |
| `X-Correlation-Id` | string (UUID) | optional | Mã định danh luồng trace OpenTelemetry |

#### Request Body:
| Field | Type | Required | Description |
|---|---|---|---|
| `message` | string | ✓ | Câu hỏi của người dùng gửi cho chatbot |
| `session_id` | string (UUID) | ✓ | ID phiên hội thoại để lưu trữ history |
| `user_id` | string | ✓ | ID của user (dùng để lưu giỏ hàng/thông tin cá nhân) |

*Request Example:*
```json
{
  "message": "Tìm kiếm kính thiên văn dưới 200 đô và thêm sản phẩm 1 vào giỏ",
  "session_id": "8be50a08-e08a-4c8a-a760-4bf961f018e8",
  "user_id": "test_user_001"
}
```

#### Response Body:
| Field | Type | Description |
|---|---|---|
| `status` | string | Trạng thái phản hồi (`ok` hoặc `pending` nếu chờ xác nhận ghi) |
| `reply` | string (Markdown) | Câu trả lời của chatbot (đã qua định dạng đẹp) |
| `session_id` | string | ID phiên hội thoại |
| `token` | string (JWT) | Token xác nhận hành động giao dịch (chỉ có khi status = pending) |
| `steps` | array | Danh sách vết xử lý của Agent (RateLimiter, Guardrail, Tool Calls,...) |

*Response Example (Trường hợp tìm kiếm thành công - status = ok):*
```json
{
  "status": "ok",
  "reply": "### National Park Foundation Explorascope\n- **Giá**: $101\n- **Mô tả**: Kính thiên văn alt-azimuth hoàn hảo cho người mới bắt đầu.",
  "session_id": "8be50a08-e08a-4c8a-a760-4bf961f018e8",
  "token": null,
  "steps": [
    {
      "action": "RateLimiter",
      "status": "PASS",
      "duration_ms": 1
    },
    {
      "action": "search_products_v2",
      "status": "PASS",
      "duration_ms": 450
    }
  ]
}
```

*Response Example (Trường hợp cần xác nhận thêm vào giỏ - status = pending):*
```json
{
  "status": "pending",
  "reply": "Vui lòng xác nhận thêm 1 sản phẩm 'OLJCESPC7Z' vào giỏ hàng.",
  "session_id": "8be50a08-e08a-4c8a-a760-4bf961f018e8",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "steps": []
}
```

---

### 4.2 Endpoint 2: `POST /api/confirm`
**Mục đích:** Người dùng xác nhận thực hiện hành động ghi (như thêm sản phẩm vào giỏ hàng).

#### Request Body:
| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string (UUID) | ✓ | ID phiên hội thoại hiện tại |
| `token` | string | ✓ | Token JWT chứa thông tin hành động chờ xác nhận |

*Request Example:*
```json
{
  "session_id": "8be50a08-e08a-4c8a-a760-4bf961f018e8",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

#### Response Body:
| Field | Type | Description |
|---|---|---|
| `status` | string | `ok` nếu ghi thành công, `error` nếu thất bại |
| `reply` | string | Thông báo kết quả cho người dùng hiển thị trên UI |

*Response Example:*
```json
{
  "status": "ok",
  "reply": "✅ Đã thêm vào giỏ hàng thành công!"
}
```

---

## 5. SLA Mục Tiêu (Service Level Agreements)

| Metric | Target | Description |
|---|---|---|
| **P99 Latency (Không LLM)** | < 100 ms | Phản hồi từ Cache hoặc các tĩnh endpoint |
| **P99 Latency (Có LLM & Tool)**| < 3000 ms | Bao gồm thời gian gọi Bedrock Converse + gọi gRPC |
| **Availability (Độ sẵn sàng)** | > 99.0% | Thời gian uptime của dịch vụ trong tháng |
| **Error Rate (Tỷ lệ lỗi HTTP 5xx)**| < 1.0% | Đảm bảo tính ổn định của Agent |
