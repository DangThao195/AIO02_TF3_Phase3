# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #23

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả đo lường bộ nhớ đệm (GenAI Caching & Memory), cách ly ranh giới người dùng (User Boundary Isolation), cơ chế Fail-Open và đo lường chi phí/độ trễ của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #23`**.

---

## 👥 1. Thông Tin Thành Viên Thực Hiện (Task Force AIE1)
*   **Lê Hải Khoa** - Leader AIE1
*   **Ngô Thanh Kiên** - Thành viên AIE1
*   **Nguyễn Tiến Hoàng Thịnh** - Thành viên AIE1

---

## 🔗 2. Các Commit & PR Liên Quan
*   **Commit Tích Hợp Caching & User Boundary Isolation:** [ab5913c](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ab5913c) (Tích hợp Redis cache, cờ metadata gRPC, và SHA256 User Isolation Key).
*   **Commit Baseline Đo Lường Caching:** [9012b61](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/9012b61) (Lưu trữ `cost_latency_baseline` JSON và Markdown).
*   **Nhánh làm việc chính thức:** `feature/product-review`

---

## 🛠️ 3. Lệnh Tái Tạo & Harness Đo Lường Caching (Repro & Harness)

### A. Lệnh chạy toàn bộ bộ thử nghiệm Caching & Benchmark (Một Lệnh Duy Nhất)
Thực hiện lệnh tại thư mục gốc để chạy toàn bộ suite đo lường caching và benchmark:
```bash
make eval-mandate23
```
hoặc chạy trực tiếp script benchmark:
```bash
python repro/benchmark.py
```

### B. Harness Kiểm Tra Trailing Metadata & User Boundary Isolation
Để kiểm chứng các tính năng cờ cache metadata và cách ly theo người dùng:

1.  **Harness kiểm tra gRPC Trailing Metadata (`cache: hit` / `cache: miss`):**
    ```bash
    python repro/test_grpc_cache_metadata.py
    ```
2.  **Harness kiểm tra cách ly Cache theo `user_id` (`x-user-id` header):**
    ```bash
    python repro/test_user_isolation.py
    ```

---

## 📁 4. Đường Dẫn Mã Nguồn Caching & Bộ Dữ Liệu Benchmark Trong Repo

### A. Mã nguồn logic Caching & Isolation
*   **Logic Caching & User Isolation Key:** [guardrails/cache.py](../../techx-corp-platform/src/product-reviews/guardrails/cache.py)
*   **Logic gRPC Server Metadata Trailing & User Boundary:** [product_reviews_server.py](../../techx-corp-platform/src/product-reviews/product_reviews_server.py)
*   **Logic Invalidation theo Review Version:** [database.py](../../techx-corp-platform/src/product-reviews/database.py)

### B. Tệp Artifacts & Benchmark JSON Đã Commit Trong Repo
*   **Artifact JSON Đo Lường Caching (Before vs Hot Cache):** [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json)
*   **Báo cáo hiệu năng chi tiết:** [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json)
*   **Báo cáo baseline trước khi cache:** [cost_latency_BEFORE_cache.json](../../repro/artifacts/cost_latency_BEFORE_cache.json)

---

## 🔐 5. Đặc Điểm Kiến Trúc Caching 2 Tầng (GenAI Caching & User Isolation)

### A. Tầng 1: LLM Response Cache (Redis In-Memory)
- **Tốc độ phản hồi:** Phản hồi siêu tốc `< 1ms` khi Cache Hit (không gọi LLM, 0 token tiêu thụ).
- **Công thức sinh Cache Key cách ly người dùng:**
  ```python
  Cache Key = SHA256(product_id + review_version + model_id + normalize(question) + user_id)
  ```
