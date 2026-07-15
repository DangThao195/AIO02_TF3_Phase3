# ADR 0001: Tích hợp mô hình AWS Bedrock Nova Lite qua SDK boto3 trực tiếp làm mô hình LLM chính

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-13 (Cập nhật: 2026-07-15)

---

## 1. Bối cảnh
Dịch vụ tóm tắt đánh giá sản phẩm `product-reviews` ban đầu sử dụng Mock LLM. Để đưa Shopping Copilot vào vận hành thực tế, hệ thống cần tích hợp với một mô hình ngôn ngữ lớn thực tế.

Tuy nhiên, việc tích hợp mô hình thật đối mặt với các ràng buộc nghiêm ngặt về ngân sách chi phí token, độ trễ phản hồi và tỷ lệ lỗi. Nhóm Task Force đã tiến hành đo đạc baseline trên nhiều kịch bản, chạy 20 requests liên tục cho mỗi mô hình để lựa chọn phương án tối ưu.

Đồng thời, khi triển khai trên hạ tầng Kubernetes EKS, việc duy trì một Pod proxy trung gian để chuyển đổi tham số sang Bedrock API sẽ tạo ra một hop mạng không cần thiết, làm tăng độ trễ và điểm có thể gây lỗi hệ thống.

---

## 2. Các phương án xem xét

Dựa trên số liệu đo đạc thực nghiệm tại [AI_BASELINE_EVAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AI_BASELINE_EVAL.md):

| Kịch bản | Model | Latency Average (ms) | Latency p95 (ms) | Tỉ lệ lỗi (%) | Chi phí / 10k requests | Nhận định kỹ thuật |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Real LLM - Gemini** | `gemini-2.5-flash` | 5624.31 | 6829.13 | 60.00% | - | Lỗi cạn kiệt quota tài khoản miễn phí. |
| **Real LLM - Groq 8B** | `llama-3.1-8b-instant` | 594.82 | 773.89 | 30.00% | - | Bị lỗi cú pháp Tool Calling. |
| **Real LLM - Groq 70B** | `llama-3.3-70b-versatile` | 824.67 | 968.81 | 10.00% | ~$5.29 USD | Nhanh, chất lượng tốt nhưng chi phí khá cao. |
| **Real LLM - Bedrock** | `amazon.nova-lite-v1:0` | 1668.41 | 2281.35 | 0.00% | ~$0.96 USD | Độ ổn định tuyệt đối, giá rẻ vượt trội. |
| **Real LLM - Bedrock** | `amazon.nova-micro-v1:0` | 2073.34 | 2959.01 | 0.00% | ~$0.63 USD | Giá rẻ nhất nhưng độ trễ trung bình cao hơn Nova Lite. |
| **Real LLM - Bedrock** | `meta.llama3-3-70b-instruct` | 7650.01 | 10017.15 | 65.00% | ~$6.27 USD | Bị throttle lỗi gRPC `DeadlineExceeded` liên tục. |

---

## 3. Quyết định
Chúng tôi quyết định lựa chọn **AWS Bedrock Nova Lite `amazon.nova-lite-v1:0`** làm mô hình chính cho dịch vụ `product-reviews` và áp dụng phương án **Tích hợp trực tiếp qua SDK boto3 Converse API** thay vì sử dụng LiteLLM proxy như phương án ban đầu.

**Các điểm chính trong quyết định:**
1. **Chọn mô hình AWS Bedrock Nova Lite:** Độ ổn định tuyệt đối dưới tải benchmark và chi phí vận hành siêu rẻ giúp tối ưu ngân sách tối đa.
2. **Tích hợp SDK boto3 trực tiếp:** Viết mã nguồn gọi trực tiếp AWS Bedrock thông qua Converse API của AWS SDK, tự động ánh xạ Tool Specification và định dạng tin nhắn của tool.
3. **Thiết kế Định tuyến Song song (Dual-Engine Routing):** Hỗ trợ cấu hình qua biến môi trường `LLM_PROVIDER` để chuyển đổi linh hoạt:
   * `LLM_PROVIDER="bedrock"`: Gọi trực tiếp SDK `boto3` trên EKS (sử dụng IAM Roles for Service Accounts để tự động nhận quyền).
   * `LLM_PROVIDER="openai"`: Giữ lại để kết nối tới các OpenAI-compatible endpoints phục vụ kiểm thử cục bộ hoặc chạy giả lập.

---

## 4. Hệ quả
* **Tối ưu hóa tài nguyên**: Loại bỏ hoàn toàn sự phụ thuộc vào Pod LiteLLM proxy trên Kubernetes EKS, giảm bớt tài nguyên CPU/RAM cần cấp phát và đơn giản hóa Helm chart triển khai.
* **Tối ưu hóa độ trễ**: Giảm thiểu 1 hop mạng trung gian giữa dịch vụ `product-reviews` và AWS Bedrock giúp cải thiện thời gian phản hồi thực tế của trang storefront.
* **Xử lý bất nhất cấu trúc**: Cần duy trì hàm tự động ánh xạ cấu trúc định nghĩa công cụ từ chuẩn OpenAI sang chuẩn Bedrock Tool Spec do sự khác biệt về định dạng giữa hai API.
