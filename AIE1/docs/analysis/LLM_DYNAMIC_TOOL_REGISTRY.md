# Thiết Kế Đăng Ký Công Cụ Động (Dynamic Tool Registry)

Tài liệu này mô tả thiết kế hệ thống đăng ký và điều phối công cụ động (Dynamic Tool Registry & Dispatcher) cho dịch vụ AI Assistant của TechX Corp Platform nhằm tối ưu hóa cấu trúc mã nguồn, tăng tính mở rộng (Scalability) và dễ bảo trì khi số lượng tool tăng lên.

---

## 1. Vấn Đề Cần Giải Quyết

Hiện tại, trong tệp **[product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py#L244-L257)**, quá trình thực thi các hàm cục bộ (Tool Execution) được lập trình cứng (Hard-coded) bằng cấu trúc rẽ nhánh `if/elif/else`:

```python
if function_name == "fetch_product_reviews":
    function_response = fetch_product_reviews(product_id=function_args.get("product_id"))
elif function_name == "fetch_product_info":
    function_response = fetch_product_info(product_id=function_args.get("product_id"))
else:
    raise Exception(f'Received unexpected tool call request: {function_name}')
```

### Hạn chế:
* **Khó mở rộng (Violates Open-Closed Principle)**: Mỗi khi thêm mới một Tool (ví dụ: `check_inventory`, `calculate_shipping_fee`), lập trình viên bắt buộc phải nhảy vào chỉnh sửa trực tiếp logic rẽ nhánh bên trong hàm `get_ai_assistant_response`.
* **Rườm rà và dễ lỗi**: Số lượng code phình to tỉ lệ thuận với số lượng tool, tạo ra các khối lệnh điều phối cồng kềnh, dễ dẫn đến lỗi gõ sai tên hàm hoặc tham số.

---

## 2. Giải Pháp: Dynamic Tool Registry Pattern

Chúng ta xây dựng một lớp **`ToolRegistry`** đóng vai trò quản lý trung tâm. Lớp này cung cấp:
1. **Decorator `@register_tool`**: Giúp tự động đăng ký bất kỳ hàm Python nào thành một AI Tool.
2. **Dynamic Dispatcher (Bộ điều phối động)**: Tự động tra cứu hàm bằng tên dạng chuỗi ký tự (`string`), nạp tham số dạng JSON và thực thi hàm một cách tự động.

### Sơ đồ hoạt động:
```
[Hàm Python] ──► Đánh dấu @register_tool ──► [ToolRegistry] (Lưu ánh xạ)
                                                    │
[LLM Tool Call Request] ────► [Dispatcher Lookup] ──┘
                                    │
                            (Thực thi động)
                                    ▼
                         [Kết quả trả về cho LLM]
```

---

## 3. Kiến Trúc và Thiết Kế Mã Nguồn Chi Tiết

Dưới đây là mã nguồn đề xuất để cấu trúc lại phần quản lý tool trong dịch vụ `product-reviews`:

```python
import json
import inspect
from typing import Callable, Dict, List, Any

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: List[Dict[str, Any]] = []

    def register(self, name: str, description: str, parameters_schema: Dict[str, Any]):
        """Decorator đăng ký một hàm Python làm AI Tool"""
        def decorator(func: Callable):
            self._tools[name] = func
            # Tự động tạo và lưu trữ OpenAI Tool Schema
            self._schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters_schema
                }
            })
            return func
        return decorator

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Lấy danh sách schemas cho OpenAI"""
        return self._schemas

    def get_bedrock_tools(self) -> List[Dict[str, Any]]:
        """Tự động chuyển đổi và lấy danh sách schemas cho AWS Bedrock"""
        bedrock_tools = []
        for tool in self._schemas:
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

    def dispatch(self, name: str, arguments: Dict[str, Any]) -> str:
        """Tìm kiếm hàm động và thực thi với các tham số tương ứng"""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered in ToolRegistry.")
        
        func = self._tools[name]
        logger.info(f"Dynamically dispatching tool call to: {name}")
        
        # Thực thi hàm
        result = func(**arguments)
        
        # Đảm bảo kết quả trả về luôn là string
        if not isinstance(result, str):
            result = json.dumps(result)
        return result

# Khởi tạo đối tượng registry toàn cục
registry = ToolRegistry()
```

---

## 4. Cách Sử Dụng Đăng Ký Tool Mới

Lập trình viên chỉ cần sử dụng decorator để đăng ký các hàm nghiệp vụ, không cần sửa đổi bất kỳ dòng code điều phối nào:

```python
# Đăng ký tool fetch_product_reviews
@registry.register(
    name="fetch_product_reviews",
    description="Executes a SQL query to retrieve reviews for a particular product.",
    parameters_schema={
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "The product ID."}
        },
        "required": ["product_id"]
    }
)
def fetch_product_reviews(product_id: str) -> str:
    # Logic kết nối Postgres để lấy reviews...
    return json.dumps(records)

# Đăng ký một tool mới bất kỳ (Ví dụ: kiểm tra kho)
@registry.register(
    name="check_inventory",
    description="Check stock quantity for a specific product ID.",
    parameters_schema={
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "The product ID."}
        },
        "required": ["product_id"]
    }
)
def check_inventory(product_id: str) -> str:
    # Logic gọi sang catalog service để check kho...
    return json.dumps({"product_id": product_id, "in_stock": True, "quantity": 42})
```

---

## 5. Tối Ưu Hóa Hàm Xử Lý Tool Gọi Trong get_ai_assistant_response

Hàm xử lý cuộc gọi Tool ở turn 2 trong **[product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py)** sẽ được rút gọn cực kỳ ngắn gọn và sạch sẽ:

```python
        # Xử lý tất cả các Tool Calls động qua ToolRegistry
        if tool_calls:
            messages.append(response_message)

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                try:
                    # Tra cứu và gọi hàm động bằng Dispatcher
                    function_response = registry.dispatch(function_name, function_args)
                except Exception as e:
                    logger.error(f"Error executing tool {function_name}: {e}")
                    function_response = json.dumps({"error": f"Failed to execute tool: {str(e)}"})

                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )
```
*(Nếu sử dụng AWS Bedrock, logic dispatch cũng diễn ra tương tự bằng cách sử dụng `toolUseId` và cấu trúc `toolResult` của Bedrock).*
