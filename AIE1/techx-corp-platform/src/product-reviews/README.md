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

### 3. Luồng Database Queries (GetProductReviews & GetAverageProductReviewScore)
Cách thức xử lý các truy vấn trực tiếp vào PostgreSQL database được chia làm 2 luồng độc lập để hiển thị rõ ràng nhất:

#### 3.1. Luồng xử lý GetProductReviews
```mermaid
flowchart TD
    ReqReviews(["Nhận GetProductReviews"]) --> SpanReviews["Bắt đầu trace span 'get_product_reviews'"]
    SpanReviews --> FetchDB["Truy vấn reviews.productreviews từ DB Postgres"]
    FetchDB --> LoopReviews["Lặp qua các bản ghi & thêm vào Response"]
    LoopReviews --> CountMetric["Tăng metric 'app_product_review_counter'"]
    CountMetric --> EndSpanReviews["Kết thúc trace span"]
    EndSpanReviews --> RetReviews(["Trả về GetProductReviewsResponse"])
```

#### 3.2. Luồng xử lý GetAverageProductReviewScore
```mermaid
flowchart TD
    ReqScore(["Nhận GetAverageProductReviewScore"]) --> SpanScore["Bắt đầu trace span 'get_average_product_review_score'"]
    SpanScore --> FetchAvgDB["Tính điểm trung bình AVG(score) từ DB Postgres"]
    FetchAvgDB --> SetScore["Gán average_score vào Response"]
    SetScore --> EndSpanScore["Kết thúc trace span"]
    EndSpanScore --> RetScore(["Trả về GetAverageProductReviewScoreResponse"])
```

### 4. Luồng xử lý AskProductAIAssistant (RAG Pipeline)
Quy trình của trợ lý AI được thiết kế đa tầng để bảo vệ an toàn (Guardrails), xử lý lỗi linh hoạt (Fallback) và tự động đánh giá độ trung thực (Evaluation). Dưới đây là sơ đồ chi tiết được chia thành 4 giai đoạn chính:

#### 4.1. Giai đoạn 1: Nhận Yêu cầu & Bộ lọc Đầu vào (Input Guardrail)
```mermaid
flowchart TD
    ReqAI(["Nhận AskProductAIAssistant - product_id, question"]) --> SpanAI["Bắt đầu trace span 'get_ai_assistant_response'"]
    SpanAI --> InputFilter{"Chạy check_input - Bộ lọc đầu vào"}
    InputFilter -->|Không an toàn / Phát hiện Prompt Injection| RetBlocked["Gán blocked_reason làm response"]
    RetBlocked --> EndSpanAI["Kết thúc trace span & Trả về AskProductAIAssistantResponse"]
    
    InputFilter -->|An toàn| PromptBuild["Xây dựng Runtime Prompts & System Prompt"]
    PromptBuild --> ProviderCheck{"Mô hình LLM nào đang dùng?"}
    
    ProviderCheck -->|AWS Bedrock| BedrockFlow[Chuyển sang Luồng AWS Bedrock]
    ProviderCheck -->|OpenAI / Mock LLM| OpenAIFlow[Chuyển sang Luồng OpenAI / Mock]
```

#### 4.2. Giai đoạn 2A: Luồng Xử lý AWS Bedrock (Grounded Bedrock Pipeline)
```mermaid
flowchart TD
    BedrockFlow[Bắt đầu luồng AWS Bedrock] --> FetchDB["Gọi fetch_product_reviews từ Postgres"]
    FetchDB --> ReviewFilter["Kiểm tra & Lọc từng review qua check_input để chặn Injection và PII"]
    ReviewFilter --> BuildContext["Chuẩn hóa thành safe_reviews_json - Thay thế phần độc hại bằng nhãn cảnh báo"]
    BuildContext --> FetchInfo["Gọi fetch_product_info từ Catalog Service"]
    
    FetchInfo --> CheckInaccurate{"Feature Flag 'llmInaccurateResponse' bật cho sản phẩm test L9ECAV7KIM?"}
    CheckInaccurate -->|Đúng| GroundedPromptInaccurate["Xây dựng Grounded Prompt yêu cầu trả lời SAI lệch"]
    CheckInaccurate -->|Sai| GroundedPromptAccurate["Xây dựng Grounded Prompt yêu cầu trả lời ĐÚNG thực tế"]
    
    GroundedPromptInaccurate --> CallBedrock{"Gọi AWS Bedrock qua converse với Fallback wrapper"}
    GroundedPromptAccurate --> CallBedrock
    
    CallBedrock -->|Thành công| PostProcess[Chuyển sang Giai đoạn 3: Hậu xử lý & Đánh giá]
    CallBedrock -->|Gặp lỗi / Timeout| FallbackMsg["Sử dụng FALLBACK_SUMMARY_MESSAGE"]
    FallbackMsg --> EndSpanAI["Kết thúc trace span & Trả về AskProductAIAssistantResponse"]
```

