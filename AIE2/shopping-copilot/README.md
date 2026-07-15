# Shopping Copilot — TechX Corp

Trợ lý mua sắm AI cho TechX Corp, vận hành trên AWS EKS với LLM Amazon Nova (Bedrock).
Thuộc nhóm AIO02 — TF3 Phase 3.

Hỗ trợ tìm kiếm sản phẩm (SQL + RAG), xem đánh giá, thêm giỏ hàng (có xác nhận),
gợi ý sản phẩm, quy đổi tiền tệ và tra phí vận chuyển.

## Yêu cầu

- Python 3.11+
- `pip install -r requirements.txt`
- AWS credentials (cho Bedrock LLM, Guardrails, Knowledge Base)
- (Tùy chọn) server-test local nếu không có kết nối EKS

## Cấu hình

Sao chép `.env` từ mẫu (xem `.env` hiện có) và điền các thông số:

| Biến | Mô tả |
|------|-------|
| `BEDROCK_MODEL_ID` | Model ID (VD: `apac.amazon.nova-lite-v1:0`) |
| `BEDROCK_REGION` | Region AWS cho Bedrock |
| `BEDROCK_GUARDRAIL_ID` | Guardrail ID (tuỳ chọn) |
| `CATALOG_ADDR` | `localhost:3550` (local) hoặc `product-catalog:3550` (K8s) |
| `CART_ADDR` | `localhost:7070` (local) hoặc `cart:7070` (K8s) |
| `REVIEWS_ADDR` | `localhost:9090` (local) |
| `RECO_ADDR` | `localhost:8081` (local) |
| `CURRENCY_ADDR` | `localhost:7001` (local) |
| `SHIPPING_ADDR` | `http://localhost:50052` (local) |
| `BEDROCK_KB_ID` | Knowledge Base ID cho RAG (tuỳ chọn) |
| `DB_CONNECTION_STRING` | PostgreSQL connection string cho Flow 1 SQL |

Dùng `--mock` flag hoặc `MOCK_EKS=true` để chạy với gRPC mock (không cần backend thật).

## Kiến trúc

```
shopping-copilot/
├── src/                    # Mã nguồn chính
│   ├── main.py             # FastAPI server (endpoints /api/chat, /api/confirm, /chatbot)
│   ├── agent/
│   │   ├── agent.py        # Public API convenience re-export
│   │   ├── copilot_agent.py # CopilotAgent (ReAct loop + 6 guardrails + step tracking)
│   │   └── response_formatter.py  # Định dạng lại response (emoji cleanup, bold)
│   ├── llm/
│   │   ├── llm.py          # AWS Bedrock client (Amazon Nova)
│   │   └── prompt.py       # System prompt + format prompt
│   ├── guardrails/         # 6 lớp bảo vệ
│   │   ├── input_filter.py  # L2: Regex + Bedrock Guardrails
│   │   ├── confirmation.py  # L1: HMAC confirmation gate
│   │   ├── fallback.py      # L3: Exception handler + retry
│   │   ├── tool_validator.py# L4: Allow-list + user isolation + param bounds
│   │   ├── output_filter.py # L5: PII redaction
│   │   └── rate_limiter.py  # L6: Request/token limit
│   ├── memory/
│   │   ├── store.py        # SessionStore + CacheStore (TTL, LRU, JSON persistence)
│   │   └── cache.py        # Backward compatibility re-export
│   ├── tools/              # 10 công cụ agent
│   │   ├── search/         # Search pipeline (multi-strategy)
│   │   │   ├── orchestrator.py  # Phối hợp Flow 1 + Flow 2 + Reranker
│   │   │   ├── flow1/      # SQL matching (entity extractor → SQL builder → executor)
│   │   │   ├── flow2/      # RAG (Bedrock Knowledge Base)
│   │   │   ├── reranker.py # Hợp nhất & xếp hạng kết quả
│   │   │   └── models.py   # Data classes
│   │   ├── catalog_tool.py # get_categories, get_all_products
│   │   ├── cart_tool.py    # add_to_cart_tool, get_cart_tool, check_cart_item_tool
│   │   ├── review_tool.py  # get_product_reviews_tool
│   │   ├── recommendation_tool.py  # get_recommendations_tool
│   │   ├── currency_tool.py # convert_currency_tool
│   │   ├── shipping_tool.py # get_shipping_quote_tool (REST)
│   │   ├── product_id_tool.py # get_product_id (tra cứu ID từ tên)
│   │   └── service_config.py  # Resolver địa chỉ backend (real/test)
│   ├── protos/             # gRPC stubs (demo.proto)
│   ├── database/           # PostgreSQL connection pool
│   └── evaluation/         # Trust & Safety evaluation
├── server-test/            # Mock backend local (7 servers: 6 gRPC + 1 HTTP)
├── static/                 # Giao diện chatbot HTML
├── data/                   # Runtime data (cache, session JSON)
├── scripts/                # Công cụ vận hành
│   ├── sync_db_to_s3.py
│   ├── cron_sync_and_sync_kb.py
│   └── start_port_forwards.py
├── tests/                  # Test suite + pipeline đánh giá
├── contracts/              # Tài liệu bàn giao
└── reports/                # Trust & Safety report
```

