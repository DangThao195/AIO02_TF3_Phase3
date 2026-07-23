# Tool Spec — Cart Tools

> **File:** `tools/cart_tool.py` | **Backend:** CartService gRPC | **Action:** Read + Write

---

## 1. get_cart_tool (Read)

### ToolSpec Registration

```python
ToolSpec(
    name="get_cart_tool",
    description="Xem danh sách sản phẩm trong giỏ hàng hiện tại của người dùng (tên, giá, số lượng, tổng tiền).",
    is_write=False,
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "ID của người dùng (lấy từ session)"
            }
        },
        "required": ["user_id"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "empty", "error"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "string", "description": "Đã normalize: '$99.99'"},
                        "quantity": {"type": "integer"},
                        "image": {"type": "string"}
                    }
                }
            },
            "subtotal": {"type": "string", "description": "Tổng tiền: '$199.98'"},
            "item_count": {"type": "integer"},
            "message": {"type": "string"}
        },
        "required": ["status"]
    },
    examples=[
        {"input": {"user_id": "user_abc123"},
         "output": {
            "status": "success",
            "items": [
                {"product_id": "P001", "name": "Telescope XYZ", "price": "$199.99", "quantity": 1, "image": "telescope.jpg"},
                {"product_id": "P002", "name": "Camping Stove", "price": "$49.99", "quantity": 2, "image": "stove.jpg"}
            ],
            "subtotal": "$299.97",
            "item_count": 3
        }}
    ],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]}
)
```

### Backend Mapping

**Proto:** `GetCartRequest { user_id }` → `GetCartResponse { items[] { product_id, quantity } }`

**Cần JOIN với ProductCatalog** để lấy `name` và `price` (cart table chỉ chứa `product_id` + `quantity`).

| Tool Field | Source | Notes |
|---|---|---|
| `items[].product_id` | Cart.items[].product_id | |
| `items[].name` | ProductCatalog.GetProduct | JOIN |
| `items[].price` | ProductCatalog price | Normalize |
| `items[].quantity` | Cart.items[].quantity | |
| `items[].image` | ProductCatalog picture | Rename |
| `subtotal` | Computed: SUM(price × quantity) | |
| `item_count` | SUM(quantity) | |

### Price Normalization

```python
# subtotal = sum of (price * quantity) for all items
# Mỗi item price: normalize units+nanos → "$units.cents"
# subtotal format: "$units.cents" (USD)
```

### Error Handling

| Condition | `status` | Output |
|---|---|---|
| Cart empty | `"empty"` | `items=[]`, `subtotal="$0.00"`, `item_count=0` |
| gRPC error | `"error"` | `message="Dịch vụ giỏ hàng không khả dụng."` |
| User not found | `"empty"` | Giỏ hàng mới, empty |

---

## 2. add_to_cart_tool (Write)

### ToolSpec Registration

```python
ToolSpec(
    name="add_to_cart_tool",
    description="Thêm sản phẩm vào giỏ hàng. Cần user confirm trước khi execute (write tool).",
    is_write=True,
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "ID sản phẩm cần thêm"},
            "quantity": {"type": "integer", "description": "Số lượng (mặc định 1)", "default": 1}
        },
        "required": ["product_id"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "confirmed", "denied", "error"]},
            "token": {"type": "string", "description": "HMAC token cho confirm (chỉ khi status=pending)"},
            "message": {"type": "string"},
            "item": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "name": {"type": "string"},
                    "price": {"type": "string"},
                    "quantity": {"type": "integer"}
                }
            }
        },
        "required": ["status"]
    },
    examples=[
        {"input": {"product_id": "P001", "quantity": 2},
         "output": {
            "status": "pending",
            "token": "eyJ...",
            "message": "Vui lòng xác nhận thêm 2 Telescope XYZ vào giỏ hàng.",
            "item": {"product_id": "P001", "name": "Telescope XYZ", "price": "$199.99", "quantity": 2}
        }}
    ],
    retry_config={"max_retries": 1, "backoff": [0.5]}
)
```

### Confirmation Flow (L4)

```
1. add_to_cart_tool được gọi bởi DAG Executor
2. Tool gọi request_confirmation(user_id, "AddItem", {product_id, quantity})
3. Nếu action bị DENIED (EmptyCart, PlaceOrder, Charge):
   → status="denied", không tạo token
4. Nếu action cần CONFIRM (AddItem):
   → Tạo HMAC token → status="pending", trả token
   → Graph PAUSE, chờ user POST /api/confirm
5. User confirm → Executor resume → gọi gRPC AddItem thật
   → status="confirmed", ghi kết quả vào tool_results
```

### Backend Mapping

**Proto:** `AddItemRequest { user_id, item { product_id, quantity } }` → cart gRPC

### Error Handling

| Condition | `status` | Message |
|---|---|---|
| quantity ≤ 0 | `"error"` | `"Số lượng phải lớn hơn 0."` |
| gRPC AddItem error | `"error"` | `"Không thể thêm sản phẩm vào giỏ hàng."` |
| Token expired (confirm) | `"error"` | `"Phiên xác nhận đã hết hạn."` |
| Confirm với user_id sai | `"error"` | `"Token không hợp lệ."` |

### Edge Cases

| Case | Behavior |
|---|---|
| Product đã có trong giỏ | CartService tự tăng quantity |
| quantity > 99 | L3 validate chặn (resource limit) |
| user_id không hợp lệ | gRPC error → status="error" |

### Examples for TGB Few-Shot

```json
{"query": "What's in my cart?", "intent": "cart_view",
 "dag": [{"id": "n0", "tool": "get_cart_tool",
          "depends_on": [], "confidence": 0.95}]}

{"query": "Add 2 tents to my cart", "intent": "cart_add",
 "dag": [{"id": "n0", "tool": "search_products_v2", "depends_on": [], "confidence": 0.9},
         {"id": "n1", "tool": "add_to_cart_tool", "depends_on": ["n0"], "confidence": 0.85}]}

{"query": "Add 3 of the camping stove to cart", "intent": "cart_add",
 "dag": [{"id": "n0", "tool": "search_products_v2", "depends_on": [], "confidence": 0.9},
         {"id": "n1", "tool": "add_to_cart_tool", "depends_on": ["n0"], "confidence": 0.9}]}
```
