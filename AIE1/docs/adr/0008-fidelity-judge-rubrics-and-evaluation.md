# ADR 0008: Thống nhất Bộ Rubric Đánh Giá Độ Trung Thực (Fidelity) cho LLM-as-a-Judge

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Khoa (Leader AIE1), Thịnh (AIE1)
* **Ngày tạo:** 2026-07-23

---

## 1. Bối cảnh

Để đảm bảo hệ thống trả lời và tóm tắt đánh giá sản phẩm (**Product Reviews & Ask AI**) hoạt động an toàn, không bị ảo giác (hallucination) hoặc bóp méo thông tin từ cơ sở dữ liệu gốc, AIE1 cần tích hợp cơ chế **LLM-as-a-Judge** trực tuyến (Runtime Fidelity Gate).

Theo chỉ thị của dự án và các nghiên cứu từ tài liệu `LLM-as-a-Judge.pdf`, bộ chấm điểm tự động bằng mô hình ngôn ngữ lớn (Judge) cần phải được thiết lập dựa trên một **bộ tiêu chí đánh giá (Rubric)** rõ ràng, thống nhất, và phải được đối chiếu độ chính xác với nhãn của con người (Human Labels) để đảm bảo độ tin cậy thông qua chỉ số **Agreement Rate (Tỷ lệ đồng thuận)** đạt tối thiểu **80%**.

---

## 2. Quyết định: Bộ Tiêu Chỉ Đánh Giá (Rubrics) & Quy Trình Đo Đạc

Nhóm AIE1 thống nhất thông qua bộ Rubrics đánh giá độ trung thực (Fidelity) và quy trình đo đạc chất lượng của Judge như sau:

### 2.1. Cấu trúc Rubrics Chi Tiết của LLM Judge

Mỗi câu trả lời từ trợ lý AI (Candidate Summary) khi đưa vào kiểm duyệt qua Judge sẽ được bẻ nhỏ thành các tuyên bố đơn lẻ (claims) và chấm điểm theo 3 tiêu chí cốt lõi:

| Tiêu chí | Định nghĩa | Cách dán nhãn của Judge |
| :--- | :--- | :--- |
| **Faithfulness**<br>(Tính trung thực) | Các thông tin, tuyên bố trong bản tóm tắt phải hoàn toàn bắt nguồn trực tiếp từ các review thật trong database. | - **`supported`**: Tuyên bố đúng sự thật, có bằng chứng review đối chiếu.<br>- **`unsupported`**: Tuyên bố tự vẽ ra, không tìm thấy bằng chứng trong review.<br>- **`contradicted`**: Tuyên bố mâu thuẫn trực tiếp với nội dung của review. |
| **Aspect Coverage**<br>(Độ bao phủ khía cạnh) | Nội dung tóm tắt phải trả lời trực diện vào khía cạnh khách hàng hỏi (Ví dụ: hỏi về "độ bền" thì không được chỉ tóm tắt về "thiết kế"). | - **`relevant`**: Trả lời trúng khía cạnh được hỏi.<br>- **`irrelevant`**: Lạc đề, không tập trung vào câu hỏi (sẽ bị loại bỏ hoặc trả về `OUT_OF_SCOPE`). |
| **Sentiment Alignment**<br>(Độ nhất quán cảm xúc) | Cảm xúc chủ đạo của bản tóm tắt phải tương thích với tỷ lệ điểm số (score) trong database (Ví dụ: review toàn 1-2 sao thì tóm tắt không được viết là "khách hàng cực kỳ hài lòng"). | Đối chiếu rating thực tế của reviews được trích xuất từ database (Ví dụ: review < 3 sao tính là tiêu cực) để làm căn cứ đánh giá sự thiên lệch cảm xúc. |

### 2.2. Cơ chế Duyệt tại Cổng Runtime (Runtime Gate Policy)

* **Điều kiện Thông Qua (PASS):** Bản tóm tắt chỉ được duyệt và lưu vào Redis Cache khi và chỉ khi **100% các claims** được dán nhãn là **`supported`** (tức là `unsupported_claims = 0` và `contradicted_claims = 0`).
* **Hành vi Fail-Closed:** 
  * Nếu phát hiện bất kỳ claim nào bị dán nhãn `unsupported` hoặc `contradicted` → Trả về thông báo lỗi bảo mật: `The summary cannot be verified. Please try again later.`.
  * Nếu cuộc gọi tới Judge bị lỗi hoặc trả về định dạng JSON lỗi sau khi đã tự động retry tối đa 3 lần → Trả về thông báo lỗi hệ thống: `The AI is busy right now. Please try again later.`.

---

## 3. Quy trình Đánh giá Độ tin cậy (Agreement Rate)

Để chứng minh LLM Judge có khả năng chấm điểm chuẩn xác tương đương con người, nhóm thiết lập quy trình đo đạc offline:

1. **Bộ tập dữ liệu chuẩn của con người (Human Labeled Dataset):** Gồm 10 case mẫu được cả nhóm gán nhãn thủ công lưu tại tệp `repro/datasets/human_labeled_cases.jsonl`.
2. **Quy trình đo:** Chạy script đánh giá `repro/eval_support/judge_agreement.py` để so sánh các nhãn do LLM Judge tự động chấm với nhãn con người đã gán:
   $$\text{Agreement Rate} = \frac{\text{Số ca Judge chấm khớp với Người}}{\text{Tổng số ca gán nhãn (10)}} \times 100\%$$
3. **Ngưỡng nghiệm thu (Quality Gate):** Chỉ số **Agreement Rate phải đạt $\ge 80\%$** thì bộ Judge mới đủ điều kiện đóng gói lên môi trường Production.

---

## 4. Lý do chọn phương án

* **Tách biệt Claim-level Evaluation:** Việc bẻ nhỏ câu trả lời thành từng claim giúp Judge hoạt động cực kỳ chi tiết, tránh việc đánh giá chung chung cả đoạn văn gây ra lỗi nhận diện sai (False Positive).
* **Định lượng rõ ràng:** Các chỉ số `supported`, `unsupported`, và `contradicted` cung cấp bằng chứng rõ ràng trong bảng log kiểm toán bất đồng bộ (`fidelity_audit`) của PostgreSQL để phục vụ báo cáo chất lượng sau này.
* **Độ tin cậy được chứng thực:** Con số Agreement Rate $\ge 80\%$ là tiêu chuẩn công nghiệp bảo chứng cho việc sử dụng AI thay thế con người trong các khâu kiểm duyệt tự động.

---

## 5. Danh sách phê duyệt từ các thành viên

| Thành viên                  | Vai trò         | Chữ ký ký duyệt | Trạng thái |
| :-------------------------- | :-------------- | :-------------- | :--------- |
| **Lê Hải Khoa**             | Leader AIE1     | *KhoaDM*        | Đã duyệt   |
| **Nguyễn Tiến Hoàng Thịnh** | Thành viên AIE1 | *ThinhTQ*       | Đã duyệt   |
