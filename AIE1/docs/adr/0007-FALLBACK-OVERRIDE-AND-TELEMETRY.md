# ADR 0007: Thiết kế Redis Control Key `fallback_override`, Prometheus Telemetry & Graceful Shutdown

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Kiên (AIE1) và Khoa (Leader AIE1)
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

---

## 3. Số liệu & Bằng chứng kiểm chứng thực tế (Metrics & Run Verification)

Để chứng minh tính đúng đắn của cơ chế Closed-Loop Auto-remediation, nhóm đã phối hợp với đội AIOps triển khai tệp mô phỏng replay [aiops_replay_sim.py](../../techx-corp-platform/src/product-reviews/aiops_replay_sim.py) thực thi kịch bản dập lỗi e2e.

### 3.1. Kịch bản chạy thử (Replay Scenario)
* **Bước 1: Trigger (Bơm lỗi):** Giả lập lỗi LLM spike với tỷ lệ lỗi tăng cao lên **82%** (vượt ngưỡng cảnh báo **30%**).
* **Bước 2: Action (Tự dập):** AIOps Controller phát hiện lỗi và set Redis key `product_reviews:fallback_override` thành `"true"`.
* **Bước 3: Verify (Kiểm chứng):** Gọi hàm `is_fallback_override_active()` thực tế trong `guardrails/cache.py` để verify. Kết quả trả về `True` (hệ thống tự động chuyển hướng và bypass thành công, đưa tỷ lệ lỗi về **0%**).
* **Bước 4: Rollback (Lùi lỗi):** AIOps Controller thực hiện xóa Redis key để đưa hệ thống về trạng thái ban đầu.
* **Bước 5: Recover (Phục hồi):** Verify hệ thống tự động phục hồi luồng LLM bình thường (tỷ lệ lỗi thực tế giảm về mức an toàn **2%**).

### 3.2. Bảng phân tích log kiểm thử hệ thống

Mọi pha tự động trong Closed-loop Auto-remediation được ghi nhận trực tiếp vào tệp nhật ký kiểm toán [audit_log.jsonl](../../techx-corp-platform/src/product-reviews/logs/audit_log.jsonl) như sau:

| Lượt chạy (Run ID) | Bước (Phase) | Trạng thái (Status) | Chi tiết kỹ thuật | Kết quả (Verdict) |
| :--- | :---: | :---: | :--- | :---: |
| `1983499c-...` | `start` | `OK` | Bắt đầu chạy kịch bản mô phỏng AIOps replay | Khởi động |
| `1983499c-...` | `trigger` | `FIRED` | Phát hiện LLM error spike ở mức **82%** (ngưỡng **30%**) | Kích hoạt cảnh báo |
| `1983499c-...` | `action` | `OK` | Controller thiết lập `product_reviews:fallback_override=true` | Ép hạ cấp an toàn |
| `1983499c-...` | `verify` | `OK` | `is_fallback_override_active() -> True`. Bypass LLM sang Cache | **PASS (Error 0%)** |
| `1983499c-...` | `rollback` | `OK` | Controller thực hiện xóa key `fallback_override` khỏi Redis | Hủy bỏ hạ cấp |
| `1983499c-...` | `recover` | `OK` | `is_fallback_override_active() -> False`. Khôi phục gọi LLM | **PASS (Error 2%)** |
| `1983499c-...` | `end` | `OK` | Kết thúc quy trình tự dập lỗi và rollback | Hoàn thành |

> [!NOTE]
> Chi tiết toàn bộ log thô định dạng JSON Lines có thể tham chiếu trực tiếp tại [audit_log.jsonl](../../techx-corp-platform/src/product-reviews/logs/audit_log.jsonl).
