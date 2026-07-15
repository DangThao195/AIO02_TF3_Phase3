# ADR 0004: Thiết kế hệ thống Đánh giá Độ trung thực của văn bản tóm tắt

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Thịnh (AIE1) & Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-15

---

## 1. Bối cảnh
Khi sử dụng mô hình ngôn ngữ lớn thực tế để tạo bản tóm tắt các đánh giá sản phẩm, hệ thống đối mặt với nguy cơ xảy ra hiện tượng ảo giác — tức là mô hình tự tạo ra các thông tin không có thực hoặc mâu thuẫn trực tiếp với nội dung đánh giá gốc của khách hàng trong cơ sở dữ liệu. Việc hiển thị một bản tóm tắt sai lệch cho khách hàng sẽ gây ảnh hưởng nghiêm trọng đến uy tín thương hiệu và tính chính xác của dữ liệu.

Do đó, chúng tôi cần một cơ chế tự động kiểm tra và đánh giá độ trung thực của bản tóm tắt ngay sau khi mô hình tạo ra và trước khi phản hồi về phía giao diện người dùng.

---

## 2. Quyết định
Chúng tôi quyết định thiết kế và tích hợp một bộ đánh giá độ trung thực nội tuyến hoạt động như một chốt chặn chất lượng ngay sau cuộc gọi LLM tạo tóm tắt:

1. **Khởi chạy Fidelity Judge nội tuyến:**
   * Ngay sau khi nhận kết quả tóm tắt từ mô hình chính, server sẽ thực hiện một cuộc gọi thứ hai tới mô hình đánh giá — mặc định sử dụng **AWS Bedrock Nova Micro `amazon.nova-micro-v1:0`** để tối ưu hóa thời gian phản hồi và chi phí.
   * Đầu vào của Judge bao gồm: ID sản phẩm, danh sách các đánh giá gốc từ PostgreSQL và bản tóm tắt ứng viên vừa được tạo.

2. **Quy tắc Kiểm duyệt Nghiêm ngặt:**
   * Yêu cầu mô hình Judge phân tích và trả về kết quả định dạng JSON chứa các trường: `approved`, `unsupported_claims` (số lượng thông tin không có bằng chứng đối chiếu), và `contradicted_claims` (số lượng thông tin mâu thuẫn trực tiếp với đánh giá gốc).
   * Bản tóm tắt chỉ được duyệt khi số lượng thông tin không bằng chứng và thông tin mâu thuẫn đều bằng 0.

3. **Cơ chế Xử lý khi Bác bỏ:**
   * Nếu bộ đánh giá trả về `approved: false` (phát hiện có lỗi ảo giác hoặc sai lệch thông tin), hệ thống sẽ lập tức loại bỏ bản tóm tắt đó và trả về một thông báo lỗi tiếng Anh cố định cho client: `"The summary cannot be verified. Please try again later."` thay vì đẩy thông tin sai lệch lên storefront.

---

## 3. Chi tiết Thiết kế

Cấu trúc gợi ý nhắc lệnh hệ thống cho Judge được thiết lập cố định để ép định dạng đầu ra:
```text
You are a strict factuality judge for product-review summaries.
Your only job is to detect hallucinations.
Compare the candidate summary against the provided raw reviews.
Return JSON only with these fields:
{
  "approved": true | false,
  "unsupported_claims": integer,
  "contradicted_claims": integer,
  "reason": string
}
```

Quy trình hoạt động trong mã nguồn:
1. Gọi mô hình chính tạo tóm tắt ứng viên.
2. Kiểm tra nếu câu trả lời không phải là thông điệp ngoài luồng hoặc không có thông tin, tiến hành gọi hàm `evaluate_summary_fidelity` trong `guardrails/evaluator.py`.
3. Khởi tạo client kết nối với Bedrock hoặc OpenAI tương ứng, chạy prompt đánh giá với nhiệt độ bằng 0.0 để đảm bảo tính nhất quán.
4. Trích xuất và phân tích cú pháp JSON từ phản hồi của Judge để kiểm tra các chỉ số lỗi.
5. Nếu không đạt yêu cầu chất lượng, ghi nhận cảnh báo vào log hệ thống để phục vụ kiểm toán và trả về thông báo từ chối xác thực.

---

## 4. Hệ quả
* **Bảo vệ Chất lượng Dữ liệu:** Đảm bảo 100% các bản tóm tắt hiển thị trên storefront đều trung thực và bám sát ý kiến của khách hàng thực tế, loại bỏ hoàn toàn các lỗi ảo giác nguy hại.
* **Tác động đến Độ trễ:** Việc thêm một cuộc gọi LLM thứ hai làm tăng tổng thời gian phản hồi của API. Để giảm thiểu tác động này:
   * Chúng tôi lựa chọn mô hình Nova Micro có kích thước nhỏ và tốc độ xử lý nhanh nhất.
   * Áp đặt giới hạn thời gian chờ nghiêm ngặt (timeout = 3.0 giây) cho cuộc gọi Judge.
* **Xử lý Sự cố**: Nếu cuộc gọi tới Judge bị lỗi hoặc quá thời gian chờ, hệ thống sẽ kích hoạt cơ chế Fallback tầng 2 để trả về kết quả an toàn.
