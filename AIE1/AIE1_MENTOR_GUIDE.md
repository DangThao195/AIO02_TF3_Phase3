# Báo Cáo Tổng Quan & Hướng Dẫn Vận Hành Tầng AI (Dành Cho Mentor) - Nhóm AIE1

Tài liệu này tổng hợp nhanh trạng thái bàn giao của nhóm **AIE1** phục vụ việc đánh giá của Mentor. Nội dung bao gồm hướng dẫn chạy nhanh hệ thống với LLM thật và lộ trình nâng cấp kiến trúc kỹ thuật trong tuần tiếp theo.

---

## 🚀 1. Hướng Dẫn Triển Khai Nhanh (Quick Start)

Hiện tại, hệ thống đã được cấu hình sẵn sàng để chạy với **AWS Bedrock Nova Lite** thật. Để kiểm thử hệ thống đang hoạt động, Mentor chỉ cần thực hiện 2 thao tác nhanh sau:

### Bước 1: Nạp Bedrock API Key vào Kubernetes Secret
Chạy lệnh trực tiếp trên terminal của EKS cluster (thay `<namespace>` bằng namespace của bạn và điền API Key do BTC cấp bắt đầu bằng `ABSK...`):
```bash
kubectl -n <namespace> create secret generic llm-api-key --from-literal=key=<REAL_ABSK_KEY_FROM_BTC>
```

### Bước 2: Nâng cấp Helm Deployment
Thực hiện nâng cấp Helm đính kèm tệp cấu hình AI thật đã được lưu sẵn trong dự án:
```bash
helm upgrade --install techx-corp ./AIE1/techx-corp-chart -n <namespace> \
  -f AIE1/deploy/values-observability.yaml \
  -f AIE1/deploy/values-flagd-sync.yaml \
  -f AIE1/deploy/values-aio-llm.yaml
```
> [!NOTE]
> Hệ thống hiện tại (Tuần 1) sẽ chạy qua LiteLLM Proxy được thiết lập trong **[AIE1/deploy/values-aio-llm.yaml](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/deploy/values-aio-llm.yaml)** để kết nối tới mô hình AWS Bedrock Nova Lite.

---

## 🛠️ 2. Lộ Trình Nâng Cấp Kỹ Thuật (Tuần 2)

Nhóm AIE1 đã nghiên cứu, thử nghiệm và xây dựng kế hoạch nâng cấp toàn diện cho tầng AI nhằm tối ưu hóa hiệu năng, bảo mật và độ tin cậy. Các tài liệu thiết kế và mã nguồn thử nghiệm đã được chuẩn bị đầy đủ:

### A. Tích Hợp Trực Tiếp AWS Bedrock SDK (boto3)
* **Mục tiêu**: Loại bỏ hoàn toàn Pod trung gian LiteLLM để giảm 1 hop mạng, **tối ưu hóa độ trễ (Latency)** và **tăng độ tin cậy**.
* **Giải pháp**: Xây dựng cơ chế định tuyến đa Client (Dual-Engine Routing) bằng biến môi trường `LLM_PROVIDER` (`openai` hoặc `bedrock`). Mã nguồn hỗ trợ cả OpenAI client cũ và SDK `boto3` mới (sử dụng AWS Converse API và tự động ánh xạ Tool Schema).
* **Tài liệu đề xuất chi tiết**: Xem tại **[AIE1/docs/analysis/BEDROCK_INTEGRATION_PROPOSAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/BEDROCK_INTEGRATION_PROPOSAL.md)**.

### B. Bộ Đánh Giá Độ Trung Thực (Fidelity Evaluation)
* **Mục tiêu**: Phát hiện tự động các trường hợp LLM bị ảo giác (hallucination) hoặc tóm tắt sai dữ liệu review gốc của PostgreSQL.
* **Giải pháp**: Viết script đánh giá chất lượng **[AIE1/repro/eval_fidelity.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/repro/eval_fidelity.py)** so khớp dữ liệu tóm tắt với Ground Truth (Fact Sheet) sử dụng LLM làm Judge.
* **Phân tích điểm nghẽn**: Nhóm đã phát hiện và đề xuất hướng giải quyết cho **4 điểm nghẽn lớn** của bộ eval hiện tại (như bất nhất Ground Truth, nhạy cảm với dải số). Chi tiết xem tại **[AIE1/docs/analysis/evaluation_bottlenecks.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/evaluation_bottlenecks.md)**.

