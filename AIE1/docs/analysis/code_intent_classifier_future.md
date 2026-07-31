# Code Intent Classifier proposal for Product Reviews AI

## 1. Hiện tại hệ thống đang có gì?

Hiện tại hệ thống chưa có một lớp `Code Intent Classifier` riêng biệt.

Những gì đang có:

```text
1. routing.py
   - Bắt off-topic rất rõ bằng rule/regex.
   - Ví dụ: toàn số, hello thuần, code/weather/math rõ ràng.

2. answer_deterministic_planned_question()
   - Bắt một số intent chắc chắn sau khi câu hỏi đã qua routing.
   - Ví dụ: price, rating, negative review count, exact ingredient, drawback, quality.

3. Candidate LLM
   - Xử lý câu hỏi mở hoặc câu hỏi planner không chắc.

4. Runtime Judge
   - Kiểm tra factual grounding/fidelity của câu trả lời.
```

Điểm còn thiếu:

```text
Chưa có một bước trung tâm để hiểu intent/noise của user trước khi quyết định route.
```

Ví dụ chưa có hàm kiểu:

```python
classify_user_intent(question) -> {
    "is_product_related": bool,
    "intent": str,
    "normalized_question": str,
    "confidence": float,
    "noise_removed": str,
    "route_hint": str,
}
```

## 2. Code Intent Classifier giúp được gì?

Code classifier giúp tách rõ hai việc:

```text
1. Hiểu user đang muốn hỏi gì.
2. Trả lời factual content từ product/reviews.
```

Classifier chỉ làm bước 1. Nó không trả lời facts.

### Ví dụ 1: noise/greeting

Input:

```text
hello 123
```

Classifier output:

```json
{
  "is_product_related": false,
  "intent": "noise_or_greeting",
  "normalized_question": "",
  "confidence": 0.95,
  "noise_removed": "hello 123",
  "route_hint": "out_of_scope"
}
```

Runtime response:

```text
This question is out of scope. I only answer questions related to the product.
```

### Ví dụ 2: noise + product intent

Input:

```text
hello 123 review sản phẩm này tốt không
```

Classifier output:

```json
{
  "is_product_related": true,
  "intent": "review_sentiment",
  "normalized_question": "What do reviews say about this product?",
  "confidence": 0.85,
  "noise_removed": "hello 123",
  "route_hint": "candidate_llm_with_judge"
}
```

Runtime:

```text
Cho đi tiếp vào Candidate LLM + Judge.
```

### Ví dụ 3: self-introduction + price intent

Input:

```text
tôi là Thịnh cho tôi biết giá sản phẩm này
```

Classifier output:

```json
{
  "is_product_related": true,
  "intent": "price_question",
  "normalized_question": "What is the product price?",
  "confidence": 0.95,
  "noise_removed": "tôi là Thịnh",
  "route_hint": "deterministic_price_planner"
}
```

Runtime:

```text
Đi deterministic price planner, lấy giá từ Product Catalog.
```

## 3. Nó cải thiện vấn đề gì?

### 3.1. Giảm false block do regex quá cứng

Trước đây các rule kiểu:

```text
tôi là ...
```

có thể block nhầm câu:

```text
tôi là Thịnh hãy cho tôi biết sản phẩm này có review tiêu cực nào không
```

Code classifier sẽ hiểu:

```text
"tôi là Thịnh" = noise/self-introduction
"review tiêu cực" = product-review intent
```

Nên câu này không bị block nhầm.

### 3.2. Giảm request rác lọt vào LLM

Các câu như:

```text
hello 123
423942178483764873243287
???
ok ok
```

nên bị classify là:

```text
noise_or_greeting
meaningless_input
```

và trả `OUT_OF_SCOPE`, không gọi Candidate LLM.

### 3.3. Giúp prompt bớt cứng

Hiện prompt phải làm quá nhiều việc:

```text
hiểu intent
lọc noise
trả lời grounded
không bịa
không echo câu hỏi
```

Nếu classifier hiểu intent trước, Candidate chỉ cần xử lý:

```text
normalized_question + grounded context
```

Điều này giảm áp lực lên prompt và giảm tình trạng model trả `NO_INFO` quá nhiều.

### 3.4. Giảm hallucination cho facts chắc chắn

Nếu classifier nhận ra:

```text
price_question
review_count
average_rating
negative_review_count
```

runtime có thể đưa thẳng sang deterministic planner.

Facts sẽ được lấy bằng code từ:

```text
Product Catalog
review scores
trusted_review_facts
```

thay vì để LLM tự sinh.

### 3.5. Debug dễ hơn

Trace/artifact có thể ghi:

```json
{
  "intent": "price_question",
  "intent_confidence": 0.95,
  "route_hint": "deterministic_price_planner"
}
```

Khi có lỗi, mình biết lỗi nằm ở:

```text
classifier
planner
candidate
judge
sanitizer
cache
```

thay vì phải đoán trong một flow LLM lớn.

## 4. Nhược điểm của Code Intent Classifier

### 4.1. Vẫn có thể classify sai

Ví dụ:

```text
sản phẩm này có đáng tiền không?
```

Nếu classifier nhầm thành `price_question`, hệ thống có thể chỉ trả giá, trong khi user muốn hỏi value-for-money.