- **Ranh giới Người dùng (User Boundary Isolation):** Trích xuất `user_id` từ gRPC invocation metadata header (`x-user-id` hoặc `user-id`). Người dùng khác nhau hỏi cùng một câu hỏi sẽ nhận khóa cache riêng biệt, tuyệt đối không bị rò rỉ dữ liệu chéo. Nếu không truyền `user_id`, sử dụng giá trị mặc định `"anonymous"`.
- **gRPC Trailing Headers Metadata:** Tự động set trailing metadata `cache = hit` khi đọc từ Redis cache và `cache = miss` khi Cache Miss / Fallback / LLM call.
- **Fail-Open Pattern:** Nếu Redis gặp sự cố kết nối, hệ thống tự động bypass cache sang cuộc gọi LLM bình thường mà không gây crash gRPC server.
- **Thundering Herd Protection:** Áp dụng khóa phân tán `SET NX EX 10` đảm bảo chỉ 1 request đồng thời gọi LLM khi Cache Miss, các request trùng lặp chờ kết quả từ cache.

### B. Tầng 2: DB Column Regex Cache (`is_safe BOOLEAN`)
- **Tạo cột DB `is_safe`:** Đánh dấu trực tiếp trong PostgreSQL (`reviews.productreviews`).
- **Triệt tiêu CPU Latency:** Luồng đọc chỉ cần `WHERE is_safe = TRUE`, loại bỏ 100% thời gian quét 28+ Regex patterns trên luồng đọc gRPC.

---

## 📊 6. Kết Quả Đo Lường Hiệu Năng & Chi Phí (Before vs Cold vs Hot Cache)

*Đo lường tự động công khai qua tệp bằng chứng [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json) & [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json):*

| Chỉ số | Trước khi có Cache (Before Baseline) | Lần chạy đầu tiên (Cold Cache Run) | Các lần chạy sau (Hot Cache Run) | Hiệu quả cải thiện (Delta) |
| :--- | :---: | :---: | :---: | :---: |
| **Tổng số cuộc gọi LLM** | 12 (6 Candidate + 6 Judge) | 6 | **2** | **Giảm 83.3%** số lần gọi Bedrock |
| **Tổng lượng token tiêu thụ** | 13,788 tokens | 6,894 tokens | **2,297 tokens** | **Tiết kiệm 11,491 tokens** |
| **Tổng chi phí ước tính** | $0.00069523 | $0.00034760 | **$0.00011580** | **Giảm 83.3%** chi phí API |
| **Độ trễ trung vị p50 (Latency)** | 2.8213 giây | 4.0820 giây | **0.0044 giây (4.4 ms)** | **Nhanh gấp ~641 lần** |
| **Tỷ lệ Pass Rate** | 83.3% | 83.3% | **83.3%** | Giữ nguyên độ chính xác 100% |

> [!NOTE]
> **Về Độ Trễ p95:** p95 giữ ở mức 15.01 giây do chính sách **Fidelity-based Caching (Chỉ cache kết quả PASS)**. Khi Judge dán nhãn case không đạt chất lượng (`Unverified`), hệ thống chủ động bỏ qua việc ghi cache để bảo vệ storefront khỏi nội dung sai lệch, bắt buộc request sau phải verify lại từ đầu.

---

## 📁 7. Các Tài Liệu Minh Chứng & ADR Đi Kèm (Artifacts)
*   **Artifact JSON Đo Lường Caching (Before vs Hot Cache):** [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json)
*   **Báo cáo hiệu năng chi tiết:** [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json)
*   **Báo cáo baseline trước khi cache:** [cost_latency_BEFORE_cache.json](../../repro/artifacts/cost_latency_BEFORE_cache.json)

### Bộ tài liệu ADR Ký Tên Duyệt:
1.  [0005-CACHING-STRATEGY.md](../adr/0005-CACHING-STRATEGY.md) *(Thiết kế Caching 2 tầng & User Isolation)*
2.  [0006-COST-LATENCY-MEASUREMENT-AND-CACHING.md](../adr/0006-COST-LATENCY-MEASUREMENT-AND-CACHING.md) *(Nghiệm thu đo lường Cost/Latency)*
