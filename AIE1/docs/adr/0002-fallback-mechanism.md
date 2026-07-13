# ADR 0002: Thiết kế cơ chế Fallback Graceful Degradation nhiều tầng cho kết nối LLM

* **Trạng thái:** Đã phê duyệt (Accepted)
* **Tác giả:** Kiên (AIE1) & Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-13

---

## 1. Bối cảnh (Context)
Khi đưa LLM thật (AWS Bedrock) vào vận hành, dịch vụ `product-reviews` phải đối mặt với các nguy cơ gián đoạn từ API bên thứ ba (lỗi kết nối, lỗi quá hạn mức rate limit 429, hoặc API downtime 5xx). 

Hệ thống cũ không bắt ngoại lệ (naked exception) tại hàm `get_ai_assistant_response()`. Điều này khiến gRPC handler bị crash khi LLM gặp sự cố, trả về HTTP 500 cho storefront và làm đơ giao diện người dùng. Để bảo đảm cam kết SLO và tăng tính chịu lỗi của hệ thống, chúng tôi cần thiết kế một cơ chế dự phòng hoạt động ổn định dưới mọi tình huống.

---

## 2. Giải pháp Đề xuất (Proposed Solution)

Chúng tôi quyết định áp dụng mô hình kiến trúc ** Graceful Degradation 3 tầng ** bọc quanh cuộc gọi LLM:

```
Tầng 1 (Primary)    → Bedrock Nova Lite via LiteLLM (Real-time LLM Response)
        ↓ Lỗi / Timeout / Quá tải 429
Tầng 2 (Fallback 1) → Static Summary từ PostgreSQL (Pre-computed / Cache-on-success)
        ↓ Không tìm thấy dữ liệu trong DB
Tầng 3 (Fallback 2) → Generic Message thân thiện (Last Resort)
```

### Chi tiết vận hành từng tầng:

1. **Tầng 1 — Bedrock Nova Lite (Primary):** Gọi trực tiếp mô hình qua LiteLLM proxy. Nếu cuộc gọi thành công, dữ liệu được trả về gRPC đồng thời lưu đè vào DB làm cache (Cache-on-success). Nếu xảy ra bất kỳ lỗi mạng hoặc timeout nào, hệ thống bắt ngoại lệ và hạ cấp xuống Tầng 2.
2. **Tầng 2 — Static Summary từ PostgreSQL:** Hệ thống thực hiện truy vấn bảng `product_summaries` trong PostgreSQL theo `product_id`. Nếu tồn tại bản tóm tắt tĩnh (được tạo trước bởi batch job định kỳ hoặc lưu từ lần chạy thành công trước), hệ thống trả về tóm tắt này. Người dùng vẫn nhận được thông tin sản phẩm thực tế dù không phải thời gian thực.
3. **Tầng 3 — Generic Message (Last Resort):** Nếu không tìm thấy dòng dữ liệu nào trong DB (sản phẩm mới chưa có cache/batch), hệ thống trả về một thông điệp thân thiện cố định: *"Product review summary is temporarily unavailable. Please try again in a few moments."* Tầng này đảm bảo cuộc gọi luôn thành công (HTTP 200) thay vì crash lỗi trắng trang.

---

## 3. Đo lường & Giám sát (Observability)

Để phân biệt các phản hồi thực tế và phản hồi fallback trên hệ thống giám sát (Jaeger/Prometheus), chúng tôi bổ sung:
* **Span Attributes**:
  * `app.fallback.triggered` (boolean): Đánh dấu có kích hoạt fallback hay không.
  * `app.fallback.source` (string): Ghi nhận nguồn fallback (`database` | `generic_message` | `none`).
* **Logs**: Ghi log mức độ `WARNING` kèm mã lỗi gốc của Bedrock để phục vụ mục đích kiểm toán (audit trail).
* **Metrics**: Đẩy metric counter `app.ai.fallback.total` phân loại theo nhãn `source` để giám sát sức khỏe API LLM.
