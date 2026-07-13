# Hướng Dẫn Chạy & Thử Nghiệm Với Mock Data (AI Baseline)

Tài liệu này hướng dẫn chi tiết các bước để khởi động hệ thống tối giản ở môi trường cục bộ (Local) và thực hiện đo đạc các chỉ số hiệu năng (Latency, Error Rate) của Mock LLM.

---

## 1. Khởi động các dịch vụ Mock trên Docker

Để tiết kiệm tài nguyên máy cá nhân (RAM/CPU), chúng ta chỉ chạy các dịch vụ tối thiểu cần thiết để thử nghiệm tính năng AI thay vì khởi chạy toàn bộ 27 dịch vụ của hệ thống.

### Lệnh khởi chạy:
Mở terminal tại thư mục `techx-corp-platform/` và chạy:
```bash
docker compose up -d postgresql product-catalog flagd otel-collector jaeger llm product-reviews
```

### Kiểm tra trạng thái:
Gõ lệnh sau để đảm bảo các container đều đang ở trạng thái `Up`:
```bash
docker compose ps
```

*Lưu ý: Cấu hình cổng của dịch vụ `product-reviews` trong `docker-compose.yml` đã được điều chỉnh thành `"3551:${PRODUCT_REVIEWS_PORT}"` để ánh xạ trực tiếp và cố định cổng `3551` của gRPC ra máy chủ vật lý, giúp các script chạy bên ngoài container có thể kết nối được.*

---

## 2. Đo đạc hiệu năng tự động bằng Python script

Chúng ta sử dụng script [repro/benchmark.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/repro/benchmark.py) để tự động hóa quá trình gửi request và tính toán các phân vị độ trễ (Average, p95, p99) cùng tỷ lệ lỗi.

### Hướng dẫn chạy:
1. Di chuyển ra thư mục `repro/` tại thư mục gốc dự án:
   ```bash
   cd ../repro
   ```
2. Đảm bảo bạn đã cài đặt thư viện gRPC cho Python:
   ```bash
   pip install grpcio
   ```
3. Chạy script đo đạc:
   ```bash
   python benchmark.py
   ```

### Diễn giải kết quả:
* **Tỉ lệ lỗi (Error Rate) = 0.00%**: Cuộc gọi thành công, dữ liệu mock hoạt động ổn định.
* **Average Latency (~40ms - 50ms)**: Đây là độ trễ xử lý mặc định của Mock Server khi lấy trực tiếp dữ liệu từ file JSON cục bộ kết hợp với query DB Postgres.

---

## 3. Gọi kiểm tra thủ công bằng gRPC CLI (`grpcurl`)

Nếu muốn giả lập gửi một request đơn lẻ từ dòng lệnh để debug nhanh phản hồi của AI Assistant:

```bash
grpcurl -plaintext \
  -d '{"product_id": "L9ECAV7KIM", "question": "Can you summarize the product reviews?"}' \
  localhost:3551 \
  demo.ProductReviewService/AskProductAIAssistant
```

---

## 4. Dọn dẹp và dừng hệ thống

Sau khi đo đạc xong số liệu và lưu lại vào báo cáo, bạn có thể tắt các container đi để giải phóng bộ nhớ RAM của máy:

Mở terminal tại thư mục `techx-corp-platform/` và chạy:
```bash
docker compose down --remove-orphans --volumes
```