#### 4.3. Giai đoạn 2B: Luồng Xử lý OpenAI / Mock và gọi Tool (OpenAI Tool-Use Pipeline)
```mermaid
flowchart TD
    OpenAIFlow[Bắt đầu luồng OpenAI / Mock] --> FlagRate{"Feature Flag 'llmRateLimitError' bật?"}
    
    FlagRate -->|Đang bật| RandCheck{"Số ngẫu nhiên < 0.5?"}
    FlagRate -->|Đang tắt| CallLLM1["Gọi Candidate LLM lần 1 với danh sách tools"]
    
    RandCheck -->|Đúng - Giả lập lỗi 429| CallMock["Gọi Mock LLM với model techx-llm-rate-limit"]
    RandCheck -->|Sai| CallLLM1
    
    CallMock -->|Gặp lỗi 429| FallbackRateLimit["Trả về thông báo lỗi Rate Limit hệ thống"]
    FallbackRateLimit --> EndSpanAI["Kết thúc trace span"]
    CallMock -->|Không lỗi| CallLLM1
    
    CallLLM1 --> ToolReq{"LLM yêu cầu gọi Tool?"}
    
    ToolReq -->|Không| PostProcess[Chuyển sang Giai đoạn 3: Hậu xử lý & Đánh giá]
    ToolReq -->|Có| LoopTools["Lặp qua từng tool_call của LLM"]
    
    LoopTools --> ToolType{"Loại Tool?"}
    ToolType -->|fetch_product_reviews| RunReviewTool["Gọi fetch_product_reviews"]
    ToolType -->|fetch_product_info| RunInfoTool["Gọi fetch_product_info"]
    
    RunReviewTool --> FilterReview["Lọc review bằng check_input để chặn Injection và PII"]
    FilterReview --> AppendToolMsg["Nối kết quả an toàn vào messages với role='tool'"]
    RunInfoTool --> AppendToolMsg
    
    AppendToolMsg --> FlagInaccurate{"Feature Flag 'llmInaccurateResponse' bật AND ID == 'L9ECAV7KIM'?"}
    FlagInaccurate -->|Đúng| PromptInaccurate["Thêm prompt yêu cầu trả lời SAI lệch"]
    FlagInaccurate -->|Sai| PromptAccurate["Thêm prompt yêu cầu trả lời ĐÚNG thực tế"]
    
    PromptInaccurate --> CallLLM2["Gọi Candidate LLM lần 2 với Fallback wrapper"]
    PromptAccurate --> CallLLM2
    
    CallLLM2 -->|Thành công| PostProcess
    CallLLM2 -->|Gặp lỗi| FallbackMsg["Sử dụng FALLBACK_SUMMARY_MESSAGE"]
    FallbackMsg --> EndSpanAI["Kết thúc trace span"]
```

