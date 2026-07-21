# Thiết Kế Phản Hồi Dạng Luồng (LLM Streaming Response)

Tài liệu này trình bày giải pháp kỹ thuật thiết kế API dạng luồng (Streaming API) cho dịch vụ AI Assistant của TechX Corp Platform nhằm tối ưu hóa thời gian hiển thị ký tự đầu tiên (Time to First Token - TTFT) và cải thiện trải nghiệm người dùng cuối.

---

## 1. Vấn Đề Cần Giải Quyết

Hiện tại, dịch vụ AI Assistant sử dụng cuộc gọi gRPC đồng bộ kiểu **Unary-Unary** (`AskProductAIAssistant` nhận một câu hỏi và trả về một câu trả lời duy nhất). 
* **Hạn chế**: Hệ thống bắt buộc phải chờ LLM sinh xong toàn bộ văn bản (mất khoảng **~1.5s - 2.0s**) rồi mới gửi phản hồi về client. Người dùng phải nhìn màn hình chờ xoay vòng trong suốt thời gian này, tạo cảm giác hệ thống bị chậm.
* **Giải pháp**: Sử dụng cơ chế Streaming. Ngay khi LLM sinh ra những từ đầu tiên (trong vòng **~100ms - 200ms**), hệ thống sẽ lập tức truyền từng từ này về giao diện người dùng.

---

## 2. Kiến Trúc gRPC Server-Side Streaming

Vì hệ thống TechX Corp Platform giao tiếp nội bộ giữa các microservice bằng gRPC, chúng ta sẽ chuyển đổi phương thức gRPC từ Unary sang **Server-side Streaming**:

```
[Storefront Browser] ◄─── (Server-Sent Events) ─── [frontend-proxy]
                                                         │
                                             (gRPC Response Stream)
                                                         ▼
                                              [product-reviews]
                                                         │
                                               (Chunk by Chunk Stream)
                                                         ▼
                                                 [AWS Bedrock]
```

### Thay đổi định nghĩa Protocol Buffers (`demo.proto`):
```protobuf
// Trước đây:
rpc AskProductAIAssistant(AskProductAIAssistantRequest) returns (AskProductAIAssistantResponse);

// Cải tiến sang Streaming:
rpc AskProductAIAssistantStream(AskProductAIAssistantRequest) returns (stream AskProductAIAssistantResponse);
```

---

## 3. Cách Thức Hoạt Động của Streaming trên Các Providers

### A. Luồng OpenAI (Qua LiteLLM hoặc Mock)
Khi gọi API của OpenAI, chúng ta thiết lập tham số `stream=True` và lặp qua iterator `response`:
```python
response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    stream=True
)
for chunk in response:
    content = chunk.choices[0].delta.content
    if content:
        yield content
```

### B. Luồng AWS Bedrock (Qua boto3)
Khi gọi trực tiếp AWS Bedrock qua `boto3`, chúng ta sử dụng phương thức `converse_stream` thay vì `converse`:
```python
response = bedrock_client.converse_stream(
    modelId=model_name,
    messages=messages
)
stream = response.get('stream')
if stream:
    for event in stream:
        # Nhận các sự kiện text chunk
        if 'contentBlockDelta' in event:
            text = event['contentBlockDelta']['delta']['text']
            yield text
```

---

## 4. Tích Hợp Vào product_reviews_server.py

Dưới đây là cấu trúc code Python đề xuất tích hợp vào class **[ProductReviewService](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L90)**:

```python
import demo_pb2
import demo_pb2_grpc

class ProductReviewService(demo_pb2_grpc.ProductReviewServiceServicer):
    
    def AskProductAIAssistantStream(self, request, context):
        logger.info(f"Receive AskProductAIAssistantStream for product id:{request.product_id}")
        
        # Hàm generator sinh dữ liệu chunk-by-chunk
        chunks_generator = get_ai_assistant_stream_response(request.product_id, request.question)
        
        for text_chunk in chunks_generator:
            # Kiểm tra nếu client ngắt kết nối giữa chừng (User đóng trình duyệt)
            if not context.is_active():
                logger.info("Client disconnected, stopping stream.")
                break
                
            response = demo_pb2.AskProductAIAssistantResponse()
            response.response = text_chunk
            yield response

def get_ai_assistant_stream_response(request_product_id, question):
    # Lấy danh sách reviews, chạy Guardrails lọc dữ liệu đầu vào...
    
    if llm_provider == "bedrock":
        response = bedrock_client.converse_stream(
            modelId=llm_model,
            messages=messages,
            system=[{"text": system_prompt}]
        )
        for event in response.get('stream', []):
            if 'contentBlockDelta' in event:
                yield event['contentBlockDelta']['delta']['text']
    else:
        response = openai_client.chat.completions.create(
            model=llm_model,
            messages=messages,
            stream=True
        )
        for chunk in response:
            delta_content = chunk.choices[0].delta.content
            if delta_content:
                yield delta_content
```

---

## 5. Xử Lý Caching và Guardrails với Streaming

Khi sử dụng Streaming, việc chạy Caching và Guardrails cần lưu ý:
1. **Input Guardrails (Lọc PII & Prompt Injection)**: Chạy bình thường trước khi mở luồng gọi API LLM.
2. **Output Guardrails (Content Moderation)**: Phải chạy theo cơ chế kiểm tra đệm (Buffer Window) hoặc bỏ qua kiểm tra đầu ra để ưu tiên độ trễ.
3. **Caching**: Khi luồng stream trả về thành công, hệ thống sẽ tự động ghép các `text_chunk` lại thành một chuỗi văn bản hoàn chỉnh trong bộ nhớ đệm (Buffer). Sau khi stream kết thúc, lưu chuỗi hoàn chỉnh này vào PostgreSQL/Redis làm cache cho lần sau.
