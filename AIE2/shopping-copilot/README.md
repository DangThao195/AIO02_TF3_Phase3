# Shopping Copilot — TechX Corp

Trợ lý mua sắm AI cho TechX Corp. Hỗ trợ tìm kiếm sản phẩm, xem đánh giá,
thêm vào giỏ hàng, gợi ý sản phẩm và quy đổi tiền tệ.

## Yêu cầu

- Python 3.11+
- `pip install -r requirements.txt`

## Kiến trúc

```
shopping-copilot/
├── src/                 # Mã nguồn agent
│   ├── agent/           # CopilotAgent (ReAct loop)
│   ├── llm/             # LLM client (Groq)
│   ├── guardrails/      # Confirmation, rate limiter
│   ├── memory/          # Session store, cache
│   ├── protos/          # demo.proto + stubs (kết nối backend)
│   └── tools/           # 7 tools agent sử dụng
│       └── search/      # Search pipeline (multi-strategy)
├── server-test/         # Mock backend local (thay thế K8s)
│   ├── server/          # gRPC + HTTP server
│   ├── proto/           # Proto files riêng
│   └── database/        # SQLite schema + seed
├── static/              # Giao diện chatbot HTML
└── data/                # Runtime data (cache, session)
```

### 7 công cụ agent

| Công cụ | Chức năng | Backend |
|---------|-----------|---------|
| `search_products_v2` | Tìm kiếm + liệt kê danh mục | gRPC ProductCatalogService |
| `get_product_reviews_tool` | Xem đánh giá sản phẩm | gRPC ProductReviewService |
| `add_to_cart_tool` | Thêm vào giỏ hàng (cần xác nhận) | gRPC CartService |
| `get_cart_tool` | Xem giỏ hàng | gRPC CartService |
| `get_recommendations_tool` | Gợi ý sản phẩm liên quan | gRPC RecommendationService |
| `convert_currency_tool` | Quy đổi tiền tệ | gRPC CurrencyService |
| `get_shipping_quote_tool` | Xem phí vận chuyển | REST HTTP |

---

## Cách chạy

### Option A: Server-test (mock local) — khuyên dùng

Server-test mô phỏng toàn bộ backend trên local, không cần kết nối K8s.

**Bước 1: Seed database** (chỉ làm 1 lần)

```powershell
cd server-test
python scripts/seed.py
```

Kết quả: tạo file `server-test/shopping.db` với 10 sản phẩm, 50+ đánh giá.

**Bước 2: Khởi động server-test**

```powershell
cd server-test
python -m server.main
```

Server-test lắng nghe trên **7 cổng**:

| Cổng | Dịch vụ | Giao thức |
|------|---------|-----------|
| 3550 | ProductCatalogService | gRPC |
| 7070 | CartService | gRPC |
| 8081 | RecommendationService | gRPC |
| 9090 | ProductReviewService | gRPC |
| 7001 | CurrencyService | gRPC |
| 50051 | Products + ProductReviews + Accounting (legacy) | gRPC |
| 50052 | Shipping REST | HTTP |

Log thành công:

```
database ready
legacy gRPC server listening on 0.0.0.0:50051
demo gRPC service ready on 0.0.0.0:3550
demo gRPC service ready on 0.0.0.0:7070
demo gRPC service ready on 0.0.0.0:8081
demo gRPC service ready on 0.0.0.0:9090
demo gRPC service ready on 0.0.0.0:7001
HTTP shipping ready on 0.0.0.0:50052
all servers ready
```

**Bước 3: Mở terminal mới — khởi động agent**

```powershell
set USE_TEST_SERVER=true
uvicorn src.main:app --port 8001
```

`USE_TEST_SERVER=true` chuyển tất cả địa chỉ backend từ K8s sang localhost.

**Bước 4: Mở browser → giao diện chat**

