# ADR-2: Kiến trúc 6 Lớp Intent-Driven Modular cho Shopping Copilot

> [!NOTE]
> * **Trạng thái:** Đã phê duyệt (Approved)
> * **Tác giả:** Thảo (AIE2)
> * **Ngày tạo:** 2026-07-16
> * **Ngày cập nhật:** 2026-07-20
> * **Dự án:** AIE2 - Shopping Copilot (Task Force 2)

---

## 1. Bối cảnh

Ban đầu, Shopping Copilot được thiết kế dựa trên vòng lặp ReAct (Reasoning and Acting) truyền thống bằng thư viện LangChain, dự kiến kết nối với các mô hình qua Groq API. 

Tuy nhiên, trong quá trình phát triển và kiểm thử thực tế với bài toán thương mại điện tử (đặc biệt là yêu cầu đa ngôn ngữ Anh-Việt, hỗ trợ ngữ cảnh so sánh sản phẩm, và tính ổn định cao), kiến trúc ReAct bộc lộ nhiều điểm yếu:
1. **Khó dự đoán (Unpredictability):** LLM tự quyết định gọi tool nào và gọi bao nhiêu lần, dễ dẫn đến vòng lặp vô tận (infinite loop) hoặc gọi sai tool, tiêu tốn token.
2. **Hard-coded rules:** Việc xử lý các trường hợp đặc biệt (như xin chào, các lỗi hệ thống, thay đổi ngôn ngữ) bị gắn cứng (hard-coded) bằng lệnh if/else trong Python, phá vỡ khả năng giao tiếp ngôn ngữ tự nhiên linh hoạt của LLM.
3. **Mất ngữ cảnh (Context Loss):** ReAct loop thường xuyên quên ngữ cảnh của các sản phẩm được tìm kiếm trước đó khi người dùng đưa ra các câu hỏi tiếp nối mang tính chỉ định (ví dụ: "cái thứ 2 có tốt không?").

---

## 2. Quyết định

Chúng tôi quyết định **loại bỏ kiến trúc ReAct truyền thống** và thay thế bằng **Kiến trúc 6 lớp Intent-Driven Modular (Điều hướng theo Ý định)**, sử dụng mô hình Amazon Nova Lite qua AWS Bedrock. 

Đồng thời, áp dụng chính sách **Zero Hard-Rules** (Không gắn cứng quy tắc): mọi luồng phản hồi cuối cùng đều phải đi qua LLM để đảm bảo tính tự nhiên và đa ngôn ngữ.

---

## 3. Chi tiết thiết kế Kiến trúc 6 Lớp

Thay vì để LLM tự do gọi tool trong một vòng lặp `while`, hệ thống chia luồng suy nghĩ thành các giai đoạn tách biệt, quản lý state rõ ràng:

### Lớp 1: Intent Parser (Phân tích Ý định)
- **Đầu vào:** Câu nói của người dùng và Ngữ cảnh hiện tại (các sản phẩm vừa tìm kiếm).
- **Xử lý:** LLM chỉ làm một việc duy nhất là phân tích câu nói thành một chuỗi JSON chuẩn (Intent Schema). Nó xác định `task_type` (search, get_reviews, rank, add_to_cart, v.v.), trích xuất tham số (`price_max`, `currency`), và phân giải các đại từ chỉ định (context references như "cái này", "cái thứ hai") dựa trên ngữ cảnh (1-based index).
- **Bảo mật:** Đảm bảo LLM hiểu chính xác ý định bằng bất kỳ ngôn ngữ nào trước khi hệ thống hành động.

### Lớp 2: Generic Planner (Lập Kế Hoạch)
- **Đầu vào:** Intent JSON từ Lớp 1.
- **Xử lý:** Code Python (không dùng LLM) nhận Intent và tạo ra một danh sách các Tool cần gọi (Execution Plan). 
- **Tính Modular (Dynamic):** Kế hoạch là các mảnh ghép (Lego blocks). Ví dụ, nếu Intent chứa `needs_reviews=True`, Planner sẽ tự động nối thêm mảnh ghép `get_product_reviews_tool` vào cuối kế hoạch.

### Lớp 3: Executor (Thực thi)
- **Đầu vào:** Execution Plan.
- **Xử lý:** Gọi các tool tương ứng thông qua gRPC/REST. Ở bước này, các tham số như `$PREV` (ID sản phẩm từ bước trước) hoặc `last_product_id` từ Session Context sẽ được resolve tự động.

### Lớp 4: Evidence Aggregator (Tổng hợp Bằng Chứng)
- **Đầu vào:** Kết quả từ Executor.
- **Xử lý:** Gom toàn bộ kết quả JSON từ các tool lại thành một tệp "Evidence" (Bằng chứng). Dữ liệu rác bị loại bỏ, chỉ giữ lại các trường quan trọng (Tên sản phẩm, Giá, Điểm đánh giá). Evidence cũng được nhúng siêu dữ liệu (`__intent_meta__`) để truyền ý định gốc sang bước cuối.

### Lớp 5 & 6: Answer Generator & Grounding (Sinh Câu Trả Lời)
- **Đầu vào:** Tệp Evidence và câu hỏi gốc của người dùng.
- **Xử lý:** LLM (với System Prompt khắt khe) đọc Evidence và sinh ra câu trả lời cuối cùng. 
- **Đa ngôn ngữ & Zero Hard-Rules:** LLM tự động phát hiện ngôn ngữ của người dùng và trả lời bằng ngôn ngữ đó. Mọi kịch bản từ chối (unsupported cart action), xin chào (greeting), hay thông báo lỗi đều do LLM tự sinh ra bằng ngôn ngữ phù hợp, không còn bị gắn cứng chuỗi Tiếng Anh trong code.

---

## 4. Hệ quả

### Ưu điểm
- **Độ tin cậy 100% về luồng gọi Tool:** Hệ thống không bao giờ bị kẹt trong vòng lặp vô tận vì Planner đã ấn định số lượng tool trước khi chạy.
- **Bảo mật dữ liệu (Zero Hallucination):** Ở lớp Answer Generator, LLM bị cấm tự bịa dữ liệu và chỉ được phép tóm tắt từ Evidence JSON.
- **Đa ngôn ngữ hoàn hảo:** Tách biệt việc "Hiểu" (Intent Parser) và "Trả lời" (Answer Generator), giúp bot giao tiếp tự nhiên bằng cả Tiếng Việt và Tiếng Anh mà không cần phải if/else.
- **Phân biệt rạch ròi Search và Rank:** Dễ dàng xử lý các câu hỏi phức tạp như "cái nào rẻ hơn" (Compare/Rank trong ngữ cảnh hiện tại) so với "còn cái nào rẻ hơn không" (Search ra ngoài CSDL).

### Đánh đổi
- Độ trễ (Latency) tăng nhẹ do phải gọi LLM 2 lần cho mỗi request (1 lần cho Intent, 1 lần cho Synthesis) so với thiết kế lý tưởng gọi LLM 1 lần. Tuy nhiên, mô hình Nova Lite đủ nhanh để bù đắp.
