# ADR 0006: Giải Pháp Quản Lý Ngữ Cảnh & Giải Quyết Tham Chiếu Đa Lượt (Context & Ordinal Resolution)

- **Trạng thái:** Đã phê duyệt
- **Tác giả:** Phạm Vũ Khánh Trường, Đặng Thị Ngọc Thảo - AIE2
- **Ngày tạo:** 2026-07-22

---

## 1. Bối Cảnh

Trong các cuộc hội thoại mua sắm thực tế, người dùng thường không lặp lại đầy đủ tên sản phẩm ở các lượt hội thoại tiếp theo (multi-turn conversation). Thay vào đó, họ sử dụng:
1. **Từ chỉ định (Demonstratives):** "Sản phẩm đó giá bao nhiêu?", "So sánh nó với cái này".
2. **Thứ tự xuất hiện (Ordinals):** "Cho tôi xem review của cái thứ nhất", "Thêm cái thứ 2 vào giỏ hàng".
3. **Tham chiếu ẩn (Implicit Context):** "Có màu gì khác không?" (ngầm hiểu là sản phẩm đang được thảo luận ở turn trước).

Nếu hệ thống không duy trì và giải quyết (resolve) đúng ngữ cảnh này, các ca kiểm thử dạng `contextual` sẽ thất bại hoàn toàn hoặc dẫn đến việc AI bịa đặt thông tin.

---

## 2. Quyết Định

Chúng tôi thiết kế mô hình **Session Memory & Context Resolver** ở Lớp 3 của pipeline (`CopilotAgent`), hoạt động trước bước Planner và Execution.

### 2.1. Quản Lý Session Memory (`src/memory/store.py`)
- Cấu trúc lưu trữ session state cho mỗi `session_id` bao gồm:
  - `history`: Lịch sử các lượt chat (input_text, reply, timestamp).
  - `last_search_results`: Danh sách danh mục/sản phẩm trả về từ lượt tìm kiếm gần nhất.
  - `last_mentioned_product`: Sản phẩm đang được đề cập chính (active entity).
- Persistent Backend: Lưu vết dưới dạng tệp JSON local per-session (`.data/sessions/<session_id>.json`), cho phép khôi phục ngữ cảnh tức thì giữa các API request.

### 2.2. Ordinal & Entity Context Resolver Logic
Tại Lớp 3 (Context Resolver), câu hỏi của người dùng được phân tích và thay thế/bổ sung thông tin entity:

1. **Giải quyết Thứ tự (Ordinal Resolution):**
   - Regex bắt các cụm từ chỉ thứ tự: `"cái thứ nhất"`, `"sản phẩm 1"`, `"cái đầu tiên"`, `"the first one"`, `"second product"`.
   - Map chỉ số index tương ứng với mảng `last_search_results` trong session memory (ví dụ: "cái thứ nhất" → `last_search_results[0]`).
   - Cập nhật entity `product_name` chính xác vào Intent Object trước khi chuyển sang Planner.

2. **Giải quyết Từ chỉ định / Tham chiếu ẩn (Demonstrative / Implicit Resolution):**
   - Nếu `product_name` rỗng nhưng intent yêu cầu thông tin sản phẩm (`get_reviews`, `product_detail`, `add_to_cart`), Resolver tự động kế thừa `last_mentioned_product` từ session memory.

3. **Fallback Khi Thiếu Context:**
   - Nếu câu hỏi chứa từ tham chiếu ("cái đó") nhưng `session_memory` chưa có lịch sử tìm kiếm nào → Phản hồi lịch sự yêu cầu người dùng làm rõ: *"Bạn đang muốn hỏi về sản phẩm nào ạ? Vui lòng nêu rõ tên sản phẩm giúp mình nhé."* (Thay vì tung lỗi crash hoặc bịa sản phẩm).

---

## 3. Lý Do Chọn Phương Án

| Lựa chọn | Lý do |
|---|---|
| **Duy trì Session Memory dạng file/json** | Đơn giản, độ tin cậy cao, không bị mất memory khi server restart nhẹ |
| **Deterministic Ordinal Mapping** | Dùng Index Mapping trực tiếp thay vì bắt LLM đoán giúp đạt độ chính xác 100% khi tham chiếu "cái 1, cái 2" |
| **Explicit Clarification Fallback** | Hỏi lại người dùng khi thiếu context giúp tránh bịa đặt (Anti-hallucination) |

---

## 4. Đo Lường & Kết Quả

Hiệu quả cải tiến trên bộ test case thực tế:

| Metric | Trước khi tối ưu Context Resolver | Sau khi áp dụng ADR 0006 |
|---|---|---|
| **Pass Rate nhóm `contextual`** | 25.0% (1/4 cases) | **100.0% (4/4 cases)** |
| **Pass Rate nhóm `action_guard` (add item from context)** | 57.1% | **85.7%** |
| **Lỗi hallucination do đoán sai context** | Có xuất hiện | **0%** |

---

## 5. Tài Liệu Liên Quan

- `src/memory/store.py` — File-based session memory implementation
- `src/agent/copilot_agent.py` — Lớp 3 (Context Resolver logic)
- [ADR 0001](./0001-AGENT-PIPELINE-6-LAYER.md) — Kiến trúc Pipeline 6 lớp
- [ADR 0002](./0002-HYBRID-SEARCH-SQL-RAG.md) — Hybrid Search & Reranker
