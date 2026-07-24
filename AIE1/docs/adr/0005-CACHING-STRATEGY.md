# ADR 0005: Thiết kế Kiến trúc Caching hai tầng cho Dịch vụ Product Reviews

* **Trạng thái:** Đã phê duyệt
* **Tác giả:** Kiên (AIE1) & Khoa (Leader AIE1)
* **Ngày tạo:** 2026-07-17
* **Tài liệu thiết kế chi tiết:** [PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md](../analysis/PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md)

---

## 1. Bối cảnh

Theo [Chỉ thị số 6](../../mandates/MANDATE-06-ai-trust-safety.md) từ Ban AI & Chất lượng — TechX Corp, hệ thống AI phải đáp ứng đồng thời các ràng buộc:

1. **Không để treo trang sản phẩm** khi model lỗi/chậm — phải có đường lui (Resilience & Fallback).
2. **Tối ưu token, đừng "quăng model to cho xong"** — trong ngân sách hiện tại (Budget).
3. **Guardrail/eval không được kéo p95 vỡ SLO** (Performance).
4. **Chứng minh bằng eval, có log kiểm toán** — không bằng lời (Auditability).

Sau khi hoàn thành triển khai các biện pháp tối ưu hiệu năng cốt lõi (xem [PRODUCT_REVIEWS_BOTTLENECK_ANALYSIS.md](../analysis/PRODUCT_REVIEWS_BOTTLENECK_ANALYSIS.md)), nhóm xác định **hai điểm nghẽn còn lại** cần giải quyết bằng Caching:

| Điểm nghẽn | Loại | Latency trung bình | Nguyên nhân gốc |
| :--- | :--- | :--- | :--- |
| **Gọi LLM Bedrock** mỗi request | I/O-bound | ~1.6 giây | Mỗi câu hỏi đều gọi API LLM bên ngoài, tốn token và chịu latency mạng |
| **Quét Regex Guardrails** trên mọi review | CPU-bound | $O(N \times R \times L)$ | 28+ regex pattern quét tuần tự trên mỗi review khi LLM Cache Miss |

Cả hai điểm nghẽn này đều **vi phạm trực tiếp** ràng buộc Budget (tốn token trùng lặp) và Performance (latency spike khi tải cao) của Directive #6.

---

## 2. Quyết định

Thiết kế và tích hợp **kiến trúc Caching hai tầng bổ trợ lẫn nhau** vào dịch vụ `product-reviews`:

### Tầng 1: LLM Response Caching — Triệt tiêu I/O Latency

**Hạ tầng:** Redis (cache chính) + PostgreSQL (audit log bổ trợ)

| Cơ chế | Mô tả |
| :--- | :--- |
| **Cache-First Lookup** | Tra cứu cache ngay sau Input Guardrails. Khi Cache Hit → trả kết quả < 1ms, không gọi LLM, không tốn token |
| **Dynamic Invalidation** | Cache Key = `SHA256(product_id + review_version + model_id + normalize(question))`. Khi có review mới hoặc đổi model → key tự thay đổi → Cache Miss tự động |
| **Cache Policy chọn lọc** | Chỉ cache khi Fidelity Judge phê duyệt (`approved = true`). Không cache lỗi, fallback, `OUT_OF_SCOPE`, `NO_INFO` |
| **Metadata đầy đủ** | Lưu kèm `provider`, `model`, `token_usage`, `created_at`, `review_version` phục vụ kiểm toán |
| **TTL + LRU Eviction** | TTL 24 giờ, eviction policy `allkeys-lru` khi Redis đầy bộ nhớ |

### Tầng 2: Regex Guardrail Caching — Triệt tiêu CPU Latency

**Hạ tầng:** PostgreSQL (cột `is_safe BOOLEAN` trên bảng `reviews.productreviews`)

| Cơ chế | Mô tả |
| :--- | :--- |
| **Chuyển tải CPU sang Write Path** | Quét Regex Guardrails lúc ghi review mới, lưu kết quả vào cột `is_safe`. Luồng đọc chỉ cần `WHERE is_safe = TRUE` |
| **Không tốn RAM** | Kiểu `BOOLEAN` tốn 1 byte/dòng. 1 triệu reviews chỉ tốn ~1 MB SSD |
| **Scale ngang tự nhiên** | Trạng thái tập trung ở DB, các pod gRPC đồng bộ qua SQL query mà không cần sync layer |
| **Background Migration** | Khi cập nhật Regex rules, chạy batch job quét lại review cũ (500 rows/batch) ngoài request path |