### 4.2. Cần maintain rule/keyword

Code classifier ban đầu vẫn cần:

```text
normalization
noise stripping
intent keywords
off-topic patterns
confidence rules
```

Nên vẫn phải update khi thấy pattern user mới.

### 4.3. Có nguy cơ thành regex phức tạp

Nếu thiết kế không cẩn thận, classifier có thể biến thành một tập regex lớn khó bảo trì.

Nguyên tắc cần giữ:

```text
Classifier chỉ quyết định intent/route.
Classifier không trả lời factual answer.
Classifier không thay thế Candidate/Judge.
```

### 4.4. Không hiểu semantic sâu như LLM

Code classifier phù hợp với intent phổ biến, nhưng yếu với câu hỏi tinh tế:

```text
review này cho thấy người dùng có đang thất vọng ngầm không?
sản phẩm này phù hợp với người mới nhưng hơi khó tính không?
```

Các câu này vẫn nên đi Candidate LLM + Judge.

### 4.5. Cần thêm trace/test

Nếu thêm classifier mà không ghi trace, sẽ khó giải thích vì sao câu bị route.

Do đó classifier nên luôn ghi:

```text
intent
confidence
route_decision
normalized_question
noise_removed
```

## 5. Các bước triển khai Code Intent Classifier trong tương lai

### Step 1: Thêm file classifier riêng

Đề xuất file:

```text
AIE1/techx-corp-platform/src/product-reviews/guardrails/intent_classifier.py
```

### Step 2: Định nghĩa output schema

Ví dụ:

```python
{
    "is_product_related": bool,
    "intent": str,
    "normalized_question": str,
    "confidence": float,
    "noise_removed": str,
    "route_hint": str,
}
```

### Step 3: Định nghĩa intent ban đầu

```text
noise_or_greeting
meaningless_input
off_topic
price_question
review_count
average_rating
negative_reviews
positive_themes
review_summary
feature_mention
audience_recommendation
no_info_attribute
open_review_question
```

### Step 4: Normalize input

Xử lý:

```text
lowercase
unicode normalize
remove Vietnamese accents for matching
collapse whitespace
strip punctuation noise
```

Ví dụ:

```text
"Tôi là Thịnh cho tôi biết giá sản phẩm này"
→ "toi la thinh cho toi biet gia san pham nay"
```

### Step 5: Strip harmless noise

Tách các phần:

```text
hello
hi
ok
toi la <name>
toi ten la <name>
my name is <name>
short numeric/punctuation noise
```

Nhưng không block nếu sau noise còn product intent.

Ví dụ:

```text
hello 123 review san pham nay tot khong
→ normalized_question: "review san pham nay tot khong"
→ is_product_related: true
```

### Step 6: Detect product intent

Các cụm cần detect:

```text
product / san pham
review / danh gia / nguoi mua / khach hang
price / gia
rating / score / sao / diem
recommend / nen mua / worth
negative / tieu cuc / che / complaint
feature / tinh nang / co noi ve
```

Nếu không có product intent và chỉ là greeting/noise/off-topic rõ:

```text
route_hint = "out_of_scope"
```

### Step 7: Map intent sang route

```text
price_question
→ deterministic_price_planner

review_count / average_rating / negative_reviews
→ deterministic_rating_planner

no_info_attribute
→ deterministic_exact_attribute_planner

review_summary / feature_mention / audience_recommendation / open_review_question
→ candidate_llm_with_judge

noise_or_greeting / meaningless_input / off_topic
→ out_of_scope
```

### Step 8: Integrate trước Candidate

Flow tương lai:

```text
input_check
→ classify_user_intent(question)
→ if route_hint == out_of_scope: OUT_OF_SCOPE
→ if route_hint == deterministic_*: planner
→ else Candidate LLM + Judge
```

### Step 9: Add trace/artifact fields

Runtime trace nên có:

```json
{
  "intent": "price_question",
  "intent_confidence": 0.95,
  "normalized_question_sha256": "...",
  "route_hint": "deterministic_price_planner"
}
```

Không nên lưu raw question nếu vẫn giữ privacy policy hiện tại.

### Step 10: Test bằng stress dataset

Dùng dataset:

```text
AIE1/repro/datasets/customer_normal_stress_10000.jsonl
```

Kỳ vọng cải thiện:

```text
off_topic pass-rate tăng
normal false block giảm
NO_INFO không hợp lý giảm
wrapper/echo leak giữ ở 0
```

## 6. Kết luận

Code Intent Classifier là bước nâng cấp tiếp theo, không phải model mới.

Nó giúp:

```text
hiểu intent tốt hơn regex
giảm phụ thuộc vào prompt cứng
giảm hallucination cho facts chắc chắn
giảm request rác lọt vào LLM
dễ debug bằng trace
```

Nhưng nó cũng có nhược điểm:

```text
cần maintain
có thể classify sai
không hiểu semantic sâu như LLM
cần trace/test tốt để kiểm soát
```

Hướng tối ưu:

```text
Code classifier cho intent rõ và route decision.
Candidate LLM cho câu hỏi mở.
Judge cho factual grounding.
Sanitizer/cache policy cho output safety.
```