Truy cập: [http://localhost:8001/chatbot](http://localhost:8001/chatbot)

Giao diện chatbot HTML có:
- Khung chat với message bubble
- Timeline các bước agent thực hiện (có animation)
- Nút xác nhận cho thao tác thêm giỏ hàng
- Session ID + nút New Chat

**Câu lệnh test nhanh:**

```
cho tôi xem kính thiên văn dưới 100 đô
có những danh mục sản phẩm nào
thêm sản phẩm OLJCESPC7Z vào giỏ hàng
giỏ hàng của tôi có gì
đánh giá về sản phẩm 66VCHSJNUP
```

---

### Option B: Kết nối server thật (K8s)

Dùng khi cần test với backend thật trên cluster EKS.

**Bước 1: Port-forward các service**

```powershell
kubectl port-forward -n techx-tf3 service/product-catalog 3550:3550
kubectl port-forward -n techx-tf3 service/cart 7070:7070
kubectl port-forward -n techx-tf3 service/recommendation 8081:8081
kubectl port-forward -n techx-tf3 service/product-reviews 9090:9090
kubectl port-forward -n techx-tf3 service/currency 7001:7001
kubectl port-forward -n techx-tf3 service/shipping 50051:50051
```

Mở 6 terminal riêng hoặc dùng tmux/ngrok.

**Bước 2: Khởi động agent (không set USE_TEST_SERVER)**

```powershell
uvicorn src.main:app --port 8001
```

Mặc định `USE_TEST_SERVER=false`, agent gọi đến localhost:3550/7070/... (port-forward).

**Bước 3: Mở browser → [http://localhost:8001/chatbot](http://localhost:8001/chatbot)**

---

## API endpoints

| Endpoint | Method | Chức năng |
|----------|--------|-----------|
| `/health` | GET | Health check |
| `/chatbot` | GET | Giao diện chatbot HTML |
| `/api/chat` | POST | Gửi tin nhắn, nhận trả lời |
| `/api/confirm` | POST | Xác nhận hành động (thêm giỏ hàng) |
| `/docs` | GET | Swagger UI |

### POST /api/chat

```json
{
  "message": "tôi cần kính thiên văn dưới 100 đô",
  "session_id": "(tự động sinh nếu để trống)",
  "user_id": "anonymous"
}
```

Response:
```json
{
  "status": "ok",
  "reply": "Dạ, đây là các sản phẩm kính thiên văn dưới 100 đô...",
  "session_id": "uuid-xxx",
  "steps": [
    {"action": "search_products_v2", "status": "ok", "detail": "...", "duration_ms": 1200}
  ]
}
```

## Cấu trúc server-test

```
server-test/
├── server/
│   ├── main.py                    # Entry point: 7 servers (6 gRPC + 1 HTTP)
│   ├── config.py                  # DB_PATH, GRPC_PORT
│   ├── db.py                      # aiosqlite wrapper
│   ├── handlers/
│   │   ├── products_service.py     # Products (legacy proto)
│   │   ├── product_reviews_service.py  # ProductReviews (legacy proto)
│   │   ├── accounting_service.py  # Accounting (legacy proto)
│   │   ├── demo_catalog_service.py    # ProductCatalogService (demo.proto)
│   │   ├── demo_cart_service.py       # CartService (demo.proto)
│   │   ├── demo_review_service.py     # ProductReviewService (demo.proto)
│   │   ├── demo_recommendation_service.py  # RecommendationService (demo.proto)
│   │   └── demo_currency_service.py      # CurrencyService (demo.proto)
│   ├── demo_pb2.py                # Stub từ demo.proto
│   └── demo_pb2_grpc.py
├── proto/
│   ├── demo.proto                 # demo.proto (giống src/protos/)
│   ├── products.proto
│   ├── product_reviews.proto
│   └── accounting.proto
├── database/
│   └── init.sql                   # SQLite schema + seed data
├── scripts/
│   └── seed.py                    # Seed script
└── requirements.txt
```
