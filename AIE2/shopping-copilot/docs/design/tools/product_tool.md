# Tool Spec — get_product_details_tool

> **File:** `tools/product_tool.py` | **Backend:** ProductCatalog gRPC | **Action:** Read

## ToolSpec Registration

```python
ToolSpec(
    name="get_product_details_tool",
    description="Lấy chi tiết đầy đủ của một sản phẩm theo product_id (tên, giá, mô tả, hình ảnh, danh mục, đánh giá).",
    is_write=False,
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "ID của sản phẩm (VD: 'P001', 'OLJCESPC7Z')"
            }
        },
        "required": ["product_id"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "error"]},
            "product": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "price": {"type": "string", "description": "Đã normalize: '$99.99'"},
                    "description": {"type": "string"},
                    "image": {"type": "string", "description": "Tên file ảnh, consumer ghép CDN base URL"},
                    "categories": {"type": "array", "items": {"type": "string"}},
                    "rating": {"type": "number"},
                    "review_count": {"type": "integer"}
                }
            },
            "message": {"type": "string"}
        },
        "required": ["status"]
    },
    examples=[
        {"input": {"product_id": "P001"}, "output": {
            "status": "success",
            "product": {
                "id": "P001", "name": "Telescope XYZ",
                "price": "$199.99",
                "description": "Professional telescope for beginners",
                "image": "telescope_xyz.jpg",
                "categories": ["Outdoor", "Astronomy"],
                "rating": 4.5, "review_count": 23
            }
        }}
    ],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]}
)
```

## Backend Mapping

**gRPC Service:** `ProductCatalogService` (`product-catalog:3550`)

| Tool Field | Proto Source | Notes |
|---|---|---|
| `product.id` | `GetProductResponse.id` | |
| `product.name` | `GetProductResponse.name` | |
| `product.price` | `price_usd.units` + `price_usd.nanos` | **Normalize**: `"${units}.{nanos//10_000_000:02d}"` |
| `product.description` | `GetProductResponse.description` | |
| `product.image` | `GetProductResponse.picture` | **Rename**: `picture` → `image` |
| `product.categories` | `GetProductResponse.categories` | **Split**: comma-separated TEXT → array |
| `product.rating` | Aggregate từ `productreviews` | AVG(score) qua DB JOIN |
| `product.review_count` | COUNT từ `productreviews` | |

## Price Normalization

```python
def normalize_price(units: int, nanos: int) -> str:
    """Gộp units + nanos → price string."""
    cents = nanos // 10_000_000
    return f"${units}.{cents:02d}"
```

## Error Handling

| Condition | `status` | `message` |
|---|---|---|
| gRPC error (service unavailable) | `"error"` | `"Dịch vụ không khả dụng, vui lòng thử lại sau."` |
| Product not found | `"error"` | `"Không tìm thấy sản phẩm '{product_id}'."` |
| Invalid product_id format | `"error"` | `"Mã sản phẩm không hợp lệ."` |
| Timeout (>2s) | `"error"` | `"Dịch vụ tạm thời quá tải."` |

## Examples for TGB Few-Shot

```json
{"query": "Show details of product P001", "intent": "search",
 "dag": [{"id": "n0", "tool": "get_product_details_tool",
          "depends_on": [], "confidence": 0.95}]}

{"query": "Tell me about the telescope", "intent": "search",
 "dag": [{"id": "n0", "tool": "search_products_v2", "depends_on": [], "confidence": 0.9},
         {"id": "n1", "tool": "get_product_details_tool", "depends_on": ["n0"], "confidence": 0.85}]}
```
