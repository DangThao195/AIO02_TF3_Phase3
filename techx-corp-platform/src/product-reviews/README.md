# Product Reviews Service

This service returns product reviews for a specific product, along with an
AI-generated summary of the product reviews.

## Local Build

To build the protos, run from the root directory:

```sh
make docker-generate-protobuf
```

## Docker Build

From the root directory, run:

```sh
docker compose build product-reviews
```

## LLM Configuration

By default, this service uses a mock LLM service, as configured in
the `.env` file:

``` yaml
LLM_BASE_URL=http://${LLM_HOST}:${LLM_PORT}/v1
LLM_MODEL=techx-llm
OPENAI_API_KEY=dummy
```

If desired, the configuration can be changed to point to a real, OpenAI API
compatible LLM in the file `.env.override`. For example, the following
configuration can be used to utilize OpenAI's gpt-4o-mini model:

``` yaml
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=<replace with API key>
```

---

## Sơ đồ luồng hoạt động chi tiết (Detailed Code Flowcharts)

Để đảm bảo khả năng hiển thị tốt nhất trên các ứng dụng như Obsidian và GitHub, sơ đồ luồng hoạt động của dịch vụ Product Reviews (`product_reviews_server.py`) được chia nhỏ thành 4 sơ đồ thành phần dưới đây:

### 1. Tổng quan các Endpoint gRPC (Service Endpoints Overview)
Sơ đồ này biểu diễn các entry-point gRPC chính được dịch vụ hỗ trợ:

```mermaid
flowchart TD
    Client([Yêu cầu từ Client]) --> Endpoints{Yêu cầu gọi Endpoint?}
    Endpoints -->|GetProductReviews| Flow1[Luồng lấy danh sách Review]
    Endpoints -->|GetAverageProductReviewScore| Flow2[Luồng tính điểm trung bình]
    Endpoints -->|AskProductAIAssistant| Flow3[Luồng Trợ lý AI - RAG]
```

### 2. Luồng Khởi tạo Dịch vụ (Initialization Flow)
Quy trình khởi tạo gRPC server và thiết lập OpenTelemetry telemetry/logging khi khởi động service:

```mermaid
flowchart TD
    Start(["Chạy product_reviews_server.py"]) --> Env["Đọc biến môi trường (Port, LLM, Catalog, DB, etc.)"]
    Env --> SetFlagd["Cài đặt FlagdProvider cho OpenFeature (Feature Flag)"]
    SetFlagd --> InitOtel["Khởi tạo OpenTelemetry (Tracer, Meter & Metrics)"]
    InitOtel --> InitLogs["Cấu hình OpenTelemetry Logger & Exporter"]
    InitLogs --> CreateServer["Tạo gRPC Server (ThreadPoolExecutor với 10 workers)"]
    CreateServer --> RegServices["Đăng ký ProductReviewService & Health Service"]
    RegServices --> ConnectCatalog["Thiết lập grpc.insecure_channel với Product Catalog Service"]
    ConnectCatalog --> StartListen["Khởi động gRPC Server & lắng nghe kết nối"]
```

### 3. Luồng GetProductReviews & GetAverageProductReviewScore (Database Queries)
Cách thức xử lý các truy vấn trực tiếp vào PostgreSQL database:

```mermaid
flowchart TD
    subgraph GetReviews ["GetProductReviews"]
        ReqReviews(["Nhận GetProductReviews"]) --> SpanReviews["Bắt đầu trace span 'get_product_reviews'"]
        SpanReviews --> FetchDB["Truy vấn reviews.productreviews từ DB Postgres"]
        FetchDB --> LoopReviews["Lặp qua các bản ghi & thêm vào Response"]
        LoopReviews --> CountMetric["Tăng metric 'app_product_review_counter'"]
        CountMetric --> EndSpanReviews["Kết thúc trace span"]
        EndSpanReviews --> RetReviews(["Trả về GetProductReviewsResponse"])
    end

    subgraph GetScore ["GetAverageProductReviewScore"]
        ReqScore(["Nhận GetAverageProductReviewScore"]) --> SpanScore["Bắt đầu trace span 'get_average_product_review_score'"]
        SpanScore --> FetchAvgDB["Tính điểm trung bình AVG(score) từ DB Postgres"]
        FetchAvgDB --> SetScore["Gán average_score vào Response"]
        SetScore --> EndSpanScore["Kết thúc trace span"]
        EndSpanScore --> RetScore(["Trả về GetAverageProductReviewScoreResponse"])
    end
```

### 4. Luồng xử lý AskProductAIAssistant (RAG Pipeline)
Quy trình phức tạp nhất thực thi RAG 2-turn, điều hướng Feature Flag và tương tác với mô hình LLM:

