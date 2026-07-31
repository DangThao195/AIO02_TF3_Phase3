# ADR 0002: Thiết kế cơ chế Fallback Graceful Degradation nhiều tầng cho kết nối LLM

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Kiên (AIE1) & Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-13

---

## 1. Bối cảnh
Khi đưa mô hình ngôn ngữ lớn thực tế qua dịch vụ AWS Bedrock vào vận hành, dịch vụ `product-reviews` phải đối mặt với các nguy cơ gián đoạn từ API bên thứ ba như lỗi kết nối, lỗi quá hạn mức rate limit 429, hoặc lỗi máy chủ 5xx.

Hệ thống cũ không bắt ngoại lệ tại hàm `get_ai_assistant_response()`. Điều này khiến gRPC handler bị crash khi LLM gặp sự cố, trả về HTTP 500 cho storefront và làm đơ giao diện người dùng. Để bảo đảm cam kết SLO và tăng tính chịu lỗi của hệ thống, chúng tôi cần thiết kế một cơ chế dự phòng hoạt động ổn định dưới mọi tình huống.

---

## 2. Giải pháp Đề xuất

Chúng tôi quyết định áp dụng mô hình kiến trúc **Graceful Degradation 3 tầng** kết hợp với **cơ chế Thử lại tự động** bọc quanh cuộc gọi LLM:

```
Tầng 1 (Chính)   → AWS Bedrock Nova Lite qua SDK boto3 trực tiếp để lấy phản hồi thời gian thực
        ↓ Gọi lỗi (Thử lại tối đa 3 lần với trễ lũy thừa + Jitter)
        ↓ Kiệt sức lần thử lại / Lỗi nghiêm trọng không thể thử lại
Tầng 2 (Dự phòng 1) → Tóm tắt tĩnh từ PostgreSQL thông qua cơ chế lưu đè khi thành công
        ↓ Không tìm thấy dữ liệu trong cơ sở dữ liệu
Tầng 3 (Dự phòng 2) → Thông điệp mặc định: "The AI is busy right now. Please try again later."
```

### 2.1 Cơ chế Thử lại Tự động (Automatic Retry)

Trước khi quyết định hạ cấp xuống tầng dự phòng tiếp theo, để đối phó với các lỗi mạng tạm thời hoặc lỗi giới hạn tần suất (Rate Limit 429), hệ thống tích hợp thư viện `tenacity` để tự động thử lại lời gọi LLM:
* **Thuật toán**: Exponential Backoff với Full Jitter (trễ lũy thừa ngẫu nhiên) để tránh hiện tượng cộng hưởng tải lên hệ thống API (Thundering Herd).
* **Số lần thử lại tối đa**: 3 lần.
* **Thời gian chờ ban đầu**: 1.0 giây.
* **Thời gian chờ tối đa**: 8.0 giây.
* **Quy tắc phân loại lỗi**:
  * *Cho phép thử lại (Retryable)*: Rate Limit (HTTP 429), Lỗi máy chủ (HTTP 500/502/503/504), hoặc Lỗi kết nối mạng (APIConnectionError).
  * *Không cho phép thử lại (Non-retryable)*: Lỗi cú pháp (HTTP 400), Lỗi xác thực tài khoản (HTTP 401/403) — các lỗi này sẽ hạ cấp xuống Tầng 2 ngay lập tức mà không cần thử lại.

### 2.2 Chi tiết vận hành từng tầng

1. **Tầng 1 — Chính:** Gọi trực tiếp mô hình qua SDK `boto3` Converse API. Nếu cuộc gọi thành công, dữ liệu được trả về gRPC đồng thời lưu đè vào cơ sở dữ liệu làm bộ nhớ đệm phục vụ cho lần sau. Nếu xảy ra bất kỳ lỗi mạng hoặc lỗi quá thời gian chờ nào sau khi đã thử lại tối đa 3 lần, hệ thống bắt ngoại lệ và hạ cấp xuống Tầng 2.
2. **Tầng 2 — Tóm tắt tĩnh từ PostgreSQL:** Hệ thống thực hiện truy vấn bảng `product_summaries` trong PostgreSQL theo `product_id`. Nếu tồn tại bản tóm tắt tĩnh được tạo trước bởi tiến trình định kỳ hoặc lưu từ lần chạy thành công trước, hệ thống sẽ trả về bản tóm tắt này. Khách hàng vẫn nhận được thông tin sản phẩm thực tế dù không phải thời gian thực.
3. **Tầng 3 — Thông điệp mặc định:** Nếu không tìm thấy dòng dữ liệu nào trong cơ sở dữ liệu đối với sản phẩm mới (hoặc khi cuộc gọi LLM gặp sự cố hạ tầng), hệ thống trả về thông điệp lỗi tĩnh: *"The AI is busy right now. Please try again later."* Tầng này đảm bảo cuộc gọi gRPC luôn thành công và trả về mã HTTP 200 thay vì gây crash giao diện.

---

## 3. Đo lường & Giám sát

Để phân biệt các phản hồi thực tế và phản hồi dự phòng trên hệ thống giám sát qua Jaeger và Prometheus, chúng tôi bổ sung:
* **Thuộc tính nhãn (Span Attributes)**:
  * `app.fallback.triggered` kiểu boolean: Đánh dấu có kích hoạt dự phòng hay không.
  * `app.fallback.source` kiểu string: Ghi nhận nguồn dự phòng, nhận giá trị `"redis_override"`, `"rate_limit"`, `"timeout"`, `"candidate"`, hoặc `"none"`.
* **Nhật ký (Logs)**: Ghi log mức độ `WARNING` kèm mã lỗi gốc của Bedrock để phục vụ mục đích kiểm toán.
* **Chỉ số đo lường (Metrics)**: Đẩy chỉ số counter `app_ai_fallback_total` phân loại theo nhãn `source` để giám sát sức khỏe API LLM.

---

## 4. Hiện trạng Triển khai thực tế

Trong quá trình phát triển mã nguồn thực tế tại [fallback.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/guardrails/fallback.py) and [product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIO02_TF3_Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py), cơ chế fallback đã được tinh chỉnh so với thiết kế 3 tầng ban đầu để tối ưu hóa tài nguyên hệ thống và bảo vệ chất lượng dữ liệu:

* **Bỏ qua Tầng 2 (PostgreSQL Static Summary):** Hệ thống thực tế **chưa triển khai** việc truy cập Postgres để lấy tóm tắt cũ nhằm tránh hiển thị thông tin lỗi thời không đồng bộ với reviews mới cho khách hàng.
* **Fail-Closed 2 nhánh lỗi tĩnh:**
  * **Nhánh 1 (Lỗi hạ tầng/API/Timeout):** Trả về `FALLBACK_SUMMARY_MESSAGE` = `"The AI is busy right now. Please try again later."` (sau khi đã retry tự động 3 lần qua tenacity).
  * **Nhánh 2 (Lỗi chất lượng/Fidelity Gate/Guardrail chặn):** Trả về `UNVERIFIED_SUMMARY_MESSAGE` = `"The summary cannot be verified. Please try again later."`.
* **Redis Actuator:** Hỗ trợ key `product_reviews:fallback_override` để cưỡng bức chuyển hướng sang fallback theo lệnh điều khiển từ xa của AIOps Engine mà không cần khởi động lại container.
* **Span Attributes thực tế:** `app.fallback.source` nhận các giá trị: `"redis_override"`, `"rate_limit"`, `"timeout"`, `"candidate"`, hoặc `"none"`. Metric counter là `app_ai_fallback_total`.