---

## 3. Lý do chọn phương án

### 3.1. Tại sao chọn Redis cho LLM Cache (không phải PostgreSQL)?

> [!IMPORTANT]
> **Bối cảnh:** CDO xác nhận hạ tầng hiện tại thoải mái cả về RAM lẫn dung lượng Database, do đó rào cản chi phí Redis không còn là yếu tố quyết định.

| Tiêu chí | PostgreSQL | Redis | Kết luận |
| :--- | :--- | :--- | :--- |
| **Latency** | ~5-15 ms (Disk I/O + SQL parser) | **< 1 ms** (In-Memory) | **Redis thắng** — đáp ứng SLO p95 |
| **TTL & Eviction** | Cần cronjob + cột `expire_at` thủ công | **Tự động** `SETEX` / `EXPIRE` + LRU | **Redis thắng** — code sạch hơn |
| **Tách biệt tải** | Tăng tải lên DB nghiệp vụ chính | **Cô lập hoàn toàn** khỏi Postgres | **Redis thắng** — đáp ứng Mandate-06 Resilience |
| **Auditability** | `JSONB` hỗ trợ truy vấn SQL phân tích phức tạp | Key-Value đơn giản, khó thống kê | **PostgreSQL thắng** — đáp ứng Mandate-06 Auditability |

**→ Hướng Hybrid:** Redis phục vụ cache real-time < 1ms + PostgreSQL ghi audit log kiểm toán song song. Kết hợp cả Resilience lẫn Auditability.

### 3.2. Tại sao chọn DB Column `is_safe` cho Regex Cache (không phải RAM/Redis)?

Ba phương án đã được đánh giá chi tiết (xem [PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md § 3.2](../analysis/PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md)):

| Tiêu chí | Phương án A (RAM/Redis) | **Phương án B (DB Column)** | Phương án C (Chỉ LLM Cache) |
| :--- | :--- | :--- | :--- |
| **Read Latency** | ~1-2 ms (O(N) lookup) | **0 ms CPU** (`WHERE is_safe = TRUE`) | Latency Spike khi Cache Miss |
| **RAM tiêu thụ** | ~100-200 MB / 1M reviews | **0 MB** | 0 MB |
| **Scale ngang** | Cần Redis cluster đồng bộ | **Tự nhiên qua SQL** | Stateless |
| **Kết luận** | Phức tạp, tốn RAM | **✅ Thắng tuyệt đối** | Nguy cơ Thread Starvation |

Phương án B triệt tiêu hoàn toàn tác vụ quét Regex CPU-bound khỏi request path, giữ server gRPC ở trạng thái I/O-bound thuần túy.

---

## 4. Biện pháp giảm thiểu rủi ro

### 4.1. Redis Connection Failure — 🔴 Nghiêm trọng

**Rủi ro:** Redis sập → toàn bộ luồng RAG lỗi nếu không xử lý ngoại lệ.

**Giải pháp:** Áp dụng **Fail-Open Pattern** nhất quán với cách hệ thống xử lý Bedrock Guardrails (xem [ADR 0003](./0003-AI-TRUST-SAFETY-GUARDRAILS.md)):
* Cache Lookup lỗi → bỏ qua cache, tiếp tục như Cache Miss
* Cache Write lỗi → bỏ qua lưu cache, vẫn trả kết quả cho client
* Dịch vụ luôn hoạt động bình thường ngay cả khi Redis hoàn toàn sập

### 4.2. Cache Stampede (Thundering Herd) — 🟡 Trung bình

**Rủi ro:** Review mới → `review_version` đổi → N request đồng loạt gọi LLM.

**Giải pháp:** **Distributed Lock** bằng Redis `SET NX` (lock 10 giây). Chỉ 1 request gọi LLM, các request sau poll cache chờ kết quả. Timeout → fallback gọi LLM bình thường.

### 4.3. Migration Job khi cập nhật Regex Rules — 🟡 Trung bình

**Rủi ro:** Thay đổi Regex patterns → review cũ cần quét lại cột `is_safe`.

