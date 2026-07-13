# ADR 0001: Tích hợp mô hình AWS Bedrock Nova Lite làm mô hình LLM chính

* **Trạng thái:** Đã phê duyệt (Accepted)
* **Tác giả:** Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-13

---

## 1. Bối cảnh (Context)
Dịch vụ tóm tắt đánh giá sản phẩm (`product-reviews`) hiện đang sử dụng dịch vụ Mock LLM (`llm`). Dịch vụ này chỉ trả về các phản hồi giả lập định sẵn, không có khả năng hiểu và trả lời ngôn ngữ tự nhiên thực tế của khách hàng. Để đưa Shopping Copilot vào vận hành thực tế, hệ thống cần tích hợp với một mô hình ngôn ngữ lớn (LLM) thực tế.

Tuy nhiên, việc tích hợp LLM thật đối mặt với các ràng buộc nghiêm ngặt về **ngân sách chi phí token**, **độ trễ phản hồi (SLA Latency)** và **tỷ lệ lỗi (Reliability)**. Nhóm Task Force đã tiến hành đo đạc baseline trên nhiều kịch bản (20 requests liên tục cho mỗi model) để lựa chọn phương án tối ưu.

---

## 2. Các phương án xem xét (Alternatives)

Dựa trên số liệu đo đạc thực nghiệm tại [AI_BASELINE_EVAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AI_BASELINE_EVAL.md):

| Kịch bản | Model | Latency Average (ms) | Latency p95 (ms) | Tỉ lệ lỗi (%) | Chi phí / 10k requests | Nhận định kỹ thuật |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Real LLM** (Gemini) | `gemini-2.5-flash` | 5624.31 | 6829.13 | 60.00% | - | Lỗi cạn kiệt quota tài khoản miễn phí. |
| **Real LLM** (Groq 8B) | `llama-3.1-8b-instant` | 594.82 | 773.89 | 30.00% | - | Bị lỗi cú pháp Tool Calling (hallucination). |
| **Real LLM** (Groq 70B) | `llama-3.3-70b-versatile` | 824.67 | 968.81 | 10.00% | ~$5.29 USD | Nhanh, chất lượng tốt nhưng chi phí khá cao. |
| **Real LLM** (Bedrock) | `amazon.nova-lite-v1:0` | 1668.41 | 2281.35 | **0.00%** | **~$0.96 USD** | Độ ổn định tuyệt đối, giá rẻ vượt trội. |
| **Real LLM** (Bedrock) | `amazon.nova-micro-v1:0` | 2073.34 | 2959.01 | **0.00%** | **~$0.63 USD** | Giá rẻ nhất nhưng độ trễ trung bình cao hơn Nova Lite. |
| **Real LLM** (Bedrock) | `meta.llama3-3-70b-instruct` | 7650.01 | 10017.15 | 65.00% | ~$6.27 USD | Bị throttle lỗi gRPC `DeadlineExceeded` liên tục. |

---

## 3. Quyết định (Decision)
Chúng tôi quyết định lựa chọn **AWS Bedrock Nova Lite (`amazon.nova-lite-v1:0`)** thông qua **LiteLLM local proxy** làm mô hình LLM chính cho dịch vụ `product-reviews`.

**Lý do lựa chọn:**
1. **Độ ổn định tuyệt đối (Reliability):** Đạt tỷ lệ lỗi **0.00%** dưới tải benchmark. Khả năng tuân thủ Tool Calling hoàn hảo khi đi qua adapter của LiteLLM.
2. **Hiệu quả chi phí vượt trội (Cost-effective):** Chỉ tốn **~$0.96 USD cho 10,000 requests**, giúp tiết kiệm **81.8% chi phí** vận hành so với Llama 3.3 70B.
3. **Thời gian phản hồi chấp nhận được (Latency):** Độ trễ trung bình ~1.6 giây hoàn toàn đáp ứng tốt trải nghiệm người dùng trên storefront đối với tính năng tóm tắt không đồng bộ.

---

## 4. Hệ quả (Consequences)
* **Yêu cầu hạ tầng**: Cần triển khai và duy trì LiteLLM proxy ở cổng `4000` với cấu hình `drop_params: true` và `modify_params: true` để dịch chuyển tham số từ định dạng OpenAI sang Bedrock.
* **Theo dõi và Giám sát**: Cần cấu hình OpenTelemetry để đẩy chỉ số span latency và token của Bedrock qua Collector tới Jaeger để quản lý chất lượng.
* **Kiến trúc bổ trợ**: Vì độ trễ trung bình là ~1.6 giây, bắt buộc phải triển khai cơ chế **Fallback nhiều tầng** ( ADR 0002 ) để tránh lỗi API sập làm treo UI storefront.