### 10 công cụ agent

| Công cụ | Chức năng | Backend |
|---------|-----------|---------|
| `search_products_v2` | Tìm kiếm sản phẩm (SQL + RAG + reranker) | SQL DB + Bedrock KB |
| `get_categories` | Danh sách danh mục | SQL DB |
| `get_all_products` | Toàn bộ sản phẩm (chỉ khi cần) | SQL DB |
| `get_product_id` | Tra product_id từ tên sản phẩm | SQL DB + SQLite |
| `get_product_reviews_tool` | Xem đánh giá | gRPC ProductReviewService |
| `add_to_cart_tool` | Thêm vào giỏ (cần xác nhận) | gRPC CartService |
| `get_cart_tool` | Xem giỏ hàng | gRPC CartService |
| `get_recommendations_tool` | Gợi ý sản phẩm | gRPC RecommendationService |
| `convert_currency_tool` | Quy đổi tiền tệ | gRPC CurrencyService |
| `get_shipping_quote_tool` | Phí vận chuyển (nội địa VN) | REST HTTP |

### 6 lớp Guardrail

| Lớp | Chức năng | File |
|-----|-----------|------|
| L1 | Confirmation Gate (HMAC token cho write actions) | `confirmation.py` |
| L2 | Input Filter (Regex + AWS Bedrock Guardrails) | `input_filter.py` |
| L3 | Fallback (xử lý exception, timeout, retry) | `fallback.py` |
| L4 | Tool Validator (allow-list, user isolation, param bounds) | `tool_validator.py` |
| L5 | Output Filter (PII redaction) | `output_filter.py` |
| L6 | Rate Limiter (request/token per user) | `rate_limiter.py` |

---

## Cách chạy

### Option A: Server-test (mock local) — khuyên dùng

**Bước 1: Seed database** (chỉ làm 1 lần)

```powershell
cd server-test
python scripts/seed.py
```

**Bước 2: Khởi động server-test**

```powershell
cd server-test
python -m server.main
```

Server-test lắng nghe trên 7 cổng:

| Cổng | Dịch vụ | Giao thức |
|------|---------|-----------|
| 3550 | ProductCatalogService | gRPC |
| 7070 | CartService | gRPC |
| 8081 | RecommendationService | gRPC |
| 9090 | ProductReviewService | gRPC |
| 7001 | CurrencyService | gRPC |
| 50051 | Legacy (Products + Reviews + Accounting) | gRPC |
| 50052 | Shipping REST | HTTP |

**Bước 3: Mở terminal mới — khởi động agent**

```powershell
uvicorn src.main:app --port 8001 --mock
```

