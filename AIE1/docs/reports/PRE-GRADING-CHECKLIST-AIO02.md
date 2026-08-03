# Checklist tự kiểm trước ngày chấm — AIO02 (TF3)

> Repo `DangThao195/AIO02_TF3_Phase3`. Rà lại và tự xác nhận trên bản mới nhất trước buổi chấm cuối chương trình. Không cần nộp thêm — mentor xem trực tiếp trên repo đang chạy.

## Chung cho mọi mandate
- [x] **(AIE1)** Mọi con số báo cáo **đo trên dữ liệu thật** và **khớp artifact committed** (`cost_latency_comparison.json`, `security_false_block_runtime_bedrock_v2_20260727.json`, `rag_accuracy_runtime_bedrock_usage_fix2_20260727.json`), chạy lại ra đúng số.
- [ ] Repro chạy được thật; **merge các nhánh về trunk** (nhánh AIE1 `feature/product-review` sẵn sàng merge).
- [x] **(AIE1)** Doc/status mô tả đúng trạng thái thật (phân biệt rõ live gRPC vs fault injection simulation mode).

## Vấn đề cần xử lý (theo mandate)

**#7b / #15 Detection — quan trọng nhất**
- [ ] Precision/Recall hiện **đo trên tập tự soạn 1 service (checkout), các dòng "bình thường" toàn giá trị 0**, và cửa sổ `warmup` loại hết các dòng bình thường → chỉ số bị đẩy về 1.0, **không phản ánh chất lượng thật**. → Đo lại trên **bộ nhãn nhiều service, có dữ liệu bình thường thật**, bỏ warmup-trim.
- [ ] Cổng `validation_passed` đang báo **pass** trong khi precision thực của model rất thấp, do guardrail **bỏ qua tiêu chí precision cho một số loại scenario** → validate không exempt, trên nhãn thật.
- [ ] Model IsolationForest hiện gần như **flag mọi thứ** (precision thấp); phần phân biệt "bận vs hỏng" thực tế do **cổng SLO/threshold** làm → chứng minh ML **thêm giá trị thật** hoặc nêu rõ vai trò từng lớp.
- [ ] Ca "masking" hiện là lỗi **hiện rõ** (kích cả 3 điều kiện cổng) → dựng ca masking thật: lỗi **ẩn dưới baseline đang trôi**.
- [ ] "100% không báo giả" đang lấy từ fixture có latency=0/error=0 tuyệt đối → đo trên **tải cao thật**.
- [ ] Headline P/R trong submission chưa ghi rõ đo trên tập tự soạn → ghi đúng bối cảnh + số thật.

**#22 Closed-loop**
- [x] **(AIE1)** Đã hoàn thiện **Actuator**, **PostgreSQL Tier 2 Static Summary Fallback**, và **HTTP Error Injection Mode (8086)**; đã chạy simulation dập lỗi closed-loop ghi log tại `logs/audit_log.jsonl`.
- [ ] MTTR "110m → 4.5m" hiện là **số suy từ budget bước**, không đo → đo thật bằng timestamp detect→recover.
- [ ] Header evidence ghi "EKS Cluster Active" + "PASSED" trong khi chạy mô phỏng → sửa cho khớp trạng thái thật.

**#6 Trust & Safety**
- [x] **(AIE1)** Đã chứng minh deploy chạy Bedrock Nova Lite & Nova Micro thật (`security_false_block_runtime_bedrock_v2_20260727.json`, 186 cases).

**#7a Detection**
- [ ] Doc baseline còn số cũ → cập nhật theo số thật từ metric.

**#14 AI Eval**
- [x] **(AIE1)** Báo **False Block Rate riêng cho bề mặt AIE1 (Product Reviews)**: đạt **`0.0%`** (0/68 ca lành tính bị chặn trên gRPC service sống).
- [x] **(AIE1)** 100% các ca thử nghiệm trong artifact AIE1 chạy trên service sống thực tế (`errors: 0`).
- [x] **(AIE1)** Đã làm rõ sự khác biệt giữa con số legacy 28.57% (bề mặt cũ/AIE2) và 0.0% (bề mặt AIE1 live gRPC).

**#23 / #24 / #25 GenAI (2 bề mặt AIE1 + AIE2)**
- [x] **#23 (AIE1)**: Mentor xác nhận dịch vụ Product Reviews là **Single-Turn Q&A / Review Summary per product**, không cần Memory đa lượt; đã hoàn thành Caching Redis 2 tầng, `x-user-id` boundary isolation, invalidation theo `review_version`, và harness benchmark tự động `repro/eval_support/benchmark.py`.
- [x] **#24 (AIE1)**: Đã bổ sung đủ 4 trường trace (`user_id_hash`, `session_id`, `tool_calls: []`, `model_version`); chuyển sang ghi trace bất đồng bộ (`write_llm_trace_async`) qua ThreadPool; tính cost theo bảng giá dynamic multi-model pricing (`_PRICE_PER_1M_TOKENS`).
- [x] **#25 (AIE1)**: Circuit Breaker (`CircuitBreaker`) đã wire trực tiếp vào call path gRPC `get_ai_assistant_response`; 36/36 unit/resilience tests passing (`test_circuit_breaker.py`, `test_error_injection.py`, `test_tool_validator.py`, `test_fallback_tier2.py`).

## Nice-to-have cuối chương trình (#26 · #27 · #28)
- [x] **(AIE1)** Đã mở cổng HTTP `POST /replay` (port 8086) nhận kịch bản từ bên ngoài và ghi audit log vết sự cố theo thời gian.

