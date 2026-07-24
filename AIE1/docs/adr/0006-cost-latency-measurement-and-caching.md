# ADR 0006: Đo lường Chi Phí/Độ Trễ và Tích Hợp Redis Caching Cho Dịch Vụ Product Reviews

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Thịnh (AIE1) và Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-24

---

## 1. Bối cảnh (Context)

Theo **Chỉ thị số 14 (AI Eval Standard)** và **Chỉ thị số 23 (GenAI Caching & Memory)**, nhóm AIE1 cần đáp ứng đồng thời các tiêu chí:
1. Xác lập bộ chỉ số đo lường hiệu năng cốt lõi (Cost/Latency) cho các cuộc gọi mô hình ngôn ngữ lớn (AWS Bedrock / OpenAI).
2. Xây dựng cơ chế Caching hai tầng để giảm thiểu tối đa độ trễ và chi phí token, đồng thời cách ly cache theo ranh giới người dùng (`user_id`).
3. Chứng minh hiệu năng trước và sau khi có cache thông qua các số liệu đo đạc thực tế (Before vs After) với các chỉ số thống kê cụ thể (p50, p95, token count, USD cost).

Trước khi có cache, mỗi yêu cầu hỏi đáp của khách hàng đều phải gọi trực tiếp sang Bedrock API (Candidate model: Nova Lite + Judge model: Nova Micro) gây ra các điểm nghẽn:
- **Độ trễ cao:** Trung bình mỗi request mất khoảng 2.82 giây (I/O network bottleneck).
- **Chi phí lớn:** Gây lãng phí token trùng lặp cho các câu hỏi giống nhau và dễ bị Rate Limit (HTTP 429) khi có lượng truy cập đột biến.

---

## 2. Quyết định (Decision)

Nhóm thống nhất triển khai các giải pháp kiến trúc sau:

### 2.1. Lựa chọn Redis/Valkey làm hạ tầng Caching chính
Chúng tôi chọn Redis thay vì lưu trữ cache trực tiếp trong PostgreSQL nghiệp vụ vì:
* **Tốc độ phản hồi (Latency):** Redis lưu trữ hoàn toàn trên RAM (In-Memory), cho phép tốc độ đọc/ghi đạt mức `< 1ms`, trong khi Postgres tốn từ `5-15ms` do Disk I/O và SQL query parser.
* **Tách biệt tải trọng:** Việc cô lập cache sang cụm Redis (AWS ElastiCache) giúp tránh việc làm quá tải (Disk/CPU starvation) cho cơ sở dữ liệu Postgres chính chứa các thông tin giao dịch/reviews.
* **Hỗ trợ vòng đời cache:** Redis tích hợp sẵn lệnh `SETEX` (thiết lập TTL) và chính sách thu hồi khóa tự động `allkeys-lru` khi đầy bộ nhớ, giảm tải mã nguồn tự quản lý trong ứng dụng.

### 2.2. Phương pháp đo lường và tính toán (Metrics Strategy)
* **Độ trễ (Latency):** Sử dụng script benchmark `repro/run_eval_guardrail.py` để quét tuần tự các case test, ghi nhận thời gian phản hồi ở mức gRPC Client, tính toán các chỉ số p50, p95 và Mean Latency.
* **Chi phí (Cost):** Trích xuất thông tin token (`input_tokens`, `output_tokens`) từ API Response của Bedrock và áp dụng bảng giá niêm yết:
  - **amazon.nova-lite-v1:0 (Candidate):** Input: $0.06 / triệu tokens | Output: $0.24 / triệu tokens.
  - **amazon.nova-micro-v1:0 (Judge):** Input: $0.035 / triệu tokens | Output: $0.14 / triệu tokens.
  - Công thức tính:
    $$\text{Cost} = \sum (\text{Input Token} \times \text{Input Price}) + (\text{Output Token} \times \text{Output Price})$$

---

## 3. Số liệu đo lường thực tế (Metrics & Results)

Số liệu thực tế thu thập từ 6 normal cases mẫu chạy tuần tự (trước và sau khi kích hoạt Redis Cache) được lưu trữ tại [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json):

| Chỉ số | Trước khi có Cache (Before Caching Baseline) | Lần chạy đầu tiên (Cold Cache Run) | Các lần chạy sau (Hot Cache Run) | Hiệu quả cải thiện (Delta) |
| :--- | :---: | :---: | :---: | :---: |
| **Tổng số cuộc gọi LLM** | 12 (6 Candidate + 6 Judge) | 6 | **2** | **Giảm 83.3%** số lần gọi Bedrock |
| **Tổng lượng token tiêu thụ** | 13,788 tokens | 6,894 tokens | **2,297 tokens** | **Tiết kiệm 11,491 tokens** |
| **Tổng chi phí ước tính** | $0.00069523 | $0.00034760 | **$0.00011580** | **Giảm 83.3%** chi phí API |
| **Độ trễ p50 (p50 Latency)** | 2.8213 giây | 4.0820 giây | **0.0044 giây (4.4 ms)** | **Nhanh gấp ~641 lần** |
| **Độ trễ p95 (p95 Latency)** | 3.4962 giây | 17.6619 giây | **15.0109 giây** | *(Xem phần giải thích ở mục 4.2)* |
| **Tỷ lệ Pass Rate** | 83.3% | 83.3% | **83.3%** | Giữ nguyên độ chính xác 100% |

---

## 4. Hệ quả và Rủi ro (Consequences)

### 4.1. Tác động tích cực
* **Trải nghiệm khách hàng tối ưu:** Tốc độ phản hồi đạt mức gần như tức thời (~4ms) đối với các request hit cache.
* **An toàn chi phí:** Giảm thiểu 83.3% chi phí API Bedrock và hạn chế tối đa nguy cơ nghẽn Rate Limit của AWS Account.
* **Cách ly an toàn dữ liệu:** Cache key chứa tham số băm SHA256 gồm cả `user_id` (`SHA256(product_id + review_version + model_id + question + user_id)`) giúp ngăn chặn hoàn toàn việc rò rỉ chéo thông tin cache giữa các khách hàng khác nhau.

### 4.2. Lý giải hiện tượng p95 Latency
Độ trễ p95 trong các lần chạy sau (Hot Cache) vẫn giữ ở mức 15 giây. Đây không phải lỗi mà là hệ quả từ chính sách **Fidelity Cache Policy** của hệ thống:
- Các câu trả lời bị dán nhãn `Unverified` (không trung thực) bởi Judge sẽ **bị từ chối ghi vào Cache**.
- Ở các request sau, hệ thống bắt buộc phải bỏ qua cache và gọi lại LLM thực tế để tái đánh giá, đảm bảo tính đúng đắn cho người dùng. Do đó, request bị Unverified này kéo p95 lên, nhưng bảo vệ an toàn cho dữ liệu hiển thị.

### 4.3. Phòng chống Cache Stampede
Hệ thống tích hợp Distributed Lock (`SET NX EX 10`). Khi có đợt burst request đồng thời vào một sản phẩm chưa được cache, chỉ luồng đầu tiên được gọi LLM, các luồng còn lại tự động xếp hàng polling chờ ghi nhận từ Redis, loại bỏ hoàn toàn rủi ro sập hệ thống (thundering herd).

---

## 5. Danh sách phê duyệt từ các thành viên

| Thành viên | Vai trò | Chữ ký ký duyệt | Trạng thái |
| :--- | :--- | :--- | :--- |
| **Trần Quốc Thịnh** | Thành viên AIE1 | *ThinhTQ* | Đã duyệt |
| **Đặng Minh Khoa** | Leader AIE1 | *KhoaDM* | Đã duyệt |
