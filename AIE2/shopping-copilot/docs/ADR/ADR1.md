# ADR-1: Trust & Safety Architecture for Shopping Copilot

- Status: Accepted
- Date: 2026-07-15
- Authors: TF3 / CDO02

## Context

Shopping Copilot cần vận hành trên môi trường thương mại điện tử thực tế, nơi hệ thống có thể tiếp nhận:
- câu hỏi từ khách hàng về sản phẩm và đơn hàng,
- review sản phẩm làm đầu vào để tóm tắt hoặc trả lời,
- yêu cầu có tính hành động như thêm vào giỏ, xác nhận đơn hàng, checkout.

Các rủi ro cần kiểm soát:
1. Prompt injection: người dùng cố tình khiến AI bỏ qua quy tắc hoặc lộ system prompt.
2. Hallucination / unsafe answer: AI bịa thông tin hoặc trả lời không dựa trên review nguồn.
3. Unsafe action: AI tự ý thực hiện hành động có rủi ro như checkout, empty cart, hoặc thay đổi đơn hàng.
4. Service failure: khi LLM hoặc dịch vụ phụ trợ lỗi, hệ thống không được treo hoặc trả về nội dung vô nghĩa.

## Decision

Chúng tôi quyết định triển khai một kiến trúc Trust & Safety gồm 4 tầng, dựa trực tiếp trên các module đã có trong codebase hiện tại:

1. Input Guardrail
   - Chặn prompt injection, jailbreak, prompt disclosure, PII extraction và các input không phù hợp bằng module [AIE2/shopping-copilot/src/guardrails/input_filter.py](AIE2/shopping-copilot/src/guardrails/input_filter.py).
   - Hiện tại, luồng thực thi dùng tầng regex trước, vì tầng Bedrock semantic check vẫn chưa được kết nối đầy đủ trong code.

2. Output Guardrail
   - Lọc và redact các thông tin nhạy cảm như email, số điện thoại, thẻ tín dụng, connection string, AWS ARN, API key bằng module [AIE2/shopping-copilot/src/guardrails/output_filter.py](AIE2/shopping-copilot/src/guardrails/output_filter.py).
   - Đây là lớp bảo vệ cuối trước khi trả lời khách hàng.

3. Fallback & Safe Error Handling
   - Khi LLM hoặc service lỗi, hệ thống trả về message an toàn thay vì crash hoặc treo bằng module [AIE2/shopping-copilot/src/guardrails/fallback.py](AIE2/shopping-copilot/src/guardrails/fallback.py).
   - Mọi exception đều được chuyển thành response chuẩn có message, reply và error_code.

4. Action Guard / Confirmation Gate
   - Các hành động ghi (write actions) như checkout, empty cart, place order bị cấm tuyệt đối hoặc yêu cầu xác nhận bằng module [AIE2/shopping-copilot/src/guardrails/confirmation.py](AIE2/shopping-copilot/src/guardrails/confirmation.py).
   - Việc gọi tool cũng được kiểm soát bằng [AIE2/shopping-copilot/src/guardrails/tool_validator.py](AIE2/shopping-copilot/src/guardrails/tool_validator.py) để chặn tool lạ, cross-user và tham số không hợp lệ.

## Chosen Model and Runtime Strategy

- Model chính: AWS Bedrock runtime, hiện được đóng gói trong [AIE2/shopping-copilot/src/llm/llm.py](AIE2/shopping-copilot/src/llm/llm.py) với cấu hình model ID mặc định là Amazon Nova Lite.
- Nguyên tắc: dùng model thật cho luồng production-like; không lùi về mock client khi khởi tạo Bedrock thất bại.
- Nếu model không sẵn sàng, hệ thống dùng fallback an toàn và không tiếp tục thực thi hành động ghi.

## Evaluation Strategy

Bộ eval được triển khai tại [AIE2/shopping-copilot/src/evaluation/trust_safety.py](AIE2/shopping-copilot/src/evaluation/trust_safety.py) và chạy từ script [AIE2/shopping-copilot/scripts/run_eval_suite.py](AIE2/shopping-copilot/scripts/run_eval_suite.py).

Bộ eval được thiết kế để đo các khía cạnh sau:

1. Prompt injection robustness
   - Test một review hoặc câu hỏi có chứa câu độc như "ignore previous instructions".
   - Kết quả kỳ vọng: AI chặn request, không nghe theo.

2. Groundedness / factuality
   - Test một câu hỏi mà review nguồn không hề trả lời được.
   - Kết quả kỳ vọng: AI không bịa, mà trả về "không có thông tin" hoặc fallback-safe answer.

3. Fallback behavior
   - Test khi model/service lỗi.
   - Kết quả kỳ vọng: AI trả về message an toàn thay vì treo.

4. Action safety
   - Test hành vi như "checkout" hoặc "empty cart".
   - Kết quả kỳ vọng: AI từ chối hoặc hỏi xác nhận trước khi thực hiện.

## Measurement

Các metric chính:
- accuracy: tỉ lệ case pass trên tổng số case
- blocked rate: tỉ lệ prompt injection / unsafe inputs bị chặn đúng
- fallback rate: tỉ lệ lỗi được xử lý bằng safe fallback
- action denial rate: tỉ lệ action nguy hiểm bị chặn đúng

## Consequences

### Positive
- Hệ thống có khả năng chống prompt injection và bảo vệ khỏi output độc hại.
- Có đường lui khi model hoặc service lỗi.
- Có thể chứng minh bằng eval và test thay vì bằng lời nói.

### Trade-offs
- Một số request có thể bị chặn quá mức nếu input giống các pattern bảo mật.
- Fallback có thể làm trải nghiệm ít tự nhiên hơn khi service lỗi, nhưng ưu tiên an toàn.

## Implementation Notes

- Evaluation cases phải được lưu trong repo để reproducible, ví dụ [AIE2/shopping-copilot/docs/sample_eval_cases.json](AIE2/shopping-copilot/docs/sample_eval_cases.json).
- Khi thay đổi prompt, guardrail hoặc action policy, cần chạy lại test/eval trước khi deploy.
- Report kết quả evaluation có thể export sang JSON hoặc Markdown bằng script chạy ở trên.
- Mentor hoặc reviewer có thể tự bắn thử theo các case mẫu để thấy AI chặn prompt injection, không bịa khi thiếu grounding, fallback khi lỗi và từ chối action nguy hiểm.
