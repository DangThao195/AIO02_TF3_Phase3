# Thiết Kế Bộ Nhớ Hội Thoại (LLM Conversation Memory)

Tài liệu này trình bày giải pháp thiết kế bộ nhớ hội thoại (Conversation Memory) cho dịch vụ AI Assistant của TechX Corp Platform nhằm chuyển đổi chatbot từ dạng hỏi đáp đơn lượt (Single-Turn Q&A) sang hội thoại đa lượt (Multi-Turn Conversation).

---

## 1. Vấn Đề Cần Giải Quyết

Hiện tại, dịch vụ AI Assistant hoạt động hoàn toàn **không lưu trạng thái (Stateless)**:
* Mỗi khi khách hàng gửi một câu hỏi lên gRPC handler, hệ thống chỉ khởi tạo một mảng `messages` chứa duy nhất System Prompt và câu hỏi hiện tại.
* Hệ thống không thể nhớ lại các câu hỏi hoặc câu trả lời trước đó trong cùng một phiên trò chuyện (Session). Ví dụ: Nếu người dùng hỏi *"Mặt hàng này có rẻ không?"* và sau đó hỏi *"Nó có màu gì?"*, AI sẽ không biết *"Nó"* đang ám chỉ sản phẩm nào ở câu hỏi trước.
* **Giải pháp**: Xây dựng một lớp quản lý lịch sử hội thoại (Conversation History) sử dụng **Redis** làm kho lưu trữ tập trung.

---

## 2. Kiến Trúc Lưu Trữ Bộ Nhớ Hội Thoại (Memory Backend)

Để đảm bảo khả năng mở rộng (Scalability) khi chạy trên môi trường cluster Kubernetes EKS gồm nhiều Pod bản sao của `product-reviews`, chúng ta không thể lưu lịch sử hội thoại trong bộ nhớ RAM của Pod (In-Memory).

Chúng ta sử dụng **Redis** làm database lưu trữ phân tán cho chat history:

```
[Storefront (Session ID)] ──► [EKS Load Balancer]
                                     │
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
            [product-reviews Pod 1]         [product-reviews Pod 2]
                     └───────────────┬───────────────┘
                                     ▼
                        [Redis Chat History Cache]
                        (TTL = 30 Phút, tự động dọn)
```

---

## 3. Chiến Lược Quản Lý Bộ Nhớ (Memory Strategies)

Để tránh tình trạng quá tải Context Window của LLM khi hội thoại kéo dài (khiến chi phí token tăng cao hoặc vượt giới hạn), hệ thống áp dụng chiến lược **Buffer Window Memory (Bộ nhớ cửa sổ trượt)** kết hợp **Tự động Tóm tắt (Summary Memory)**:

1. **Buffer Window Memory**: Chỉ lưu giữ tối đa `N` lượt hội thoại gần nhất (ví dụ: `N = 6` tin nhắn tương đương 3 lượt hỏi-đáp) ở dạng văn bản gốc.
2. **Conversation Summary (Tương lai)**: Đối với các cuộc hội thoại vượt quá `N` lượt, hệ thống sẽ kích hoạt một tiến trình ngầm (Background Task) dùng model LLM phụ (ví dụ: Bedrock Nova Micro) để tóm tắt lịch sử hội thoại cũ thành một đoạn văn ngắn gọn, giải phóng token nhưng vẫn giữ lại nội dung chính.

---

## 4. Tích Hợp Vào product_reviews_server.py

Dưới đây là cấu trúc mã nguồn Python đề xuất sử dụng thư viện `redis` để lưu trữ lịch sử hội thoại:

```python
import json
import redis
from typing import List, Dict, Any

# Kết nối tới dịch vụ Redis trong Cluster K8s (sử dụng thông tin từ env)
redis_host = os.environ.get('REDIS_HOST', 'redis')
redis_port = int(os.environ.get('REDIS_PORT', 6379))
redis_client = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)

# Định nghĩa TTL cho phiên trò chuyện: 30 phút (1800 giây)
SESSION_TTL_SECONDS = 1800
MAX_HISTORY_TURNS = 6  # Lưu tối đa 6 tin nhắn gần nhất

def load_conversation_history(session_id: str) -> List[Dict[str, str]]:
    """Tải lịch sử hội thoại từ Redis"""
    key = f"chat_history:{session_id}"
    try:
        raw_data = redis_client.get(key)
        if raw_data:
            return json.loads(raw_data)
    except Exception as e:
        logger.error(f"Failed to load chat history from Redis: {e}")
    return []

def save_conversation_history(session_id: str, messages: List[Dict[str, str]]):
    """Lưu lịch sử hội thoại vào Redis kèm thời gian hết hạn (TTL)"""
    key = f"chat_history:{session_id}"
    try:
        # Chỉ giữ lại tối đa MAX_HISTORY_TURNS tin nhắn gần nhất
        truncated_messages = messages[-MAX_HISTORY_TURNS:]
        redis_client.setex(
            key,
            SESSION_TTL_SECONDS,
            json.dumps(truncated_messages)
        )
    except Exception as e:
        logger.error(f"Failed to save chat history to Redis: {e}")
```

---

## 5. Tối Ưu Hóa Hàm get_ai_assistant_response Đa Lượt

Chúng ta điều chỉnh API để nhận thêm tham số `session_id` từ client, nạp lịch sử hội thoại trước khi gọi LLM và lưu lại lịch sử mới sau khi cuộc gọi thành công:

```python
def get_ai_assistant_response(request_product_id, question, session_id=None):
    # Khởi tạo danh sách messages ban đầu
    system_prompt = "You are a helpful assistant..."
    
    # 1. Nạp lịch sử hội thoại từ Redis (nếu có session_id)
    history_messages = []
    if session_id:
        history_messages = load_conversation_history(session_id)
    
    # 2. Xây dựng prompt người dùng hiện tại
    user_prompt = f"Answer the following question about product ID:{request_product_id}: {question}"
    
    # 3. Kết hợp: System Prompt + Lịch sử hội thoại + Câu hỏi mới nhất
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_prompt})

    # Chạy cuộc gọi LLM chính thức (Bedrock hoặc OpenAI)...
    # ...
    # Giả định kết quả trả về nằm ở biến `result`

    # 4. Cập nhật lịch sử mới vào Redis
    if session_id:
        # Thêm câu hỏi hiện tại và câu trả lời của AI vào lịch sử
        history_messages.append({"role": "user", "content": user_prompt})
        history_messages.append({"role": "assistant", "content": result})
        save_conversation_history(session_id, history_messages)

    return result
```