```mermaid
flowchart TD
    ReqAI(["Nhận AskProductAIAssistant"]) --> SpanAI["Bắt đầu trace span 'get_ai_assistant_response'"]
    SpanAI --> FlagRate{"Feature Flag 'llmRateLimitError' bật?"}
    
    FlagRate -->|Đang bật| RandCheck{"Số ngẫu nhiên < 0.5?"}
    FlagRate -->|Đang tắt| NormalClient["Khởi tạo OpenAI Client (llm_base_url, llm_api_key)"]
    
    RandCheck -->|Đúng - Giả lập lỗi 429| MockClient["Khởi tạo OpenAI Client trỏ về Mock LLM"]
    RandCheck -->|Sai| NormalClient
    
    MockClient --> CallMock["Gọi Mock LLM với model 'techx-llm-rate-limit'"]
    CallMock --> TryCatch{"Bắt lỗi Exception 429?"}
    TryCatch -->|Có lỗi| RecException["Ghi Exception vào Span (ERROR status)"]
    RecException --> RetFallback["Trả về phản hồi lỗi hệ thống thân thiện"]
    TryCatch -->|Không lỗi| NormalClient
    
    NormalClient --> CallLLM1["Gọi LLM lần 1 (prompt + danh sách tools, tool_choice='auto')"]
    CallLLM1 --> ToolReq{"LLM yêu cầu gọi Tool?"}
    
    ToolReq -->|Không| RetNormal["Lấy nội dung câu trả lời trực tiếp"]
    ToolReq -->|Có| AppendCalls["Thêm tin nhắn Assistant chứa tool_calls vào messages"]
    
    AppendCalls --> LoopTools["Lặp qua từng tool_call yêu cầu từ LLM"]
    LoopTools --> ToolType{"Loại Tool?"}
    
    ToolType -->|fetch_product_reviews| RunReviewTool["Gọi fetch_product_reviews (Truy vấn DB Postgres)"]
    ToolType -->|fetch_product_info| RunInfoTool["Gọi fetch_product_info (gRPC tới Product Catalog)"]
    ToolType -->|Khác| RaiseToolErr["Ném lỗi Exception"]
    
    RunReviewTool --> AppendToolMsg["Nối kết quả trả về từ tool vào messages (role='tool')"]
    RunInfoTool --> AppendToolMsg
    
    AppendToolMsg --> FlagInaccurate{"Feature Flag 'llmInaccurateResponse' bật AND ID == 'L9ECAV7KIM'?"}
    
    FlagInaccurate -->|Đúng| PromptInaccurate["Thêm prompt yêu cầu trả lời SAI lệch"]
    FlagInaccurate -->|Sai| PromptAccurate["Thêm prompt yêu cầu trả lời ĐÚNG thực tế"]
    
    PromptInaccurate --> CallLLM2["Gọi LLM lần 2 để đúc kết câu trả lời cuối cùng"]
    PromptAccurate --> CallLLM2
    
    CallLLM2 --> SetResult["Gán phản hồi từ LLM lần 2 làm kết quả final"]
    
    RetNormal --> IncMetric["Tăng metric 'app_ai_assistant_counter'"]
    SetResult --> IncMetric
    RetFallback --> IncMetric
    
    IncMetric --> EndSpanAI["Kết thúc trace span"]
    EndSpanAI --> RetAIResponse(["Trả về AskProductAIAssistantResponse"])
```

## Chi tiết các luồng xử lý chính

### 1. Luồng Lấy Đánh Giá & Điểm Số
* **`GetProductReviews`**: Truy vấn danh sách đánh giá từ cơ sở dữ liệu Postgres bằng hàm `fetch_product_reviews_from_db`, ghi nhận số lượng review nhận được vào OpenTelemetry metric `app_product_review_counter`, sau đó trả về danh sách dưới định dạng protobuf.
* **`GetAverageProductReviewScore`**: Truy vấn điểm đánh giá trung bình từ database và trả về.

### 2. Luồng Trợ lý AI (`AskProductAIAssistant`)
* **Bước 1: Chống chịu sự cố (Fault Tolerance)**
  * Kiểm tra Feature Flag `llmRateLimitError`. Nếu được bật bởi Ban Tổ Chức, hệ thống giả lập lỗi Rate Limit (429) với tỷ lệ 50% và trả về thông báo lỗi thân thiện để tránh làm sập client.
* **Bước 2: Gọi LLM Lần 1 (Giai đoạn Đề xuất Hành động)**
  * Tạo kết nối đến LLM (theo API OpenAI tương thích). Gửi kèm danh sách `tools` định nghĩa trong mã nguồn (gồm `fetch_product_reviews` và `fetch_product_info`).
* **Bước 3: Thực thi Tool (nếu LLM yêu cầu)**
  * Nếu LLM quyết định cần gọi tool, hệ thống sẽ thực thi các hàm truy vấn DB (`fetch_product_reviews` hoặc `fetch_product_info`) cục bộ.
  * Kết quả trả về từ tool được chuyển thành văn bản JSON và chèn vào lịch sử hội thoại (`messages`).
* **Bước 4: Gọi LLM Lần 2 (Giai đoạn Tổng hợp câu trả lời)**
  * Hệ thống kiểm tra Feature Flag `llmInaccurateResponse` trên sản phẩm test (`L9ECAV7KIM`) để điều hướng hành vi sinh phản hồi (sinh câu trả lời đúng hay cố tình sai lệch).
  * Gọi LLM lần 2 để đúc kết câu trả lời cuối cùng dựa trên các dữ liệu thực tế thu thập được từ tool.
* **Bước 5: Trả kết quả**
  * Tăng chỉ số metric `app_ai_assistant_counter` và trả câu trả lời cho Client.
