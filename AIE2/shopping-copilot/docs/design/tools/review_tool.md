# Tool Spec — get_product_reviews_tool

> **File:** `tools/review_tool.py` | **Backend:** ProductReview gRPC | **Action:** Read

## ToolSpec Registration

```python
ToolSpec(
    name="get_product_reviews_tool",
    description="Lấy đánh giá thực tế của khách hàng cho một sản phẩm (điểm trung bình, phân bố điểm, các review chi tiết).",
    is_write=False,
    input_schema={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "ID của sản phẩm cần xem review"
            },
            "limit": {
                "type": "integer",
                "description": "Số lượng review tối đa (mặc định 10)",
                "default": 10
            },
            "sort": {
                "type": "string",
                "enum": ["newest", "highest", "lowest"],
                "description": "Cách sắp xếp review",
                "default": "newest"
            }
        },
        "required": ["product_id"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "error"]},
            "product_id": {"type": "string"},
            "product_name": {"type": "string"},
            "average_score": {"type": "number", "description": "Điểm trung bình (VD: 4.5)"},
            "total_reviews": {"type": "integer"},
            "distribution": {
                "type": "object",
                "properties": {
                    "1": {"type": "integer"},
                    "2": {"type": "integer"},
                    "3": {"type": "integer"},
                    "4": {"type": "integer"},
                    "5": {"type": "integer"}
                },
                "description": "Phân bố số lượng review theo từng điểm số"
            },
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "review_id": {"type": "integer"},
                        "username": {"type": "string"},
                        "score": {"type": "number"},
                        "body": {"type": "string"}
                    }
                }
            },
            "message": {"type": "string"}
        },
        "required": ["status", "product_id"]
    },
    examples=[
        {"input": {"product_id": "P001", "limit": 5},
         "output": {
            "status": "success",
            "product_id": "P001",
            "product_name": "Telescope XYZ",
            "average_score": 4.5,
            "total_reviews": 23,
            "distribution": {"5": 15, "4": 5, "3": 2, "2": 1, "1": 0},
            "reviews": [
                {"review_id": 1, "username": "astronomy_fan", "score": 5.0, "body": "Great telescope for beginners!"}
            ]
        }}
    ],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]}
)
```

## Backend Mapping

**gRPC Service:** `ProductReviewService` (`product-reviews:9090`)

| Tool Field | Proto Source | Notes |
|---|---|---|
| `product_id` | `GetProductReviewsResponse...` | Từ request param |
| `product_name` | JOIN `products` table | Lấy name từ products DB |
| `average_score` | Aggregate | AVG(score) |
| `total_reviews` | COUNT(*) | |
| `distribution` | GROUP BY score | `{1: N, 2: N, ...}` |
| `reviews[].review_id` | `ProductReview.review_id` | INTEGER auto-increment |
| `reviews[].username` | `ProductReview.username` | |
| `reviews[].score` | `ProductReview.score` | NUMERIC(2,1) |
| `reviews[].body` | `ProductReview.description` | **Rename**: `description` → `body` |

**Proto:** `demo.proto` → `GetProductReviewsRequest { product_id }` → `GetProductReviewsResponse { product_reviews[] { review_id, username, score, description } }`

## Error Handling

| Condition | `status` | `message` |
|---|---|---|
| gRPC error | `"error"` | `"Dịch vụ đánh giá tạm thời không khả dụng."` |
| No reviews found | `"success"` | `total_reviews=0, reviews=[]` |
| Invalid product_id | `"error"` | `"Mã sản phẩm không hợp lệ."` |
| Timeout (>2s) | `"error"` | `"Dịch vụ quá tải, vui lòng thử lại."` |

## Edge Cases

| Case | Behavior |
|---|---|
| Product has 0 reviews | `average_score=0`, `total_reviews=0`, `reviews=[]` |
| Product has 1 review | Array size 1, `distribution` chỉ có 1 score |
| Product không tồn tại | `status="error"`, message rõ |
| `limit > total` | Trả tất cả reviews có |
| `sort = "highest"` | Sắp xếp score giảm dần |
| `body` quá dài (>500 chars) | Giữ nguyên, không truncate |

## Examples for TGB Few-Shot

```json
{"query": "What do people say about the tent?", "intent": "review",
 "dag": [{"id": "n0", "tool": "search_products_v2", "depends_on": [], "confidence": 0.9},
         {"id": "n1", "tool": "get_product_reviews_tool", "depends_on": ["n0"], "confidence": 0.95}]}
```
