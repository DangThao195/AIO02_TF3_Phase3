# Hybrid Answer Planner changes for Product Reviews AI

## Mục tiêu

Tối ưu tính năng Ask AI của product-review theo hướng an toàn hơn nhưng đỡ “cứng prompt” hơn.

Trước đó, hệ thống phụ thuộc nhiều vào Candidate LLM và Judge. Prompt được siết rất chặt để chống hallucination, nhưng nhược điểm là model dễ trả `NO_INFO`, dễ hiểu sai câu hỏi noisy/mixed-language, hoặc đôi khi tự echo lại câu hỏi người dùng.

Thay đổi mới dùng hướng hybrid:

```text
User question
→ input safety check
→ deterministic routing cho off-topic rõ ràng
→ deterministic answer planner cho intent chắc chắn
→ nếu planner không xử lý được thì mới gọi Candidate LLM
→ runtime Judge kiểm tra grounding/fidelity
→ output sanitizer
→ cache only safe/approved response
```

## Code đã thay đổi

### 1. Deterministic price planner

File:

```text
AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py
```

Hàm mới:

```python
answer_deterministic_price_question(question, product_info)
```

Tác dụng:

- Nhận diện câu hỏi giá/cost bằng nhiều cách diễn đạt như:
  - `price`
  - `cost`
  - `how much`
  - `gia`
  - `bao nhieu tien`
  - `muc gia`
- Lấy giá trực tiếp từ `product_info.priceUsd`.
- Trả lời bằng facts từ Product Catalog, không cần Candidate LLM tự suy luận.

Ví dụ:

```text
Question: Tôi là Thịnh cho tôi biết giá sản phẩm này
Answer: The price of Solar System Color Imager is 175 USD.
```

### 2. Unified deterministic planner entrypoint

File:

```text
AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py
```

Hàm mới:

```python
answer_deterministic_planned_question(question, reviews, product_info=None)
```

Planner hiện xử lý các intent có độ chắc chắn cao:

```text
price
rating / average_score
negative_review_count
exact_attribute / ingredient no-info
drawback / improvement absence
quality / durability with grounded nuance
```

Nếu planner trả được answer thì runtime trả luôn với:

```text
outcome="deterministic_answer"
judge_status="deterministic"
```

Nếu planner không chắc, nó trả `None` để câu hỏi đi tiếp vào Candidate LLM + Judge.

### 3. Runtime flow gọi planner trước Candidate LLM

File:

```text
AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py
```

Trong Bedrock path, flow mới là:

```python
reviews_json = fetch_product_reviews(request_product_id)
safe_reviews_json, raw_reviews_for_judge = normalize_reviews_for_context(reviews_json)
product_info_json = fetch_product_info(request_product_id)

deterministic_answer = answer_deterministic_planned_question(
    safe_question,
    raw_reviews_for_judge,
    product_info_json,
)

if deterministic_answer is not None:
    return finalize_response(
        deterministic_answer,
        outcome="deterministic_answer",
        judge_status_override="deterministic",
    )
```

Tác dụng:

- Các câu hỏi facts rõ ràng không còn phụ thuộc vào LLM.
- Giảm hallucination cho price/rating/count.
- Giảm latency/cost cho intent chắc chắn.
- Dễ debug hơn vì biết response đến từ planner hay LLM.

### 4. Routing chạy trước output redaction

File:

```text
AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py
```

Vấn đề cũ:

```text
User nhập chuỗi số dài
→ filter_output hiểu nhầm là PHONE_VN
→ đổi thành [REDACTED]
→ routing không còn thấy câu toàn số
→ request lọt vào LLM
```

Fix mới:

```text
check_input(question)
→ is_clearly_off_topic_question(question gốc)
→ filter_output(question) chỉ chạy sau khi routing đã qua
```

Kết quả:

```text
Question: 423942178483764873243287
Answer: This question is out of scope. I only answer questions related to the product.
```

### 5. Output sanitizer cho echo câu hỏi

File:

