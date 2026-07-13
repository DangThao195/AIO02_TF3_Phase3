# ADR-002: Chiến Lược Caching & Fallback Cho Tầng AI (Product Reviews)

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-06
- **Tác giả / Ký tên**: Team AIO02 (Task Force 3)
- **Phạm vi tác động**: Microservice `product-reviews`, Tầng AI (AIE & AIOps)

---

## 1. Bối cảnh (Context)

Trong quá trình vận hành `product-reviews`, nhóm **AIO02** nhận diện 2 rủi ro kỹ thuật lớn:
1. **Rủi ro vỡ Ngân sách AWS ($300/tuần)**: Mỗi lượt xem sản phẩm (`GetProductReviews`) đều gọi LLM sinh tóm tắt làm tăng chi phí token không cần thiết khi 80% người dùng xem cùng các sản phẩm hot.
2. **Rủi ro vỡ SLO từ sự cố bơm vào (`llmRateLimitError` / HTTP 429)**: BTC sẽ kích hoạt lỗi HTTP 429 ngẫu nhiên hoặc làm chậm LLM. Nếu không có Fallback, request của khách hàng sẽ bị đơ hoặc lỗi 5xx.

---

## 2. Quyết Định Kiến Trúc (Decisions)

### **A. Chiến lược Caching (Tuần 1: In-Memory Dict $\rightarrow$ Tuần 2-3: Valkey riêng)**

#### **Quyết định Tuần 1**: Triển khai **In-Memory Dict** ngay trong `product_reviews_server.py`.
- **Cấu hình**: Cấu trúc `_summary_cache: dict[str, tuple[str, float]]` với `CACHE_TTL_SECONDS = 3600` (1 giờ).
- **Lý do KHÔNG dùng `valkey-cart` ngay trong Tuần 1**:
  1. **Memory limit chỉ 20Mi**: `valkey-cart` được thiết kế riêng cho `cart` service với hạn mức memory cực kỳ khiêm tốn (`limits.memory: 20Mi` trong `values.yaml`). Nhét LLM summary cache vào đây sẽ gây ra nguy cơ OOM làm mất state giỏ hàng, vi phạm SLO cứng của Giỏ hàng ($\ge 99.5\%$).
  2. **Coupling ngầm giữa các Service**: `valkey-cart` thuộc sở hữu của `cart`. Sử dụng chung sẽ tạo ra phụ thuộc chéo nguy hiểm khi team CDO bảo trì/thay đổi auth `valkey-cart`.
  3. **Thiếu dependency trong `requirements.txt`**: File `requirements.txt` của `product-reviews` chưa có thư viện `redis`. Thêm dependency đòi hỏi rebuild image và redeploy, tạo ra overhead không cần thiết cho Tuần 1.
  4. **Tóm tắt AI không cần Distributed Cache ở Phase 1**: Ở Tuần 1, `product-reviews` chạy 1-2 replicas. In-memory dict trên từng pod là quá đủ để cắt giảm 80% số lượt gọi LLM.

#### **Điều kiện Upgrade lên Valkey riêng (`valkey-llm-cache`) ở Tuần 2-3**:
- Khi `product-reviews` scale lên $\ge 3$ replicas (tỷ lệ cache miss giữa các pods tăng lên).
- Hoặc khi cần duy trì cache TTL qua các lần restart pod.
- Khi nâng cấp, nhóm sẽ deploy một component Helm riêng `valkey-llm-cache`, **tuyệt đối KHÔNG dùng chung `valkey-cart`**.

---

### **B. Chiến lược Fallback & Retry (Xử lý HTTP 429 & Timeout)**

1. **Retry Mechanism**:
   - Bọc toàn bộ lời gọi LLM client bằng khối `try/except`.
   - Với các lỗi tạm thời (HTTP status 429 Rate Limit, Connection Timeout): Thực hiện tối đa **2 retries** với **Exponential Backoff** (chờ 0.5s $\rightarrow$ 1.5s).
2. **Fallback Mechanism**:
   - Nếu Retry vẫn thất bại hoặc LLM bị sập hẳn:
     - *Ưu tiên 1*: Trả về bản tóm tắt đã lưu trong Cache (cho dù đã quá TTL).
     - *Ưu tiên 2*: Nếu không có Cache, trả về thông báo an toàn: *"Tóm tắt tạm thời không khả dụng. Vui lòng tham khảo các đánh giá chi tiết bên dưới."*
   - **Cam kết SLO**: **Tuyệt đối KHÔNG hiển thị tóm tắt bịa đặt / sai lệch** cho khách và KHÔNG để request bị treo quá 2 giây.

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
- Giảm ngay **80% chi phí token LLM** cho TF3, đáp ứng trần ngân sách $300/tuần.
- Giảm latency từ 1.4s xuống **<50ms** cho 80% request xem sản phẩm có cache.
- Đảm bảo giao diện storefront không bao giờ bị đơ khi BTC kích hoạt lỗi `llmRateLimitError`.

### **Đánh đổi chấp nhận trong Tuần 1**:
- Khi pod `product-reviews` bị restart, cache in-memory bị xoá $\rightarrow$ Pod gọi LLM lại 1 lần cho sản phẩm đó (không ảnh hưởng tới tính khả thi của hệ thống).