`--mock` flag kích hoạt gRPC mock để chạy không cần backend thật.

**Bước 4: Mở browser**

Truy cập: [http://localhost:8001/chatbot](http://localhost:8001/chatbot)

**Câu lệnh test nhanh:**

```
cho tôi xem kính thiên văn dưới 100 đô
có những danh mục sản phẩm nào
thêm sản phẩm OLJCESPC7Z vào giỏ hàng
giỏ hàng của tôi có gì
đánh giá về sản phẩm 66VCHSJNUP
```

### Option B: Kết nối server thật (EKS)

**Bước 1: Port-forward các service**

```powershell
kubectl port-forward -n techx-tf3 service/product-catalog 3550:3550
kubectl port-forward -n techx-tf3 service/cart 7070:7070
kubectl port-forward -n techx-tf3 service/recommendation 8081:8081
kubectl port-forward -n techx-tf3 service/product-reviews 9090:9090
kubectl port-forward -n techx-tf3 service/currency 7001:7001
kubectl port-forward -n techx-tf3 service/shipping 50052:50052
```

**Bước 2: Khởi động agent**

```powershell
uvicorn src.main:app --port 8001
```

Mặc định agent đọc địa chỉ từ `.env` (`CATALOG_ADDR`, `CART_ADDR`, ...).

### Option C: Dùng gRPC mock (không cần server-test)

```powershell
set MOCK_EKS=true
uvicorn src.main:app --port 8001
```

Hoặc không dùng biến môi trường:

```powershell
uvicorn src.main:app --port 8001 --mock
```

## API endpoints

| Endpoint | Method | Chức năng |
|----------|--------|-----------|
| `/` | GET | Thông tin server |
| `/health` | GET | Health check |
| `/chatbot` | GET | Giao diện chatbot HTML |
| `/api/chat` | POST | Gửi tin nhắn, nhận trả lời |
| `/api/confirm` | POST | Xác nhận hành động (thêm giỏ hàng) |
| `/api/cart` | GET | Xem giỏ hàng theo user_id |
| `/debug/session/{id}` | GET | Tra cứu session memory |
| `/debug/sessions` | GET | Danh sách session |
| `/debug/cache` | GET | Cache store stats |
| `/debug/ratelimit` | GET | Rate limiter state |
| `/docs` | GET | Swagger UI |

### POST /api/chat

```json
{
  "message": "tôi cần kính thiên văn dưới 100 đô",
  "session_id": "(tự động sinh nếu để trống)",
  "user_id": "anonymous"
}
```

Response khi thành công (status=ok):

```json
{
  "status": "ok",
  "reply": "Dạ, đây là các sản phẩm kính thiên văn dưới 100 đô...",
  "session_id": "uuid-xxx",
  "token": null,
  "steps": [
    {"action": "search_products_v2", "status": "ok", "detail": "...", "duration_ms": 1200}
  ]
}
```

Response khi cần xác nhận (status=pending):

```json
{
  "status": "pending",
  "reply": "Vui lòng xác nhận thêm 1 sản phẩm 'OLJCESPC7Z' vào giỏ hàng.",
  "session_id": "uuid-xxx",
  "token": "eyJ...signature",
  "steps": [...]
}
```

### POST /api/confirm

```json
{
  "session_id": "uuid-xxx",
  "token": "eyJ...signature"
}
```

## Luồng tìm kiếm (Search Pipeline)

```
Query → Entity Extractor (heuristic + LLM) ─┬→ Flow 1: SQL matching (PostgreSQL / SQLite)
                                             │
                                             └→ Flow 2: RAG (Bedrock Knowledge Base)
                                                    │
                                                    ↓
                                              PromptRewriter
                                                    │
                                                    ↓
                                              KB Query → resolve product details
                                                    │
                                                    ↓
                                              Reranker (dedup + merge)
                                                    │
                                                    ↓
                                              Result (top 5 products)
```
