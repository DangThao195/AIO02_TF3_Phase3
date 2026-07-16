Với hệ thống hiện tại, **LangChain ReAct Agent không còn là lựa chọn tối ưu**. Tài liệu thiết kế đang phụ thuộc vào:

* System Prompt để quyết định tool.
* ReAct loop của LangChain.
* `bind_tools()` để sinh tool call.

Điều này có 4 hạn chế lớn:

1. Không kiểm soát được khi nào model được phép gọi tool.
2. Khó bắt buộc workflow nhiều bước (product name → id → reviews → recommend...).
3. Khó cache và retry từng bước.
4. Business logic bị nhét vào prompt.

Đối với Shopping Copilot, **LangGraph phù hợp hơn vì graph chính là business logic** chứ không phải prompt.

---

# Kiến trúc đề xuất

```
                  User
                    │
             Input Guardrail
                    │
           Intent Classifier
                    │
      ┌─────────────┼─────────────┐
      │             │             │
 Search Flow    Cart Flow    Shipping Flow
      │             │             │
      └─────────────┼─────────────┘
                    │
           Response Generator
                    │
          Output Guardrail
```

LLM không còn quyết định workflow.

LLM chỉ làm:

* hiểu ý định
* trích entity
* sinh câu trả lời cuối.

Workflow được quyết định hoàn toàn bởi Graph.

---

# Chia graph thành các node

```
START

↓

InputGuard

↓

IntentClassifier

↓

Router

↓

SearchWorkflow
CartWorkflow
ReviewWorkflow
RecommendationWorkflow
ShippingWorkflow

↓

AnswerGenerator

↓

END
```

---

# State

```python
class ShoppingState(TypedDict):

    messages: list

    intent: str

    entities: dict

    tool_results: dict

    current_product_id: str | None

    candidate_products: list

    final_answer: str

    user_id: str

    session_id: str
```

Graph chỉ truyền State.

---

# Intent node

LLM chỉ làm classification.

Ví dụ:

```
User:
Recommend me a laptop.

↓

{
    intent:"recommend",
    product_name:"laptop"
}
```

Không gọi tool.

---

# Entity Extraction node

Ví dụ

```
"I need an iPhone 15"

↓

{
 product_name:"iphone 15"
}
```

---

# Router

```
recommend
↓

RecommendationGraph
```

```
review
↓

ReviewGraph
```

```
cart

↓

CartGraph
```

Không cần prompt để chọn tool.

---

# Recommendation Graph

Đây là phần LangGraph mạnh nhất.

Workflow:

```
User

↓

Extract Product Name

↓

Search Product

↓

Có đúng 1 sản phẩm?
```

Nếu

YES

↓

Save ProductID

↓

Recommendation Tool

↓

Generate Answer

Nếu

NO

↓

Disambiguation

↓

END

Graph:

```
START

↓

ExtractName

↓

SearchProduct

↓

Decision

──────────────┐
              │
FoundOne      │Many
              │
              ▼
GetProductID  AskUser
      │
      ▼
RecommendationTool
      │
      ▼
GenerateAnswer
```

Không cần model suy nghĩ.

---

# Ví dụ

User:

```
Recommend accessories for iPhone 15
```

Graph:

```
Extract

↓

iphone 15

↓

search_product()

↓

[
 id=P123
]

↓

recommend(P123)

↓

response
```

Không hề có ReAct loop.

---

# Workflow nhiều bước

Ví dụ:

```
Show me reviews of products similar to Galaxy S25
```

Graph:

```
Extract

↓

Galaxy S25

↓

SearchProduct

↓

GetProductID

↓

RecommendationTool

↓

Loop

For each recommendation

↓

ReviewTool

↓

Aggregate

↓

Generate
```

Workflow:

```
Product Name

↓

Product ID

↓

Recommend

↓

Review

↓

Final Answer
```

---

# LangGraph Loop

LangGraph hỗ trợ loop rất tốt.

Ví dụ:

```
recommend()

↓

10 products

↓

FOR

↓

review(product)

↓

collect

↓

END LOOP

↓

LLM Summary
```

Không cần model tự gọi tool 10 lần.

---

# Conditional Edge

Ví dụ:

```
SearchProduct

↓

0 result

↓

Semantic Search
```

```
SearchProduct

↓

1 result

↓

Recommendation
```

```
SearchProduct

↓

>1

↓

Ask User
```

Graph:

```
Search

↓

───────────────
│     │      │
0     1      N
│     │      │
│     │      Ask
│     │
Semantic
      │
 Recommend
```

---

# Tool Executor Node

Toàn bộ tool đều đi qua một node.

```
ToolExecutor
```

Input

```
tool_name

arguments
```

Output

```
result
```

Trong node này:

```
Validate

↓

Retry

↓

Cache

↓

Call gRPC

↓

Store Result
```

Business logic không nằm trong prompt nữa.

---

# Multi-step Workflow Template

Ví dụ một workflow chuẩn:

```
User

↓

Extract Entity

↓

Normalize

↓

Search Product

↓

Select Product

↓

Get ProductID

↓

Recommendation

↓

Review

↓

Ranking

↓

Generate
```

---

# Cart Workflow

```
User

↓

Extract

↓

Search

↓

ProductID

↓

Stock Check

↓

Need Confirmation?

↓

Yes

↓

Pending

↓

Confirm

↓

Add Cart

↓

Generate
```

L4 Confirmation vẫn giữ nguyên.

---

# Shipping Workflow

```
Extract Address

↓

Search Product

↓

Weight

↓

Shipping Tool

↓

Currency Tool

↓

Generate
```

---

# Một số workflow nên hard-code

## 1. Recommendation

```
ProductName
↓

ProductID
↓

Recommendation
```

---

## 2. Review

```
ProductName

↓

ProductID

↓

Review
```

---

## 3. Add Cart

```
ProductName

↓

ProductID

↓

Stock

↓

Confirmation

↓

Cart
```

---

## 4. Shipping

```
Product

↓

Weight

↓

Shipping

↓

Currency
```

---

## 5. Price Conversion

```
Product

↓

Price

↓

Currency
```

---

## 6. Compare Products

```
Extract Products

↓

Search A

↓

Search B

↓

Product IDs

↓

Detail Tool

↓

Compare
```

---

# Hybrid Agent

Không nên loại bỏ hoàn toàn khả năng agent tự quyết định. Thay vào đó, chia hệ thống thành hai lớp:

```
                  LangGraph
                      │
        ┌─────────────┴─────────────┐
        │                           │
 Deterministic Workflow      Agent Workflow
```

* **Deterministic Workflow (80–90% request):** Các nghiệp vụ đã biết (search, review, recommendation, cart, shipping...) được điều phối bằng LangGraph với các node và conditional edge cố định.
* **Agent Workflow (10–20% request):** Chỉ dùng khi yêu cầu mở, không khớp workflow định nghĩa sẵn, ví dụ: "Hãy tìm một chiếc laptop phù hợp cho sinh viên, ngân sách 20 triệu và giải thích vì sao". Lúc này mới chuyển sang một agent có quyền lập kế hoạch và gọi tool.

Nhờ vậy:

* Workflow quan trọng luôn có thể dự đoán, kiểm thử và tối ưu.
* LLM chỉ được trao quyền lập kế hoạch khi thật sự cần.
* Prompt đơn giản hơn, business logic nằm trong graph thay vì trong system prompt.
* Có thể bổ sung cache, retry, logging, telemetry và guardrail ở từng node độc lập.

Đây là mô hình thường được áp dụng trong các hệ thống production vì kết hợp được tính ổn định của workflow với tính linh hoạt của agent.
