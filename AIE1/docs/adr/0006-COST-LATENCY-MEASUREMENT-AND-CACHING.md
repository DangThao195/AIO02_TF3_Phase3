# ADR 0006: Đo lường Chi Phí/Độ Trễ và Tích Hợp Redis Caching Cho Dịch Vụ Product Reviews

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Thịnh (AIE1) & Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-24

---

## 1. Bối cảnh

Theo các chỉ thị vận hành từ Ban AI & Chất lượng, dịch vụ `product-reviews` cần xác lập bộ chỉ số đo lường hiệu năng thực tế (Cost/Latency) và tối ưu hóa hệ thống thông qua cơ chế Caching.

Trước khi tích hợp caching, toàn bộ 100% các request đều phải gọi API Bedrock (Nova Lite + Nova Micro) gây ra:
- **Độ trễ cao (Latency):** Trung vị p50 mất tới 2.82 giây do phụ thuộc vào I/O network.
- **Chi phí token lớn (Cost):** Tốn chi phí trùng lặp cho các câu hỏi giống nhau và có nguy cơ bị Rate Limit (HTTP 429).

Chúng tôi cần một giải pháp lưu trữ cache tối ưu và phương pháp đo đạc hiệu năng thực tế (Before vs After) để chứng minh hiệu năng.

---

## 2. Quyết định

Chúng tôi quyết định tích hợp cơ chế Caching dựa trên hạ tầng **Redis/Valkey** với các thiết kế sau:

### 2.1. Tại sao chọn Redis (Không chọn PostgreSQL làm cache chính)
* **Tốc độ (Performance):** Redis là In-Memory database, cho tốc độ đọc/ghi phản hồi `< 1ms` so với `5-15ms` của Postgres.
* **Tách biệt tải trọng (Resilience):** Tránh làm nghẽn hoặc quá tải CPU/Disk của Postgres nghiệp vụ chính khi lượng request tăng đột biến.
* **Vòng đời cache sạch hơn:** Redis hỗ trợ cơ chế đặt TTL (`SETEX`) và LRU tự động mà không cần viết lệnh dọn dẹp thủ công.

### 2.2. Phương pháp đo lường Cost/Latency
* **Đo độ trễ (Latency):** Sử dụng công cụ benchmark `repro/run_eval_guardrail.py` chạy tuần tự bộ 6 cases normal để tính toán p50, p95 và Mean Latency.
* **Đo chi phí (Cost):** Trích xuất `input_tokens` và `output_tokens` từ API response của Bedrock, áp dụng bảng giá Nova Lite ($0.06/M input, $0.24/M output) và Nova Micro ($0.035/M input, $0.14/M output) để tính toán USD Cost.

---

## 3. Số liệu đo lường thực tế (Metrics & Results)

Số liệu chi tiết đo đạc thực tế đối chiếu trước và sau khi có cache (Hot Cache) từ tệp `cost_latency_baseline.json`:

| Chỉ số | Trước khi có Cache (Before Baseline) | Lần chạy đầu tiên (Cold Cache Run) | Các lần chạy sau (Hot Cache Run) | Hiệu quả cải thiện (Delta) |
| :--- | :---: | :---: | :---: | :---: |
| **Tổng số cuộc gọi LLM** | 12 (6 Candidate + 6 Judge) | 6 | **2** | **Giảm 83.3%** số lần gọi Bedrock |
| **Tổng lượng token tiêu thụ** | 13,788 tokens | 6,894 tokens | **2,297 tokens** | **Tiết kiệm 11,491 tokens** |
| **Tổng chi phí ước tính** | $0.00069523 | $0.00034760 | **$0.00011580** | **Giảm 83.3%** chi phí API |
| **Độ trễ p50 (p50 Latency)** | 2.8213 giây | 4.0820 giây | **0.0044 giây (4.4 ms)** | **Nhanh gấp ~641 lần** |
| **Độ trễ p95 (p95 Latency)** | 3.4962 giây | 17.6619 giây | **15.0109 giây** | *(Xem phần giải thích ở mục 4)* |
| **Tỷ lệ Pass Rate** | 83.3% | 83.3% | **83.3%** | Giữ nguyên độ chính xác 100% |

---

## 4. Hệ quả và Rủi ro

* **Tăng tốc độ phản hồi:** 5/6 cases hit cache phản hồi siêu tốc chỉ mất khoảng 4ms.
* **p95 Latency cao:** Trường hợp câu trả lời bị Unverified (Case 1) đi theo chính sách **Fidelity Cache Policy** (bị từ chối lưu cache để re-evaluate ở lần sau nhằm đảm bảo chất lượng). Đây là đánh đổi cần thiết để giữ an toàn dữ liệu.
* **Tránh rò rỉ dữ liệu:** Cache key cách ly theo người dùng nhờ thêm `user_id` vào mã băm SHA256.
* **Distributed Lock:** Áp dụng `SET NX EX 10` bảo vệ hệ thống khỏi Cache Stampede khi tải cao.

---

## 5. Tài liệu liên quan

* [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json)
* [cost_latency_baseline.md](../../repro/artifacts/cost_latency_baseline.md)
* [PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md](../analysis/PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md)
