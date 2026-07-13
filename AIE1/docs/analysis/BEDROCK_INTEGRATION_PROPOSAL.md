# Đề Xuất Kỹ Thuật: Tích Hợp Trực Tiếp AWS Bedrock SDK (boto3) Song Song OpenAI (Dual-Engine LLM Routing)

Tài liệu này trình bày giải pháp cải tiến mã nguồn cho dịch vụ `product-reviews` nhằm hỗ trợ song song hai cơ chế gọi LLM (OpenAI Client và AWS boto3 SDK), được cấu hình linh hoạt thông qua biến môi trường.

---

## 1. Bối cảnh & Mục tiêu

* **Hiện tại (Tuần 1)**: Dịch vụ [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/techx-corp-platform/src/product-reviews/product_reviews_server.py) gọi LLM thông qua thư viện `OpenAI`. Khi chạy EKS Cluster thực tế, hệ thống phải duy trì một Pod proxy trung gian (LiteLLM) để dịch chuyển tham số sang Bedrock API.
* **Mục tiêu (Tuần 2)**: Tích hợp trực tiếp SDK `boto3` của AWS để loại bỏ LiteLLM Proxy trên EKS, từ đó **tối ưu hóa độ trễ (Latency)** và **tăng độ tin cậy hệ thống**.
* **Nguyên tắc cốt lõi**: **Giữ lại mã nguồn OpenAI cũ** để tương thích ngược. Sử dụng biến môi trường `LLM_PROVIDER` để tự động định tuyến (Routing) luồng xử lý.

---

## 2. Kiến trúc Định tuyến (Dual-Engine Routing)

Chúng ta bổ sung thêm biến môi trường `LLM_PROVIDER` với hai chế độ:

1. **`LLM_PROVIDER="openai"`** (Mặc định): Hệ thống khởi tạo và sử dụng `OpenAI` client để kết nối tới các OpenAI-compatible endpoints (như LiteLLM Local, Groq, hoặc OpenAI API).
2. **`LLM_PROVIDER="bedrock"`**: Hệ thống khởi tạo và sử dụng `boto3` client để kết nối trực tiếp tới dịch vụ AWS Bedrock Runtime trên EKS (sử dụng IAM Roles for Service Accounts - IRSA).

---

## 3. Sự khác biệt kỹ thuật giữa OpenAI và Bedrock Converse API

Để hai luồng hoạt động song song không xung đột, hệ thống cần xử lý sự khác biệt về định dạng cấu trúc dữ liệu:

### A. Cấu trúc định nghĩa Tool (Tool Specification Schema)
* **OpenAI**: Định dạng `function`.
* **AWS Bedrock**: Định dạng `toolSpec` và nhận schema tham số qua thuộc tính `inputSchema`.
* **Giải pháp**: Viết hàm chuyển đổi tự động `convert_openai_tools_to_bedrock()` trong code để tái sử dụng danh sách tool hiện tại, tránh định nghĩa trùng lặp.

### B. Định dạng tin nhắn gửi kết quả của Tool (Tool Result Message)
* **OpenAI**: Gửi tin nhắn có `role: "tool"` kèm `tool_call_id`.
* **Bedrock**: Gửi tin nhắn có `role: "user"` chứa một danh sách `toolResult` bên trong block `content`.

---

## 4. Chi tiết đề xuất thay đổi mã nguồn

### Thay đổi 1: Thêm thư viện vào [requirements.txt](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/techx-corp-platform/src/product-reviews/requirements.txt)
Thêm thư viện `boto3` để container build nạp được SDK:
```diff
 psycopg2-binary==2.9.11
 openai==2.14.0
+boto3==1.34.140
 simplejson==3.20.2
```

### Thay đổi 2: Khởi tạo Client trong [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/techx-corp-platform/src/product-reviews/product_reviews_server.py)
```python
import boto3

llm_provider = os.environ.get("LLM_PROVIDER", "openai").lower()

if llm_provider == "bedrock":
    # Boto3 tự động nạp AWS credentials tạm thời từ EKS ServiceAccount
    bedrock_client = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
else:
    openai_client = OpenAI(base_url=llm_base_url, api_key=llm_api_key)
```

