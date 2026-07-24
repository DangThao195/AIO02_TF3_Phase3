# ADR 0007: Thiết kế Redis Control Key `fallback_override`, Prometheus Telemetry & Graceful Shutdown

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Kiên (AIE1)
* **Ngày tạo:** 2026-07-23

---

## 1. Bối cảnh
Trong quá trình vận hành dịch vụ `product-reviews`, AIOps Engine cần có khả năng:
1. Chủ động ép dịch vụ hạ cấp (Force Fallback) thông qua tín hiệu điều khiển từ xa mà không cần restart container.
2. Giám sát lượng sự cố kết nối LLM / Rate Limit / Timeout qua Prometheus metric tiêu chuẩn.
3. Đóng gRPC connection một cách êm ái (Graceful Shutdown) khi hạ tải pod hoặc bảo trì hệ thống.

---

## 2. Giải pháp Đề xuất

### 2.1 Redis Key Control Schema
* **Key Name:** `product_reviews:fallback_override`
* **Data Type:** String
* **Giá trị hợp lệ:** `"true"`, `"1"` (bật Force Fallback) hoặc `"false"`, `"0"` (tắt).
* **Hành vi:** Trước khi thực hiện cuộc gọi sang LLM (AWS Bedrock hoặc OpenAI), handler `get_ai_assistant_response()` đọc key `product_reviews:fallback_override` từ Redis. Nếu active, hệ thống ngay lập tức chuyển hướng sang luồng Static Summary / PostgreSQL Cache mà không gửi bất kỳ request nào tới Bedrock/OpenAI.

### 2.2 Schema Prometheus Custom Metrics
Bổ sung counter metric mới vào `metrics.py`:
* **Metric Name:** `app_ai_fallback_total`
* **Description:** Tổng số lần fallback của ai_assistant
* **Labels:**
  * `source`: Nguồn nguyên nhân hạ cấp (`"redis_override"`, `"rate_limit"`, `"timeout"`, `"bedrock_error"`, `"circuit_breaker"`).
  * `error`: Loại lỗi hoặc mã HTTP (`"forced"`, `"429"`, `"timeout"`, `"500"`).

### 2.3 Cơ chế Graceful Shutdown & Auto-Reconnection
1. **gRPC Health Check Status:** Đăng ký service `grpc_health.v1.health`. Trạng thái mặc định khi chạy là `SERVING`.
2. **Signal Handling (SIGTERM/SIGINT):** Khi nhận được tín hiệu ngắt từ K8s/AIOps Engine:
   * Chuyển trạng thái Health Check thành `NOT_SERVING`.
   * Gọi `server.stop(grace=5.0)` để chờ các gRPC stream/request dở dang hoàn tất trong 5 giây trước khi đóng hoàn toàn.
3. **Auto-Reconnection cho Dependencies:** Bọc truy vấn PostgreSQL connection pool & Redis client bằng cơ chế retry auto-reconnection để tránh crash startup nếu dependencies khởi động chậm hơn service.
