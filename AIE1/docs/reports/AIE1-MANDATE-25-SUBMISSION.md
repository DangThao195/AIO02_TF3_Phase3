# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #25

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả kiểm thử tự động (Unit & Integration Tests) và phân tích mã nguồn cho các cơ chế Phục Hồi Khai Thác Lỗi (AI Resilience & Closed-Loop Fallback), Ngắt Mạch Circuit Breaker (Subtask 3.1), Kiểm Tra Schema Biên Tool Arguments (Subtask 3.2), và Cổng Ép Lỗi Giả Lập Failure Injection Mode (Subtask 3.3) của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #25`**.

---

## 👥 1. Thông Tin Thành Viên Thực Hiện (Task Force AIE1)
*   **Lê Hải Khoa** - Leader AIE1
*   **Ngô Thanh Kiên** - Thành viên AIE1
*   **Nguyễn Tiến Hoàng Thịnh** - Thành viên AIE1

---

## 🔗 2. Các Commit & PR Liên Quan
*   **Commit Triển Khai Circuit Breaker, Tool Validator & Error Injection:** [ab5913c](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ab5913c)
*   **Commit Cập Nhật ADR 0007 & Báo Cáo Minh Chứng Subtasks:** [a033b35](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/a033b35)
*   **Nhánh làm việc chính thức:** `feature/product-review`

---

## 🛠️ 3. Lệnh Tái Tạo & Chạy Unit Test Suites (Repro & Harness)

### A. Lệnh chạy toàn bộ Unit Tests của Mandate 25 (Một Lệnh Duy Nhất)
Thực hiện lệnh tại thư mục `techx-corp-platform/src/product-reviews` để kiểm tra 100% test cases:
```bash
pytest test_circuit_breaker.py test_tool_validator.py test_error_injection.py -v
```

### B. Lệnh chạy từng bộ test suite riêng lẻ
1.  **Kiểm thử Ngắt Mạch Circuit Breaker (4/4 Passed):**
    ```bash
    pytest test_circuit_breaker.py -v
    ```
2.  **Kiểm thử Thẩm Định Schema Biên Tool Arguments (10/10 Passed):**
    ```bash
    pytest test_tool_validator.py -v
    ```
3.  **Kiểm thử Cổng Ép Lỗi Giả Lập Error Injection (22/22 Passed):**
    ```bash
    pytest test_error_injection.py -v
    ```

---

## 📁 4. Đường Dẫn Mã Nguồn Core & Tài Liệu Minh Chứng Trong Repo

### A. Mã nguồn các Module Guardrails & Server Integration
*   **Subtask 3.1 - Circuit Breaker State Machine:** [guardrails/circuit_breaker.py](../../techx-corp-platform/src/product-reviews/guardrails/circuit_breaker.py)
*   **Subtask 3.2 - Tool Arguments Boundary Validation:** [guardrails/tool_validator.py](../../techx-corp-platform/src/product-reviews/guardrails/tool_validator.py)
*   **Subtask 3.3 - Error Injection State Manager:** [guardrails/error_injection.py](../../techx-corp-platform/src/product-reviews/guardrails/error_injection.py)
*   **Tích hợp gRPC Boundary & Fallback Handler:** [product_reviews_server.py](../../techx-corp-platform/src/product-reviews/product_reviews_server.py)
*   **AIOps Replay Simulation Script & Audit Log:** [aiops_replay_sim.py](../../techx-corp-platform/src/product-reviews/aiops_replay_sim.py) và [audit_log.jsonl](../../techx-corp-platform/src/product-reviews/logs/audit_log.jsonl)

### B. Bộ báo cáo minh chứng chi tiết đã commit
*   **Báo cáo Subtask 3.1 (Circuit Breaker):** [subtask3_1_circuit_breaker.md](../subtask3_1_circuit_breaker.md)
*   **Báo cáo Subtask 3.2 (Tool Validator):** [subtask3_2_tool_validator.md](../subtask3_2_tool_validator.md)
*   **Báo cáo Subtask 3.3 (Failure Injection Mode):** [subtask3_3.md](../subtask3_3.md)
*   **Tài liệu Kiến trúc ADR 0007:** [0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md](../adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md)

---

## 🎯 5. Chi Tiết 3 Trụ Cột Resilience Của Mandate #25

