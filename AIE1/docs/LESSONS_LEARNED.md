# 📑 Đúc Kết Kinh Nghiệm Xây Dựng & Vận Hành Dịch Vụ Product Reviews
*(AIE1 System Architecture Retrospective & GenAI Engineering Lessons)*

---

## 📌 1. Bối Cảnh & Chuyển Đổi Tư Duy (Mindset Shift)

### A. Từ "Task-Driven" (Chạy Theo Ticket) Sang "Architecture-Driven" (Làm Chủ Hệ Thống)
- **Thực trạng ban đầu:** Trong giai đoạn đầu, tôi quá tập trung vào việc hoàn thành và tích chọn (check-off) các yêu cầu Mandate mà chưa dành đủ thời gian đọc hiểu bức tranh toàn cảnh về luồng dữ liệu (Data Flow) và ranh giới kiến trúc hệ thống.
- **Sự chuyển biến tư duy:** Nhận ra rằng việc hoàn thành ticket chỉ là điều kiện cần. Để một dịch vụ AI hoạt động ổn định trong thực tế, có độ trễ cực thấp (< 5ms) và an toàn về mặt chi phí, người kỹ sư bắt buộc phải **làm chủ và hiểu sâu bản chất kiến trúc hệ thống** thay vì chỉ để AI sinh code qua loa.

---

## 🧠 2. Bài Học Về Tư Duy Đọc & Thiết Kế Kiến Trúc Hệ Thống (System Architecture)

### A. Phân Biệt Điểm Nghẽn CPU-bound vs I/O-bound
- **Bài học:** Không phải tác vụ nào cũng cần gọi LLM hay chạy quét RAM liên tục. Cần phân tích đúng bản chất điểm nghẽn để đặt đúng vị trí tối ưu:
  - **Tầng 1 (Redis LLM Cache):** Triệt tiêu độ trễ mạng (I/O-bound) khi gọi Amazon Bedrock LLM $\rightarrow$ Hạ Latency p50 từ 2.82s xuống **4.4ms**, tiết kiệm **83.3% chi phí API**.
  - **Tầng 2 (DB Column `is_safe`):** Chuyển việc quét Regex từ RAM Server xuống cột PostgreSQL $\rightarrow$ Triệt tiêu **100% độ trễ xử lý CPU (CPU-bound)**.

### B. Nhận Thức Đúng Về Ranh Giới Tính Năng (Single-Turn RAG vs Multi-Turn Memory)
- **Bài học:** Tránh áp dụng công nghệ dư thừa khi không cần thiết.
- **Thực tế:** Dịch vụ Product Reviews hoạt động theo cơ chế **Single-turn RAG / Tóm tắt theo từng sản phẩm**. Việc lạm dụng Long-term Memory giữa các sản phẩm khác nhau sẽ gây ra nguy cơ suy luận nhầm lẫn (Cross-Product Hallucination) và rò rỉ dữ liệu cá nhân (PII).

---

## 🎯 3. Kỹ Thuật Đóng Khung & Kiểm Soát Prompt Hệ Thống (System Prompt Engineering)

### A. Vấn Đề "AI Làm Qua Loa / Mất Kiểm Soát" (Vague AI Generation)
- **Thực trạng:** Khi chỉ viết prompt chung chung hoặc để AI tự do sinh văn bản, kết quả trả về thường bị lan man, suy diễn không có căn cứ (Fabrication), hoặc trả về sai định dạng mong muốn (như tự tiện dùng dạng Question/Answer).

### B. Kỹ Thuật Đóng Khung Prompt Chặt Chẽ (Strict Constraints & Deterministic Steering)
1. **Định nghĩa Ranh giới Bằng chứng (Strictly Grounded):**
   - Chỉ cho phép LLM tổng hợp câu trả lời **dựa trên duy nhất danh sách nhận xét được truyền vào Prompt Context**.
2. **Kỹ thuật Đặt Điều Cấm (Negative Constraints):**
   - Cấm tự tiện đưa ra thông tin bảo hành, độ bền dài hạn khi nhận xét không đề cập.
   - Cấm dùng cấu trúc Question/Answer rác trong response.
3. **Trả về Sentinel Tokens Để Backend Đón Nhánh (Deterministic Routing):**
   - Hướng dẫn LLM trả về các từ khóa định danh chuẩn: `OUT_OF_SCOPE`, `NO_INFO`, `UNVERIFIED_SUMMARY` khi không đủ dữ liệu. Điều này giúp mã nguồn Python xử lý câu điều kiện (`if/else`) một cách chính xác thay vì đoán chuỗi văn bản tự do.

