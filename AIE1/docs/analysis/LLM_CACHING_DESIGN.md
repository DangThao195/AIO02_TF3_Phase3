# Thiết Kế Cơ Chế Caching Cho Hệ Thống LLM (AIE1 Task Force)

Tài liệu này mô tả chi tiết giải pháp thiết kế bộ nhớ đệm (Caching) cho dịch vụ AI Assistant của TechX Corp Platform nhằm tối ưu hóa chi phí token và giảm thiểu độ trễ (Latency).

---

## 1. Lý Do Cần Triển Khai Caching

1. **Tối ưu hóa Chi phí (Cost Optimization)**: Giảm số lượng yêu cầu trùng lặp gửi tới AWS Bedrock, tiết kiệm chi phí Token tiêu thụ.
2. **Tối ưu hóa Hiệu năng (Latency Reduction)**: 
   * Cuộc gọi LLM thông thường mất khoảng **~1.6 giây**.
   * Đọc từ Cache (PostgreSQL/Redis) mất **< 10 mili-giây** (nhanh hơn gấp 160 lần).
3. **Phục vụ cho luồng Fallback**: Cache đóng vai trò là nguồn dữ liệu cho tầng dự phòng số 2 khi AWS Bedrock gặp sự cố.

---

## 2. Cơ Chế Định Danh Khóa Cache (Cache Key Generation)

Hệ thống AI nhận hai loại yêu cầu khác nhau từ Storefront và sẽ áp dụng cách tạo Khóa Cache (Cache Key) tương ứng:

### A. Đối với Tóm tắt đánh giá mặc định (Default Summary)
* **Mô tả**: Khi người dùng mở trang chi tiết sản phẩm, hệ thống tự động tải bản tóm tắt chung các review của sản phẩm đó. Câu hỏi đầu vào là cố định.
* **Khóa Cache (Cache Key)**: Sử dụng mã sản phẩm `product_id` (Ví dụ: `L9ECAV7KIM`).
* **Vận hành**: Mọi người dùng truy cập sản phẩm này sẽ đọc chung một bản tóm tắt từ Cache.

### B. Đối với Hỏi đáp tự do (User Q&A)
* **Mô tả**: Người dùng nhập câu hỏi tùy ý vào ô chat. Các câu hỏi có thể khác nhau hoàn toàn.
* **Khóa Cache (Cache Key)**: Được băm thành mã SHA256 duy nhất từ chuỗi kết hợp mã sản phẩm và nội dung câu hỏi (sau khi đã chuẩn hóa viết thường và cắt khoảng trắng).
* **Công thức**: 
  $$\text{Cache Key} = \text{SHA256}(\text{product\_id} + \text{normalize}(\text{question}))$$
* **Vận hành**: Đảm bảo câu hỏi nào sẽ nhận được câu trả lời nấy. Chỉ khi có người hỏi trùng câu hỏi cho cùng một sản phẩm thì hệ thống mới tái sử dụng cache.

---

## 3. Quy Trình Vận Hành Của Hệ Thống Caching

```
              [Nhận Yêu Cầu (product_id, question)]
                                │
                      [Tính toán Cache Key]
                                │
                       (Kiểm tra trong Cache)
                             /        \
                    (Có dữ liệu)    (Không có dữ liệu - Cache Miss)
                         /                \
          [Trả về kết quả ngay lập tức]    [Gọi API AWS Bedrock]
          (Latency < 10ms, Cost: $0)              │
                                           [Nhận phản hồi từ Bedrock]
                                                  │
                                          [Ghi kết quả mới vào Cache]
                                                  │
                                           [Trả về cho Storefront]
                                           (Latency ~1.6s)
```

---

## 4. Cơ Chế Cập Nhật/Xóa Cache (Cache Invalidation)

Để tránh việc hiển thị thông tin cũ khi sản phẩm có đánh giá mới:
* **Trigger**: Khi khách hàng gửi một Review mới thành công vào PostgreSQL.
* **Hành động**: Hệ thống tự động xóa toàn bộ các bản ghi Cache liên quan đến `product_id` đó.
* **Kết quả**: Lượt truy cập tiếp theo sẽ bị Cache Miss, buộc hệ thống gọi Bedrock sinh tóm tắt mới và cập nhật lại cache.

---

## 5. Minh Họa Logic Mã Nguồn Python Đề Xuất

Dưới đây là cấu trúc code minh họa được chuẩn bị để tích hợp vào tệp **[product_reviews_server.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/AIE1/techx-corp-platform/src/product-reviews/product_reviews_server.py)**:

```python
import hashlib

def generate_cache_key(product_id: str, question: str) -> str:
    # Chuẩn hóa câu hỏi để tăng tỷ lệ khớp cache (loại bỏ khoảng trắng thừa, viết thường)
    normalized_q = " ".join(question.lower().strip().split())
    raw_key = f"{product_id}:{normalized_q}"
    return hashlib.sha256(raw_key.encode('utf-8')).hexdoking()

def get_cached_response(cache_key: str) -> str:
    # Truy vấn DB hoặc Redis để lấy câu trả lời đã lưu
    # SELECT response FROM ai_response_cache WHERE cache_key = %s
    pass

def save_to_cache(cache_key: str, product_id: str, response: str):
    # Lưu câu trả lời mới vào DB/Redis kèm metadata
    # INSERT INTO ai_response_cache (cache_key, product_id, response) VALUES (%s, %s, %s)
    pass

def invalidate_product_cache(product_id: str):
    # Xóa cache khi có review mới
    # DELETE FROM ai_response_cache WHERE product_id = %s
    pass
```