**Giải pháp:** Batch Update ngoài request path (500 rows/batch, sleep 100ms giữa batch). Trade-off an toàn: review cũ chưa quét giữ `is_safe = TRUE` — có thể **lọt review xấu tạm thời** nhưng **không bao giờ chặn nhầm review sạch**.

### 4.4. Cache Invalidation chậm — 🟢 Thấp

**Rủi ro:** `review_version` phụ thuộc vào hàm `get_review_version()` chưa có trong code hiện tại.

**Giải pháp:** Thêm hàm `get_review_version()` vào `database.py`, tính `SHA256(product_id + count + max_timestamp)[:12]` từ các review có `is_safe = TRUE`.

---

## 5. Tác động đến các ràng buộc Directive #6

| Ràng buộc Directive #6 | Trước Caching | Sau Caching | Đánh giá |
| :--- | :--- | :--- | :--- |
| **Resilience — Không treo trang** | Mỗi request gọi LLM ~1.6s, nghẽn khi tải cao | Cache Hit < 1ms, Redis fail-open không chặn dịch vụ | ✅ Cải thiện đáng kể |
| **Budget — Tối ưu token** | 100% request tốn token LLM | Cache Hit → 0 token. Distributed Lock giảm trùng lặp khi burst | ✅ Tiết kiệm đáng kể |
| **Performance — p95 không vỡ SLO** | Regex quét CPU-bound trên request path gây latency spike | `WHERE is_safe = TRUE` triệt tiêu CPU, Redis < 1ms triệt tiêu I/O | ✅ p95 ổn định |
| **Auditability — Log kiểm toán** | Không lưu lịch sử cache | PostgreSQL audit log ghi `provider`, `model`, `token_usage`, trạng thái judge | ✅ Đáp ứng yêu cầu |

---

## 6. Lộ trình triển khai

| Giai đoạn | Nội dung | Files ảnh hưởng |
| :--- | :--- | :--- |
| **GĐ1: Database Migration** | Thêm cột `is_safe BOOLEAN DEFAULT TRUE` + Index composite. Chạy migration job quét review cũ | `database.py`, SQL migration script |
| **GĐ2: Cấu hình Redis** | Thêm `redis>=5.0.0` vào `requirements.txt`. Thêm Redis service vào `docker-compose.yaml`. Cấu hình Helm `values-aio-llm.yaml` | `requirements.txt`, `docker-compose.yaml`, `values-aio-llm.yaml` |
| **GĐ3: Tích hợp mã nguồn** | Cập nhật SQL query `WHERE is_safe = TRUE`. Tích hợp Cache Lookup/Write với fail-open vào `AskProductAIAssistant`. Thêm hàm `get_review_version()` | `database.py`, `product_reviews_server.py` |

---

## 7. Tài liệu liên quan

| Tài liệu | Mô tả |
| :--- | :--- |
| [PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md](../analysis/PRODUCT_REVIEW_SERVER_CACHING_DESIGN.md) | Thiết kế kỹ thuật chi tiết: kiến trúc, trade-off analysis, code minh họa, phân tích rủi ro |
| [LLM_CACHING_DESIGN.md](../analysis/LLM_CACHING_DESIGN.md) | Tài liệu thiết kế LLM Caching ban đầu |
| [PRODUCT_REVIEWS_BOTTLENECK_ANALYSIS.md](../analysis/PRODUCT_REVIEWS_BOTTLENECK_ANALYSIS.md) | Phân tích điểm nghẽn hiệu năng tổng thể dịch vụ product-reviews |
| [ADR 0001 — Chọn Bedrock Nova Lite](./0001-CHOOSE-BEDROCK-NOVA-LITE.md) | Quyết định chọn model LLM chính |
| [ADR 0003 — Guardrails & Eval](./0003-AI-TRUST-SAFETY-GUARDRAILS.md) | Thiết kế hệ thống Guardrails đa tầng |
| [ADR 0004 — Summary Fidelity Evaluation](./0004-SUMMARY-FIDELITY-EVALUATION.md) | Bộ đánh giá độ trung thực — tích hợp làm Cache Policy gate |
| [MANDATE-06 — AI Trust & Safety](../../mandates/MANDATE-06-ai-trust-safety.md) | Chỉ thị gốc từ Ban AI & Chất lượng |