### 5.1. Subtask 3.1: Circuit Breaker State Machine
- **Chức năng:** Tự động chuyển đổi giữa 3 trạng thái `CLOSED`, `OPEN`, `HALF-OPEN`. Ngưỡng kích hoạt ngắt mạch: **5 lỗi liên tiếp**, thời gian nguội (Cooldown): **30 giây**.
- **Động cơ lưu trữ kép (Dual-Storage Engine):** Ưu tiên lưu trạng thái trên Redis key (`product_reviews:cb:state`, `failures`, `opened_at`), tự động fallback về bộ nhớ trong Thread-Safe (`threading.Lock`) nếu mất kết nối Redis.
- **Kết quả kiểm thử:** Passed **4/4** unit test cases (`test_circuit_breaker.py`).

### 5.2. Subtask 3.2: Tool Arguments Schema Validation & Security Filter
- **An toàn biên JSON Decode:** Bọc lệnh parse JSON trong khối `try...except (json.JSONDecodeError, TypeError, ValueError)`, loại bỏ nguy cơ crash gRPC server khi LLM trả JSON rác.
- **Thẩm định Schema `product_id`:** Ép kiểu dữ liệu chuỗi ký tự, độ dài ≤ 64 ký tự, khớp regex `^[A-Za-z0-9_-]+$`, chặn 100% hành vi SQL Injection, XSS, Path Traversal.
- **Telemetry:** Xuất Prometheus metric `app_ai_fallback_total{source="malformed_tool_args"}` và OpenTelemetry trace attribute `app.fallback.source="malformed_tool_args"`.
- **Kết quả kiểm thử:** Passed **10/10** unit test cases (`test_tool_validator.py`).

### 5.3. Subtask 3.3: HTTP Error Injection Mode & Closed-Loop Simulation
- **Cổng HTTP phụ (Port 8086):** Endpoints `POST /inject/error` và `GET /inject/error` cho phép AIOps ép lỗi giả lập (`"429"`, `"timeout"`, `"500"`, `"circuit_breaker"`).
- **gRPC Server Hook:** Tự động phát hiện cờ injection, ngắt cuộc gọi LLM Bedrock, xuất telemetry metric `app_ai_fallback_total{source="error_injection"}` và phản hồi đường tĩnh Fallback. Khi `error_type == "circuit_breaker"`, tự động gọi `circuit_breaker.record_failure()` để kích hoạt ngắt mạch.
- **Mô phỏng AIOps Closed-Loop (Simulation Log Verification):** Script `aiops_replay_sim.py` kiểm chứng chu trình 5 bước AIOps: Ép lỗi 429 → Tỷ lệ lỗi tăng lên 72%-82% → Tự động sửa chữa → Xóa lỗi → Tỷ lệ lỗi giảm về 0% → Phục hồi về 2%-4%. Toàn bộ kết quả ghi nhận công khai tại [audit_log.jsonl](../../techx-corp-platform/src/product-reviews/logs/audit_log.jsonl).
- **Kết quả kiểm thử:** Passed **22/22** unit test cases (`test_error_injection.py`).

---

## 📊 6. Bảng Tổng Hợp Kết Quả Kiểm Thử (Verification Summary)

| Tên Bộ Kiểm Thử (Test Suite) | File Test Source | Số Ca Passed | Tổng Số Ca | Tỷ Lệ Đạt (Pass Rate) | Trạng Thái Quality Gate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Subtask 3.1: Circuit Breaker** | `test_circuit_breaker.py` | 4 | 4 | **`100.0%`** | ✅ PASSED |
| **Subtask 3.2: Tool Arguments Validator** | `test_tool_validator.py` | 10 | 10 | **`100.0%`** | ✅ PASSED |
| **Subtask 3.3: Error Injection Mode** | `test_error_injection.py` | 22 | 22 | **`100.0%`** | ✅ PASSED |
| **TỔNG THỂ (Overall Mandate 25)** | **Cả 3 file test suite** | **36** | **36** | **`100.0%`** | **`PASSED`** |

---

## 📁 7. Các Tài Liệu Minh Chứng & ADR Đi Kèm (Artifacts)
*   **Tài liệu Kiến trúc ADR 0007:** [0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md](../adr/0007-FALLBACK-OVERRIDE-AND-TELEMETRY.md)
*   **Log đối soát AIOps Simulation Audit Log:** [audit_log.jsonl](../../techx-corp-platform/src/product-reviews/logs/audit_log.jsonl)
*   **Mandate 25 Specification:** [MANDATE-25-ai-resilience-fallback.md](../../mandates/MANDATE-25-ai-resilience-fallback.md)
