# ADR-001: Lựa Chọn Mô Hình LLM Provider Cho Tầng AI (Product Reviews)

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-06
- **Tác giả / Ký tên**: Team AIO02 (Task Force 3)
- **Phạm vi tác động**: Microservice `product-reviews`, `llm`, Tầng AI (AIE)

---

## 1. Bối cảnh (Context)

Tính năng AI cốt lõi của sản phẩm TechX Corp là **Tóm tắt Review Sản phẩm** (`product-reviews`). 
Mặc định trong codebase ban đầu, service gọi đến một backend `llm` **mock** (chỉ trả về chuỗi JSON cố định từ file đĩa).

Để đưa ứng dụng ra vận hành thực tế (Production Readiness), nhóm **AIO02** cần lựa chọn một **LLM Provider thật** đáp ứng các tiêu chuẩn:
1. Độ trễ thấp ($p95 < 1.5s$).
2. Chi phí thấp (trong trần ngân sách hạ tầng $300/tuần/TF3$).
3. Độ tin cậy và tương thích chuẩn OpenAI Chat Completions API.
4. Tích hợp mượt mà với hạ tầng AWS EKS của TF3.

---

## 2. Quyết Định Kiến Trúc (Decision & Migration Roadmap)

### **Giai đoạn 1 (Tuần 1 Baseline)**: Sử dụng **OpenAI Format Client (`gpt-4o-mini`)**
- Triển khai cấu hình qua [deploy/values-aio-llm.yaml](file:///d:/Xbrain/Read_Capstone03/phase3/deploy/values-aio-llm.yaml) với Secret `llm-api-key`.
- **Lý do chọn cho Tuần 1**: Tương thích 100% với SDK `openai` Python hiện có trong code `product_reviews_server.py`, độ trễ cực thấp ($p95 \approx 0.8s$), chi phí rẻ ($0.15 / 1M input tokens$). Giúp hoàn thành mốc **Baseline System** ngay trong Ngày 1-2 mà không cần sửa đổi SDK gọi LLM.

### **Giai đoạn 2 (Tuần 2-3 Migration Plan)**: Chuyển sang **AWS Bedrock / Bedrock Gateway**
- **Mục tiêu**: Đưa toàn bộ traffic LLM vào mạng nội bộ AWS EKS của TF3, tận dụng IAM Role sẵn có của node EKS và hiển thị minh bạch chi phí trên AWS Cost Explorer.
- **Cách thực hiện**: Cắm Bedrock-compatible gateway trỏ `LLM_BASE_URL` sang `https://bedrock-gateway.techx-tf3.svc.cluster.local/v1` và đổi `LLM_MODEL` sang `anthropic.claude-3-haiku-20240307-v1:0`.

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
- **Không gây gián đoạn (Zero-downtime)**: Tuần 1 có ngay LLM thật chạy để đo Baseline metrics cho bài Pitching.
- Quản lý secret an toàn qua K8s Secret `llm-api-key`.
- Lộ trình chuyển sang Bedrock rõ ràng ở Tuần 2 giúp tăng tính bảo mật VPC và tích hợp với tính năng AI Agentic (Shopping Copilot).

### **Đánh đổi chấp nhận**:
- Ở Tuần 1, gọi OpenAI API công cộng có xác suất nhỏ bị lỗi HTTP 429 Rate Limit $\rightarrow$ Đã được giải quyết bằng cơ chế **Retry & Fallback (P1)** trong `ADR-002`.