#### 4.4. Giai đoạn 3: Hậu xử lý, Bộ lọc Đầu ra & Đánh giá Độ trung thực (Output Guardrail & Fidelity Evaluation)
```mermaid
flowchart TD
    PostProcess[Nhận raw_response từ LLM] --> OutputFilter["Chạy post_process_output và filter_output để lọc PII và leak"]
    OutputFilter --> MatchSystemMsg{"Kết quả là OUT_OF_SCOPE hoặc NO_INFO?"}
    
    MatchSystemMsg -->|Đúng| RetDirect["Bỏ qua đánh giá, trả trực tiếp kết quả"]
    MatchSystemMsg -->|Sai| CheckJudge{"Có đánh giá reviews để đối chiếu không?"}
    
    CheckJudge -->|Không| RetDirect
    CheckJudge -->|Có| CallJudge["Gọi Giám khảo call_summary_judge để chấm điểm Fidelity"]
    
    CallJudge -->|Giám khảo gặp lỗi / Timeout| FallbackJudge["Ghi nhận lỗi & trả về thông báo lỗi hệ thống"]
    CallJudge -->|Giám khảo trả kết quả| CheckApprove{"Kết quả được duyệt approved == True ?"}
    
    CheckApprove -->|Không - Phát hiện ảo giác| RejectSummary["Ghi log lý do & trả về UNVERIFIED_SUMMARY_MESSAGE"]
    CheckApprove -->|Đúng - Trung thực| ApproveSummary["Ghi log duyệt & Trả về kết quả tóm tắt cho khách"]
    
    RetDirect --> FinishMetric["Tăng metric app_ai_assistant_counter"]
    FallbackJudge --> FinishMetric
    RejectSummary --> FinishMetric
    ApproveSummary --> FinishMetric
    
    FinishMetric --> EndSpanAI(["Trả về AskProductAIAssistantResponse"])
```

## Chi tiết các luồng xử lý chính

### 1. Luồng Lấy Đánh Giá & Điểm Số
* **`GetProductReviews`**: Truy vấn danh sách đánh giá từ cơ sở dữ liệu Postgres bằng hàm `fetch_product_reviews_from_db`, ghi nhận số lượng review nhận được vào OpenTelemetry metric `app_product_review_counter`, sau đó trả về danh sách dưới định dạng protobuf.
* **`GetAverageProductReviewScore`**: Truy vấn điểm đánh giá trung bình từ database và trả về.

### 2. Luồng Trợ lý AI (`AskProductAIAssistant`)
* **Bước 1: Bộ lọc đầu vào (Input Guardrail)**
  * Chạy `check_input` để kiểm tra câu hỏi từ khách hàng. Nếu phát hiện Prompt Injection hoặc nội dung không an toàn, hệ thống sẽ chặn ngay lập tức và trả về lý do chặn.
* **Bước 2: Xử lý nguồn dữ liệu & Lọc độc hại (Data Fetching & Review Filter)**
  * Khi truy vấn review từ cơ sở dữ liệu (cả ở luồng Bedrock hoặc OpenAI Tool), hệ thống sẽ duyệt qua từng review và chạy `check_input` để lọc các nội dung độc hại (như prompt injection chèn trong review) hoặc thông tin cá nhân nhạy cảm (PII). Nếu phát hiện, nội dung review sẽ được thay thế bằng thông báo cảnh báo an toàn.
* **Bước 3: Chống chịu sự cố & Mô hình hóa (Fault Tolerance & LLM Execution)**
  * Nếu dùng luồng OpenAI và Feature Flag `llmRateLimitError` được kích hoạt, hệ thống giả lập lỗi Rate Limit (429) với tỷ lệ 50% để kích hoạt cơ chế fallback.
  * Việc gọi mô hình Candidate (cả Bedrock và OpenAI) được bọc trong bộ xử lý lỗi `@with_fallback`. Nếu mô hình chính gặp sự cố hoặc quá tải, hệ thống sẽ tự động trả về `FALLBACK_SUMMARY_MESSAGE` thay vì bị treo hoặc crash.
* **Bước 4: Bộ lọc đầu ra (Output Guardrail)**
  * Kết quả trả về từ mô hình được xử lý thông qua hàm `post_process_output` và `filter_output` để lọc bỏ các từ khóa nhạy cảm, ngăn rò rỉ System Prompt hoặc phơi bày thông tin cá nhân.
* **Bước 5: Đánh giá độ trung thực (Fidelity Evaluation & Hallucination Guard)**
  * Đối với các tóm tắt thông thường (không phải trường hợp lạc đề hoặc thiếu thông tin), hệ thống sẽ kích hoạt một mô hình Giám khảo (`call_summary_judge`) để đối chiếu câu trả lời với các review nguồn gốc.
  * Nếu Giám khảo phát hiện câu trả lời chứa thông tin tự bịa (Hallucination) hoặc mâu thuẫn dữ liệu thật và từ chối (`approved = False`), hệ thống sẽ giấu nội dung này và trả về `UNVERIFIED_SUMMARY_MESSAGE` nhằm bảo vệ trải nghiệm của khách hàng.