```text
AIE1/techx-corp-platform/src/product-reviews/guardrails/output_contract.py
```

Hàm mới:

```python
strip_leading_question_echo(answer, question)
```

Tác dụng:

- Nếu Candidate/Cache trả về câu bắt đầu bằng chính câu hỏi user, hệ thống cắt phần câu hỏi đi.

Ví dụ trước:

```text
Tôi là Thịnh cho tôi biết giá sản phẩm này The price of the Solar System Color Imager is 175 USD.
```

Sau fix:

```text
The price of the Solar System Color Imager is 175 USD.
```

### 6. Cache-hit cũng đi qua sanitizer

File:

```text
AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py
```

Trước đây nếu cache đã lưu response xấu, backend có thể trả lại nguyên response đó.

Fix mới:

```python
cached_answer = post_process_output(cached_data["answer"], safe_question)
return finalize_response(cached_answer, outcome="cache_hit", cache_hit=True)
```

Tác dụng:

- Response từ cache cũng bị chặn/cắt wrapper hoặc echo.
- Giảm nguy cơ cache khuếch đại lỗi cũ.

## Test đã thêm

File:

```text
AIE1/techx-corp-platform/src/product-reviews/test_runtime_guardrails.py
```

Các test mới/chính:

```text
test_price_question_is_answered_from_product_catalog
test_planner_answers_price_before_llm_path
test_planner_keeps_open_feature_question_on_llm_path
test_strip_leading_question_echo
test_post_process_strips_leading_question_echo
```

Kết quả test:

```text
38 passed, 43 subtests passed
```

Command:

```bash
python -m pytest AIE1/techx-corp-platform/src/product-reviews/test_runtime_guardrails.py -q
```

## Vì sao hướng này tối ưu hơn chỉ sửa prompt?

Chỉ sửa prompt có nhược điểm:

```text
LLM vẫn phải tự hiểu intent
LLM vẫn tự sinh facts
Judge vẫn phải bắt lỗi sau
Prompt càng cứng thì UX càng kém
```

Hybrid planner tốt hơn vì:

```text
Facts chắc chắn → code lấy trực tiếp
Intent chắc chắn → deterministic planner xử lý
Câu hỏi mở → LLM vẫn xử lý
Claims phức tạp → Judge vẫn kiểm tra
Output xấu → sanitizer chặn/cắt
```

Nói ngắn gọn:

```text
Cho code xử lý phần chắc chắn.
Cho LLM xử lý phần ngôn ngữ tự nhiên.
Cho Judge kiểm tra phần factual grounding.
```

## Nhược điểm còn lại

1. Planner vẫn cần mở rộng intent

Hiện planner mới xử lý nhóm chắc chắn. Các câu hỏi mở như:

```text
review này cho thấy pain point gì?
sản phẩm này có đáng tiền với người mới không?
người dùng có vẻ thật sự hài lòng không?
```

vẫn cần Candidate LLM + Judge.

2. Classifier/planner chưa semantic hoàn toàn

Planner vẫn dùng normalized keyword ở một số intent. Tốt hơn nữa là thêm một intent classifier nhẹ, nhưng phải kiểm soát để không biến thành LLM trả lời facts.

3. Verbalizer chưa tách riêng

Hiện deterministic answer trả câu tiếng Anh template trực tiếp. Nếu muốn tự nhiên hơn nữa, có thể thêm LLM verbalizer chỉ được viết lại từ facts đã được code extract.

4. Judge vẫn là LLM

Runtime Judge giúp giảm rủi ro nhưng không đảm bảo tuyệt đối 100%.

## Kết luận

Thay đổi mới không cố làm prompt “mềm hết” hoặc regex “bắt hết”.

Hệ thống chuyển sang hướng hybrid:

```text
deterministic planner cho facts chắc chắn
+ LLM cho câu hỏi mở
+ Judge cho grounding
+ sanitizer/cache policy cho output safety
```

Đây là hướng cân bằng hơn giữa:

```text
độ tin cậy
UX tự nhiên
debug dễ
cost/latency thấp hơn
```
