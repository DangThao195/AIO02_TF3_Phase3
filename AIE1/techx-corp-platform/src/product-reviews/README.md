# Product Reviews Service

Dịch vụ Product Reviews cung cấp thông tin đánh giá sản phẩm và trả về bản tóm tắt tự động sử dụng Trợ lý AI (RAG Pipeline) kèm theo các cơ chế Caching, Resilience, và Observability được tích hợp sẵn.

---

## 1. Hướng dẫn Dựng & Chạy local

### Build Protobuf
Chạy từ thư mục gốc của project:
```sh
make docker-generate-protobuf
```

### Docker Build
Chạy từ thư mục gốc của project:
```sh
docker compose build product-reviews
```

### Chạy Replay Simulation (Kiểm thử Closed-loop)
Chạy trực tiếp từ thư mục này để giả lập kịch bản dập lỗi của AIOps:
```sh
python aiops_replay_sim.py
```

---

## 2. Kiến trúc & Các Điểm Cải Tiến Cốt Lõi (Tuần 3)

Dịch vụ đã được nâng cấp toàn diện để đáp ứng các tiêu chuẩn vận hành an toàn:
1. **Caching 2 Tầng (LLM & Database):**
   * **Tầng 1 (Redis Cache):** Tra cứu trước khi gọi LLM. Cache key băm SHA256 phân tách theo `user_id` để tránh rò rỉ chéo thông tin. Trả cờ `cache: hit` hoặc `cache: miss` qua gRPC trailing metadata.
   * **Tầng 2 (PostgreSQL Filter):** Chỉ truy vấn và sử dụng các review có cột `is_safe = TRUE` làm context sạch gửi cho LLM.
2. **Circuit Breaker (Bộ ngắt mạch an toàn):**
   * Giám sát tỷ lệ lỗi kết nối LLM qua Redis. Tự động chuyển trạng thái `OPEN` (chuyển sang PostgreSQL cache hoặc trả về fallback) sau 5 lỗi liên tiếp trong 30 giây để bảo vệ hệ thống khỏi nghẽn luồng.
3. **Graceful Shutdown & Auto-Reconnection:**
   * Lắng nghe tín hiệu `SIGTERM` / `SIGINT`.
   * Khi tắt, chuyển trạng thái gRPC Health Check thành `NOT_SERVING` và trì hoãn ngắt kết nối `server.stop(grace=5.0)` để hoàn thành các request đang dở dang.
   * Tự động thử lại kết nối PostgreSQL (5 lần exponential backoff) và Redis khi startup để tránh crash pod nếu dependencies khởi động chậm hơn service.
4. **OTel Telemetry Sidecar Server (Port 8086):**
   * Cung cấp cổng phụ HTTP hỗ trợ giám sát và tiêm lỗi:
     * `POST /replay`: Chạy kịch bản dập lỗi closed-loop.
     * `GET /trace/<trace_id>`: Lấy vết telemetry đã được che PII lưu trên Redis.
     * `POST /inject`: Giả lập lỗi 429/timeout để test khả năng chống chịu của server.

---

## 3. Sơ đồ luồng hoạt động chi tiết (Detailed Code Flowcharts)

### 3.1. Tổng quan các Endpoint gRPC (Service Endpoints Overview)
```mermaid
flowchart TD
    Client([Yêu cầu từ Client]) --> Endpoints{Yêu cầu gọi Endpoint?}
    Endpoints -->|GetProductReviews| Flow1[Luồng lấy danh sách Review]
    Endpoints -->|GetAverageProductReviewScore| Flow2[Luồng tính điểm trung bình]
    Endpoints -->|AskProductAIAssistant| Flow3[Luồng Trợ lý AI - RAG]
```

### 3.2. Luồng Khởi tạo Dịch vụ & Graceful Shutdown
```mermaid
flowchart TD
    Start(["Chạy product_reviews_server.py"]) --> Env["Đọc biến môi trường"]
    Env --> DBConnect{"Thử kết nối PostgreSQL & Redis"}
    DBConnect -->|Thất bại| Retry["Retry Connection (Backoff 5 lần)"]
    Retry --> DBConnect
    DBConnect -->|Thành công| InitOtel["Khởi tạo OpenTelemetry & Prometheus Metrics"]
    InitOtel --> CreateServer["Tạo gRPC Server & Đăng ký Health Check (SERVING)"]
    CreateServer --> RegisterSignal["Đăng ký Bắt Tín Hiệu SIGTERM/SIGINT"]
    RegisterSignal --> StartListen["Khởi động gRPC Server & Lắng nghe kết nối"]
    
    StartListen -->|Nhận SIGTERM/SIGINT| HealthNotServing["Đổi Health status -> NOT_SERVING"]
    HealthNotServing --> WaitGrace["Trì hoãn & Tắt server qua server.stop(grace=5.0)"]
    WaitGrace --> EndService(["Dịch vụ tắt an toàn"])
```