### C. AI Guardrails (Bảo Mật & Lọc PII)
* **Mục tiêu**: Ngăn chặn Prompt Injection và bảo vệ dữ liệu cá nhân của khách hàng.
* **Giải pháp**: Thiết kế bộ lọc dữ liệu nhạy cảm (PII Filter) tự động loại bỏ Email, Số điện thoại trước khi đưa vào Prompt và cơ chế kiểm duyệt từ khóa đầu vào để từ chối các payload phá hoại system prompt. Chi tiết xem tại **[AIE1/AI_BASELINE_EVAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/AI_BASELINE_EVAL.md#L650-L766)**.

### D. Cơ Chế Xử Lý Dự Phòng (3-Tier Graceful Fallback)
* **Mục tiêu**: Đảm bảo storefront luôn hoạt động bình thường khi API Bedrock bị Timeout, lỗi 500 hoặc Rate Limit.
* **Kiến trúc dự phòng 3 tầng**:
  1. *Tầng 1 (Primary)*: Gọi trực tiếp mô hình AWS Bedrock Nova Lite (Real-time).
  2. *Tầng 2 (Fallback 1)*: Lấy tóm tắt tĩnh đã thành công trước đó từ bảng `product_summaries` trong PostgreSQL.
  3. *Tầng 3 (Fallback 2)*: Trả về thông báo lỗi thân thiện được thiết kế trước (Last Resort).
* **Tài liệu quyết định kiến trúc**: Xem tại **[AIE1/docs/adr/0002-fallback-mechanism.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/adr/0002-fallback-mechanism.md)**.

### E. Cơ Chế Caching Tối Ưu Chi Phí và Độ Trễ
* **Mục tiêu**: Giảm thiểu chi phí token của LLM và tối ưu thời gian phản hồi của trang Storefront đối với các lượt yêu cầu trùng lặp.
* **Giải pháp**: Xây dựng cơ chế lưu cache sử dụng hàm băm (Hash Key Caching) dựa trên `product_id` (với tóm tắt mặc định) và `SHA256(product_id + normalize(question))` (với câu hỏi Q&A tự do), kèm theo cơ chế xóa cache tự động khi có review mới.
* **Tài liệu đề xuất chi tiết**: Xem tại **[AIE1/docs/analysis/LLM_CACHING_DESIGN.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_CACHING_DESIGN.md)**.

### F. Thử Lại & Trễ Lũy Thừa (Retry & Exponential Backoff)
* **Mục tiêu**: Nâng cao tính chống chịu lỗi trước các lỗi mạng tạm thời hoặc Bedrock Rate Limit (HTTP 429).
* **Giải pháp**: Tích hợp thuật toán Exponential Backoff với Jitter qua decorator `tenacity` để tự động thử lại 3 lần trước khi kích hoạt Fallback.
* **Tài liệu đề xuất chi tiết**: Xem tại **[AIE1/docs/analysis/LLM_RETRY_BACKOFF.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_RETRY_BACKOFF.md)**.

### G. Phản Hồi Dạng Luồng (Streaming Response)
* **Mục tiêu**: Giảm thiểu thời gian nhận ký tự đầu tiên (TTFT) xuống dưới 200ms để tăng UX.
* **Giải pháp**: Chuyển đổi API sang cơ chế gRPC Server-side Streaming và sử dụng API `converse_stream` của Bedrock hoặc `stream=True` của OpenAI.
* **Tài liệu đề xuất chi tiết**: Xem tại **[AIE1/docs/analysis/LLM_STREAMING.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_STREAMING.md)**.

### H. Đăng Ký Công Cụ Động (Dynamic Tool Registry)
* **Mục tiêu**: Loại bỏ code rẽ nhánh `if/elif` cồng kềnh và dễ mở rộng khi bổ sung thêm nhiều tool mới.
* **Giải pháp**: Hiện thực hóa lớp `ToolRegistry` và decorator `@register_tool` để đăng ký động và tự động điều phối (Dynamic Dispatch) các AI tools.
* **Tài liệu đề xuất chi tiết**: Xem tại **[AIE1/docs/analysis/LLM_DYNAMIC_TOOL_REGISTRY.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_DYNAMIC_TOOL_REGISTRY.md)**.

### I. Bộ Nhớ Hội Thoại (Conversation Memory)
* **Mục tiêu**: Hỗ trợ hội thoại nhiều lượt (Multi-turn chat) thay vì chỉ hỏi đáp đơn lẻ.
* **Giải pháp**: Lưu trữ lịch sử tin nhắn của phiên chat sử dụng cơ chế Buffer Window lưu vào Redis phân tán (được đặt TTL tự động xoá sau 30 phút).
* **Tài liệu đề xuất chi tiết**: Xem tại **[AIE1/docs/analysis/LLM_CONVERSATION_MEMORY.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_CONVERSATION_MEMORY.md)**.

---

## 📁 3. Bản Đồ Thư Mục Của Nhóm AIE1

Toàn bộ các tài liệu và phần việc liên quan của nhóm AIE1 được tổ chức ngăn nắp tại thư mục **[AIE1/](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1)**:

* **[AIE1/AI_BASELINE_EVAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/AI_BASELINE_EVAL.md)**: Nhật ký đo đạc Baseline (độ trễ, chi phí token), thiết kế Guardrails và Backlog cải tiến.
* **[AIE1/docs/adr/](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/adr)**: Quyết định thiết kế kiến trúc (ADR 0001 và ADR 0002).
* **[AIE1/docs/analysis/](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis)**: Các báo cáo phân tích thiết kế bao gồm:
  * Lỗi hệ thống đánh giá: **[evaluation_bottlenecks.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/evaluation_bottlenecks.md)**
  * Tích hợp `boto3` trực tiếp: **[BEDROCK_INTEGRATION_PROPOSAL.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/BEDROCK_INTEGRATION_PROPOSAL.md)**
  * Thiết kế Caching: **[LLM_CACHING_DESIGN.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_CACHING_DESIGN.md)**
  * Thử lại và trễ lũy thừa: **[LLM_RETRY_BACKOFF.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_RETRY_BACKOFF.md)**
  * Phản hồi dạng luồng: **[LLM_STREAMING.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_STREAMING.md)**
  * Đăng ký công cụ động: **[LLM_DYNAMIC_TOOL_REGISTRY.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_DYNAMIC_TOOL_REGISTRY.md)**
  * Bộ nhớ hội thoại: **[LLM_CONVERSATION_MEMORY.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/analysis/LLM_CONVERSATION_MEMORY.md)**
* **[AIE1/docs/guides/EKS_DEPLOY_GUIDE.md](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/docs/guides/EKS_DEPLOY_GUIDE.md)**: Hướng dẫn chi tiết các bước deploy cụ thể lên cluster Kubernetes EKS.
* **[AIE1/techx-corp-platform/src/product-reviews/](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews)**: Mã nguồn Python của dịch vụ product reviews.