### C. Giải Quyết Bài Toán Input Phức Tạp & Quy Mô Tư Duy (Multi-Question & Cognitive Scale)
1. **Bài toán Multi-Question (Nhiều câu hỏi trong 1 Input):**
   - *Vấn đề:* Khách hàng gộp 3-4 câu hỏi thuộc nhiều phạm vi khác nhau (*"Pin trâu không? Tai nghe nghe hay không? Giá bao nhiêu? Giao hàng nhanh không?"*).
   - *Giải pháp:* Phân rã ý định (**Intent Decomposition**). Đối với ý thuộc Product Review (Pin, Chất âm), LLM tổng hợp dạng Bullet Points rõ ràng. Đối với ý ngoài phạm vi (Shipping/Giao hàng), hệ thống từ chối lịch sự (*"Thông tin giao hàng không nằm trong đánh giá sản phẩm"*).
2. **Xác định Ý Chính vs Ý Nhiễu (Relevance Filtering):**
   - Nhúng kỹ thuật Chain-of-Thought (CoT) nhẹ vào Prompt: Bắt LLM trải qua 2 bước suy luận ngầm trước khi trả lời: `[Step 1: Extract Relevant Product Intents]` $\rightarrow$ `[Step 2: Filter Noise/Off-Topic]` $\rightarrow$ `[Step 3: Synthesize Answer]`.
3. **Thoát Khỏi Bẫy Q/A Rập Khuôn (Flexible Cognitive Scale & Balanced Advisory):**
   - *Vấn đề:* Phản hồi dập khuôn khô cứng kiểu "Máy trả lời Q/A" khiến trải nghiệm người dùng kém tự nhiên.
   - *Giải pháp:* Linh hoạt quy mô tư duy theo độ phức tạp câu hỏi:
     - **Fact Search (Đơn giản):** Trả lời thẳng thắn 1-2 câu.
     - **Nuanced Query (Phức tạp - ví dụ: "Có nên mua làm quà không?"):** Trả lời đa chiều dạng **Tư vấn khách quan (Balanced View)**: Nêu ưu điểm nổi bật $\rightarrow$ Điểm lưu ý/Nhược điểm $\rightarrow$ Kết luận trung lập dựa trên dữ liệu đánh giá thực tế.

---

## 🛡️ 4. Tầng Phòng Thủ Đa Lớp (Defense-in-Depth & Quality Control)

### A. Kiến Trúc Phòng Thủ 3 Tầng (Input - Process - Output)
- **Input Guardrails:** Quét 28+ patterns loại bỏ Prompt Injection trước khi tới LLM.
- **Judge Evaluation:** Dùng kiến trúc 2 Model (Nova Lite Candidate + Nova Micro Judge) để chấm điểm độ trung thực của câu trả lời.
- **Output PII Filter:** Redact tự động Email, Số điện thoại Việt Nam trước khi phản hồi cho client.

### B. Cam Kết Minh Bạch Số Liệu (Audit Integrity Gate)
- Tuyệt đối không dùng con số nhập tay thủ công hay ước tính chủ quan trong báo cáo.
- Toàn bộ số liệu về Hit Rate (83.3%), Latency (4.4ms), và Tiết kiệm token (11,491 tokens) phải được trích xuất tự động qua script benchmark ([repro/eval_support/benchmark.py](../repro/eval_support/benchmark.py)) và lưu vết dưới dạng JSON Machine-Readable Artifact.

---

## 🚀 5. Checklist Quy Trình Cho Các Dự Án AI Tương Tự (Actionable Checklist)

- [ ] **Bước 1:** Đọc hiểu sơ đồ luồng dữ liệu (Data Flow Diagram) trước khi viết mã nguồn.
- [ ] **Bước 2:** Xác định bài toán thuộc dạng Single-turn hay Multi-turn để chọn kiến trúc Cache/Memory phù hợp.
- [ ] **Bước 3:** Đóng khung System Prompt với điều kiện cấm (Negative Constraints) và Sentinel Return Tokens.
- [ ] **Bước 4:** Thiết lập kiến trúc Caching 2 tầng (Response Cache + DB Flag Cache).
- [ ] **Bước 5:** Xây dựng script Harness đo lường tự động xuất file JSON bằng chứng.

---

## 📝 6. Kết Luận
*Làm chủ một hệ thống AI không phải là viết prompt thật dài hay dùng model thật lớn, mà là biết cách đóng khung giới hạn của AI, kết hợp linh hoạt với các thuật toán lập trình định tính (Deterministic Code) và hạ tầng Caching để tạo ra một dịch vụ vừa an toàn, vừa nhanh, vừa tiết kiệm chi phí.*
