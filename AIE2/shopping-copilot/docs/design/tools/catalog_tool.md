# Tool Spec — Catalog Utility Tools

> **File:** `tools/catalog_tool.py`, `tools/product_id_tool.py` | **Backend:** SQLite/PostgreSQL | **Action:** Read

---

## 1. get_categories

### ToolSpec Registration

```python
ToolSpec(
    name="get_categories",
    description="Lấy danh sách tất cả danh mục sản phẩm hiện có trong hệ thống.",
    is_write=False,
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "empty", "error"]},
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Danh sách danh mục (sorted A-Z)"
            },
            "total": {"type": "integer"},
            "message": {"type": "string"}
        },
        "required": ["status"]
    },
    examples=[
        {"input": {},
         "output": {
            "status": "success",
            "categories": ["Astronomy", "Camping", "Outdoor"],
            "total": 3
        }}
    ],
    retry_config={"max_retries": 2, "backoff": [0.5]}
)
```

### Backend
```sql
SELECT DISTINCT categories FROM products
WHERE categories IS NOT NULL AND categories != ''
ORDER BY categories
```
Parse comma-separated categories → unique, sorted array.

### Error Handling
| Condition | `status` | Message |
|---|---|---|
| DB error | `"error"` | `"Dịch vụ không khả dụng."` |
| No categories | `"empty"` | `categories=[]` |

---

## 2. get_all_products

### ToolSpec Registration

```python
ToolSpec(
    name="get_all_products",
    description="Lấy toàn bộ danh sách sản phẩm (CHỈ dùng khi user yêu cầu 'tất cả sản phẩm' — không dùng để tìm kiếm).",
    is_write=False,
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "empty", "error"]},
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "string"},
                        "description": {"type": "string"},
                        "categories": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            "total": {"type": "integer"},
            "message": {"type": "string"}
        },
        "required": ["status"]
    },
    examples=[
        {"input": {},
         "output": {
            "status": "success",
            "products": [
                {"id": "P001", "name": "Telescope XYZ", "price": "$199.99",
                 "description": "...", "categories": ["Outdoor", "Astronomy"]}
            ],
            "total": 1
        }}
    ],
    retry_config={"max_retries": 2, "backoff": [0.5]}
)
```

### Backend
```sql
SELECT id, name, description, categories, price_units, price_nanos
FROM products ORDER BY name
LIMIT 100
```

### Resource Limit
| Limit | Value |
|---|---|
| Max products returned | 100 |

---

## 3. get_product_id

### ToolSpec Registration

```python
ToolSpec(
    name="get_product_id",
    description="Tra cứu mã product_id từ tên sản phẩm chính xác. Dùng khi cần product_id để gọi tool khác.",
    is_write=False,
    input_schema={
        "type": "object",
        "properties": {
            "product_name": {
                "type": "string",
                "description": "Tên sản phẩm chính xác (VD: 'Telescope XYZ')"
            }
        },
        "required": ["product_name"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "not_found", "error"]},
            "product_id": {"type": "string", "description": "ID của sản phẩm (VD: 'P001')"},
            "product_name": {"type": "string"},
            "message": {"type": "string"}
        },
        "required": ["status"]
    },
    examples=[
        {"input": {"product_name": "Telescope XYZ"},
         "output": {
            "status": "success",
            "product_id": "P001",
            "product_name": "Telescope XYZ"
        }}
    ],
    retry_config={"max_retries": 2, "backoff": [0.5]}
)
```

### Backend
```sql
SELECT id FROM products WHERE name = %s
```

### v3.2 Note
Trong v3.2, `get_product_id` ít cần hơn vì **Executor resolve product_id tự động**:
- `search_products_v2` trả về `products[].id`
- `planner_memory.last_product_id` lưu ID đã dùng
- Intent Parser + Executor resolve entity tại runtime

Giữ tool này cho case đặc biệt khi planner cần lookup explicit.

### Error Handling
| Condition | `status` | Message |
|---|---|---|
| No product found | `"not_found"` | `"Không tìm thấy sản phẩm '{name}'."` |
| DB error | `"error"` | `"Dịch vụ không khả dụng."` |
| Empty name | `"error"` | `"Vui lòng nhập tên sản phẩm."` |
