# ADR 0001: Kiến Trúc Pipeline 6 Lớp Cho Shopping Copilot Agent

- **Trạng thái:** Đã phê duyệt
- **Tác giả:** Bùi Lê Tuấn, Phạm Vũ Khánh Trường, Đặng Thị Ngọc Thảo - AIE2
- **Ngày tạo:** 2026-07-20

---

## 1. Bối cảnh

Shopping Copilot AIE2 là thành phần AI trung tâm kết nối 6 microservices (Product Catalog, Cart, Reviews, Recommendation, Currency, Shipping) của nền tảng TechX Corp thông qua giao diện ngôn ngữ tự nhiên. Người dùng có thể tìm kiếm sản phẩm, so sánh giá, xem đánh giá, thêm vào giỏ hàng, và quy đổi tiền tệ bằng câu hỏi tiếng Việt hoặc tiếng Anh.

Hệ thống phải đáp ứng đồng thời:
1. **Độ chính xác:** Câu trả lời phải grounded theo dữ liệu thực từ DB, không bịa đặt.
2. **An toàn:** Chặn prompt injection, không rò rỉ PII, không thực thi hành động nguy hiểm.
3. **Đa lượt:** Resolve đúng tham chiếu ngữ cảnh ("cái đó", "cái đầu tiên") từ lịch sử hội thoại.
4. **Đa ngôn ngữ:** Hiểu tiếng Việt, tiếng Anh và hỗn hợp.
5. **Chi phí thấp:** Tối ưu token, sử dụng Amazon Nova Lite (không dùng model nặng cho mọi request).

---

## 2. Quyết định

Chúng tôi thiết kế `CopilotAgent` theo **pipeline 6 lớp tuần tự** (tại `src/agent/copilot_agent.py`), mỗi lớp có trách nhiệm rõ ràng và độc lập:

```
Input → [1] Input Guard → [2] Intent Parser → [3] Context Resolver
      → [4] Planner → [5] Executor → [6] Answer Generator + Faithfulness Gate → Output
```

---

## 3. Chi Tiết Từng Lớp

### Lớp 1 — Input Guard
- Phát hiện và chặn prompt injection bằng regex pattern trước khi gọi LLM.
- Patterns: system override, jailbreak, delimiter injection (`\n system:`, `<|im_start|>`), PII extraction request.
- **Fail-fast:** Nếu phát hiện injection → trả lỗi ngay, không tốn token LLM.

### Lớp 2 — Intent Parser
- Gọi Amazon Bedrock (Nova Lite) với structured output để phân loại intent thành 8 loại:
  `product_search`, `product_compare`, `product_detail`, `add_to_cart`, `view_cart`, `get_reviews`, `currency_convert`, `general`.
- Trích xuất entities: `product_name`, `category`, `price_range`, `quantity`, `target_currency`.

### Lớp 3 — Context Resolver
- Resolve các tham chiếu đa lượt từ `session_memory`:
  - Ordinal: "cái đầu tiên" → `last_search_results[0]`
  - Demonstrative: "cái đó", "sản phẩm đó" → entity gần nhất trong lịch sử
  - Implicit: câu hỏi tiếp theo không nhắc tên → entity của turn trước
- Dùng `src/memory/store.py` (file-based session) để persist context giữa các request.

### Lớp 4 — Planner
- **Heuristic Planner** (không tốn LLM call): ánh xạ intent → danh sách tool steps.
- Ví dụ: `product_compare` → `[search_product × 2, get_reviews × 2]`
- **LLM Planner** (fallback cho complex/ambiguous): gọi Nova Lite để tạo plan JSON.

### Lớp 5 — Executor
- Thực thi tool steps song song hoặc tuần tự theo plan:
  - `search_product`: Hybrid SQL + RAG (xem ADR 0002)
  - `add_to_cart`: Gọi Cart microservice, yêu cầu HMAC confirmation token
  - `view_cart`, `get_reviews`, `currency_convert`, `get_recommendations`: gRPC đến các microservice
- Mỗi tool có timeout và error handling riêng biệt.

### Lớp 6 — Answer Generator + Faithfulness Gate
- Gọi Nova Lite để tổng hợp câu trả lời từ evidence thu được ở Executor.
- **Faithfulness Gate:** Sau khi có reply, chạy thêm một lượt judge nhẹ để verify câu trả lời không mâu thuẫn với evidence (xem ADR 0004).
- PII output filter: quét reply cuối cùng bằng regex trước khi trả về client.

---

## 4. Lý Do Chọn Phương Án

| Lựa chọn | Lý do |\
|---|---|
| **Pipeline tuần tự** thay vì ReAct loop | Dễ debug, latency predictable, không bị loop vô hạn khi LLM lạc đề |
| **Heuristic Planner** là mặc định | Giảm 1 LLM call cho ~90% request thông thường → tiết kiệm chi phí |
| **Lớp Guard ở đầu, Filter ở cuối** | Defense-in-depth: chặn input độc, lọc output nhạy cảm |
| **File-based session** (không Redis) | Đơn giản hóa deploy, phù hợp prototype; dễ swap sang Redis sau |
| **Nova Lite** không phải Nova Pro | Nova Lite đủ khả năng cho intent parsing + answer synthesis, rẻ hơn ~5× |

---

## 5. Đo Lường & Kết Quả

| Chỉ số | Giá trị |
|---|---|
| Overall Pass Rate (74 test cases) | **87.84%** (65/74) |
| Avg Latency (end-to-end, bao gồm cả tool calls) | **8.04 giây** |
| P95 Latency | **20.13 giây** |
| Avg Cost per Request (Nova Lite tokens) | **$0.00001476** |

---

## 6. Tài Liệu Liên Quan

- `src/agent/copilot_agent.py` — Implementation chính (~1500 lines)
- `src/memory/store.py` — Session memory
- [ADR 0002](./0002-HYBRID-SEARCH-SQL-RAG.md) — Hybrid Search
- [ADR 0003](./0003-AI-SAFETY-GUARDRAILS.md) — Safety Guardrails