### 3.3. Luồng Database Queries
```mermaid
flowchart TD
    ReqReviews(["Nhận GetProductReviews"]) --> SpanReviews["Bắt đầu trace span 'get_product_reviews'"]
    SpanReviews --> FetchDB["Truy vấn DB Postgres: Chỉ lấy dòng is_safe = TRUE"]
    FetchDB --> LoopReviews["Lặp qua các bản ghi & thêm vào Response"]
    LoopReviews --> CountMetric["Tăng metric 'app_product_review_counter'"]
    CountMetric --> EndSpanReviews["Kết thúc trace span"]
    EndSpanReviews --> RetReviews(["Trả về GetProductReviewsResponse"])
```

### 3.4. Luồng xử lý AskProductAIAssistant (RAG Pipeline)
```mermaid
flowchart TD
    ReqAI(["Nhận AskProductAIAssistant - product_id, question, user_id"]) --> SpanAI["Bắt đầu trace span"]
    SpanAI --> InputFilter{"Chạy check_input - Bộ lọc đầu vào"}
    InputFilter -->|Không an toàn / Injection| RetBlocked["Gán blocked_reason làm response"]
    
    InputFilter -->|An toàn| CheckCB{"Circuit Breaker có OPEN?"}
    CheckCB -->|Đúng| RetFallback["Trả về Fallback / Cache message"]
    
    CheckCB -->|Sai| BuildKey["Tạo Cache Key SHA256 (user_id + question + product_id)"]
    BuildKey --> LookupCache{"Tra cứu Redis Cache"}
    
    LookupCache -->|Cache HIT| AddHitHeader["Gán metadata 'cache: hit'"]
    AddHitHeader --> RetCache["Trả kết quả từ Cache"]
    
    LookupCache -->|Cache MISS| AddMissHeader["Gán metadata 'cache: miss'"]
    AddMissHeader --> CallLLM["Gọi Candidate LLM (Bedrock / OpenAI)"]
    
    CallLLM -->|LLM Lỗi / Timeout| FallbackMsg["Sử dụng FALLBACK_SUMMARY_MESSAGE"]
    CallLLM -->|LLM Thành công| OutputFilter["Lọc PII & leak system prompt ở đầu ra"]
    
    OutputFilter --> CallJudge["Gọi Giám khảo call_summary_judge để chấm Fidelity"]
    CallJudge --> CheckClaims{"Phát hiện claim unsupported / contradicted?"}
    
    CheckClaims -->|Có - Không trung thực| RejectSummary["Trả về UNVERIFIED_SUMMARY_MESSAGE (Không ghi Cache)"]
    CheckClaims -->|Không - Hoàn toàn trung thực| SaveCache["Ghi kết quả vào Redis Cache kèm Metadata"]
    SaveCache --> ApproveSummary["Trả về kết quả tóm tắt cho khách"]
    
    RetBlocked --> EndSpanAI["Kết thúc trace span & Trả về Response"]
    RetFallback --> EndSpanAI
    RetCache --> EndSpanAI
    FallbackMsg --> EndSpanAI
    RejectSummary --> EndSpanAI
    ApproveSummary --> EndSpanAI
```

---

## 4. Cấu hình Biến Môi trường (Environment Variables)

Các tham số cấu hình chính trong file `.env` hoặc `.env.override`:

| Biến môi trường | Giá trị mặc định | Giải thích |
| :--- | :--- | :--- |
| `CACHE_TYPE` | `redis` | Loại cache sử dụng (`redis` hoặc `none`). |
| `REDIS_HOST` | `localhost` | Endpoint máy chủ Redis Cache. |
| `REDIS_PORT` | `6379` | Cổng kết nối Redis. |
| `DB_CONNECTION_STRING` | *Postgres URI* | Connection string kết nối PostgreSQL. |
| `LLM_BASE_URL` | *AWS / OpenAI Endpoint* | Đường dẫn gọi API của LLM. |
| `LLM_MODEL` | `techx-llm` | Tên mô hình Candidate. |
