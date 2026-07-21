# Thiết Kế Cơ Chế Thử Lại và Trễ Lũy Thừa (LLM Retry & Exponential Backoff)

Tài liệu này mô tả chi tiết kiến trúc xử lý lỗi tạm thời (transient errors) khi gọi API LLM nhằm nâng cao tính sẵn sàng (Availability) và tính chống chịu lỗi (Resilience) của hệ thống TechX Corp Platform.

---

## 1. Vấn Đề Cần Giải Quyết

Khi chạy trên môi trường cloud thực tế, các cuộc gọi API tới nhà cung cấp LLM (như AWS Bedrock hoặc OpenAI) có thể thất bại ngẫu nhiên vì các sự cố tạm thời:
* **Lỗi mạng (Network Glitches)**: Rớt gói tin, timeout kết nối tạm thời.
* **Lỗi Rate Limit (HTTP 429)**: Throttling do vượt quá số lượng request/phút (TPM/RPM) được cấp phát trên AWS Bedrock.
* **Sự cố dịch vụ tạm thời (HTTP 500, 502, 503, 504)**: Quá tải phía server của nhà cung cấp LLM.

Nếu không có cơ chế Retry, hệ thống sẽ kích hoạt Fallback ngay lập tức hoặc trả về lỗi 500 cho khách hàng, làm suy giảm nghiêm trọng chất lượng dịch vụ (SLA).

---

## 2. Giải Pháp: Exponential Backoff với Jitter

Để tránh việc gửi dồn dập các request thử lại làm trầm trọng thêm tình trạng quá tải của nhà cung cấp LLM (Thundering Herd Problem), hệ thống áp dụng thuật toán **Trễ lũy thừa kèm nhiễu ngẫu nhiên (Exponential Backoff with Full Jitter)**.

### Công thức tính thời gian chờ (Backoff Delay):
$$\text{Delay} = \text{random}(0, \min(\text{max\_delay}, \text{base\_delay} \times 2^{\text{attempt}}))$$

### Các thông số cấu hình đề xuất:
* **`max_retries`**: `3` (Tổng số lần thử lại tối đa).
* **`base_delay`**: `1.0` giây (Thời gian chờ ban đầu).
* **`max_delay`**: `8.0` giây (Thời gian chờ tối đa).
* **`timeout`**: `10.0` giây (Hạn định thời gian cho mỗi cuộc gọi đơn lẻ).

---

## 3. Phân Loại Mã Lỗi Được Phép Retry

Hệ thống chỉ thực hiện thử lại đối với các lỗi mang tính chất **tạm thời** và bỏ qua các lỗi do sai lệch logic phía client:

| HTTP Status | Phân loại lỗi | Hành vi | Lý do |
| :--- | :--- | :--- | :--- |
| **429** | Rate Limit / Throttling | **RETRY** | Hạn mức tạm thời bị vượt quá, chờ đợi sẽ hết nghẽn. |
| **500, 502, 503, 504** | LLM Provider Server Error | **RETRY** | Sự cố hệ thống tạm thời phía nhà cung cấp. |
| **400, 422** | Bad Request / Invalid Schema | **NO RETRY** | Lỗi định dạng prompt hoặc tham số Tool. Retry sẽ luôn thất bại. |
| **401, 403** | Unauthorized / Authentication | **NO RETRY** | Sai API Key hoặc phân quyền IAM Role. Cần can thiệp thủ công. |

---

## 4. Tích Hợp Vào Kiến Trúc Graceful Fallback

Cơ chế Retry hoạt động như chốt chặn đầu tiên. Chỉ khi toàn bộ các lượt thử lại đều thất bại, hệ thống mới chính thức kích hoạt tầng xử lý dự phòng (Fallback):

```
[Request] ──► [Lần 1] ──► (Thành công?) ──► Có ──► [Trả kết quả]
                │
              Không (Lỗi 429/500)
                │
                ▼
        [Tính Delay Jitter] ──► [Chờ đợi (Sleep)]
                │
                ▼
              [Lần 2] ──► (Thành công?) ──► Có ──► [Trả kết quả]
                │
              Không (Đã đạt max_retries = 3?)
                │
               Có
                │
                ▼
       [KÍCH HOẠT FALLBACK]
        ├── Tầng 2: PostgreSQL Cache
        └── Tầng 3: Friendly Message
```

---

## 5. Minh Họa Logic Mã Nguồn Python Đề Xuất

Chúng ta sử dụng thư viện `tenacity` (một thư viện xử lý retry mạnh mẽ trong Python) để tích hợp vào tệp **[product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py)**:

```python
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log
)
import openai
import botocore.exceptions

logger = logging.getLogger('main')

# Định nghĩa các loại lỗi tạm thời được phép retry
def is_transient_error(exception):
    # Lỗi từ OpenAI Client
    if isinstance(exception, (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError)):
        return True
    
    # Lỗi từ AWS Boto3 Bedrock Client
    if isinstance(exception, botocore.exceptions.ClientError):
        error_code = exception.response.get('Error', {}).get('Code', '')
        # ThrottlingException (429) hoặc InternalServerError (500)
        if error_code in ['ThrottlingException', 'InternalServerError', 'ServiceUnavailableException']:
            return True
            
    return False

# Cấu hình Decorator Tenacity cho phép Exponential Backoff + Jitter
llm_retry_decorator = retry(
    reraise=True,
    stop=stop_after_attempt(3),  # Max 3 attempts
    wait=wait_exponential(multiplier=1, min=1, max=8),  # Wait 1s, 2s, 4s, 8s (with random jitter automatic)
    retry=retry_if_exception(is_transient_error),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)

# Áp dụng decorator vào hàm gọi LLM
@llm_retry_decorator
def execute_llm_call_with_retry(client, model, messages, tools=None):
    if isinstance(client, openai.OpenAI):
        return client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else None,
            timeout=10.0
        )
    else:
        # Gọi qua boto3 Bedrock Converse API
        return client.converse(
            modelId=model,
            messages=messages,
            toolConfig={"tools": tools} if tools else None,
            inferenceConfig={"temperature": 0.0, "maxTokens": 500}
        )
```