### Thay đổi 3: Viết hàm tự động chuyển đổi Tool Schema
```python
def convert_openai_tools_to_bedrock(openai_tools):
    bedrock_tools = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            func = tool["function"]
            bedrock_tools.append({
                "toolSpec": {
                    "name": func["name"],
                    "description": func["description"],
                    "inputSchema": {
                        "json": func["parameters"]
                    }
                }
            })
    return bedrock_tools
```

### Thay đổi 4: Phân nhánh gRPC Handler `get_ai_assistant_response`
Chúng ta tạo ra hai luồng xử lý riêng biệt dựa trên `llm_provider`:

```python
def get_ai_assistant_response(request_product_id, question):
    if llm_provider == "bedrock":
        # ==========================================
        # LUỒNG 1: GỌI TRỰC TIẾP AWS BEDROCK (boto3)
        # ==========================================
        bedrock_tools = convert_openai_tools_to_bedrock(tools)
        
        # Thiết lập messages ban đầu
        system_prompt = "You are a helpful assistant..."
        user_prompt = f"Answer the following question about product ID:{request_product_id}: {question}"
        
        messages = [
            {"role": "user", "content": [{"text": user_prompt}]}
        ]
        
        # Turn 1: Gọi Bedrock Converse
        response = bedrock_client.converse(
            modelId=llm_model,  # Ví dụ: us.amazon.nova-lite-v1:0
            messages=messages,
            system=[{"text": system_prompt}],
            inferenceConfig={"temperature": 0},
            toolConfig={"tools": bedrock_tools}
        )
        
        output_message = response["output"]["message"]
        messages.append(output_message)
        
        # Xử lý gọi Tool nếu Bedrock yêu cầu
        if "toolUse" in output_message.get("content", [{}])[0]:
            tool_requests = [c["toolUse"] for c in output_message["content"] if "toolUse" in c]
            tool_results = []
            
            for tool_req in tool_requests:
                func_name = tool_req["name"]
                func_args = tool_req["input"]
                
                # Thực thi hàm DB tương ứng
                if func_name == "fetch_product_reviews":
                    func_res = fetch_product_reviews(product_id=func_args.get("product_id"))
                elif func_name == "fetch_product_info":
                    func_res = fetch_product_info(product_id=func_args.get("product_id"))
                
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tool_req["toolUseId"],
                        "content": [{"json": {"result": func_res}}],
                        "status": "success"
                    }
                })
            
            # Gửi kết quả Tool dưới vai trò user (Bắt buộc theo chuẩn Bedrock)
            messages.append({
                "role": "user",
                "content": tool_results
            })
            
            # Turn 2: Lấy tóm tắt cuối cùng
            final_response = bedrock_client.converse(
                modelId=llm_model,
                messages=messages,
                system=[{"text": system_prompt}]
            )
            result = final_response["output"]["message"]["content"][0]["text"]
            
        else:
            result = output_message["content"][0]["text"]
            
        ai_assistant_response.response = result
        return ai_assistant_response

    else:
        # ==========================================
        # LUỒNG 2: GIỮ NGUYÊN CODE OPENAI CŨ
        # ==========================================
        # (Không thay đổi bất kỳ dòng nào của mã nguồn OpenAI cũ để bảo toàn tính ổn định)
```

---

## 5. Thay đổi cấu hình Deploy [deploy/values-aio-llm.yaml](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/deploy/values-aio-llm.yaml)

Sau khi code được cập nhật, file Helm values sẽ được tinh giản tối đa, không cần trỏ qua proxy:

```yaml
# deploy/values-aio-llm.yaml
components:
  product-reviews:
    envOverrides:
      - name: LLM_PROVIDER
        value: bedrock                        # Đổi chế độ định tuyến sang Bedrock
      - name: LLM_MODEL
        value: us.amazon.nova-lite-v1:0        # Gọi trực tiếp qua cross-region profile của AWS
      - name: AWS_REGION
        value: us-east-1
```
*(Nếu EKS cluster đã được phân quyền qua IRSA, chúng ta hoàn toàn không cần khai báo `OPENAI_API_KEY` hay các AWS Access Key nữa, EKS sẽ tự động nạp Token xác thực tạm thời).*
