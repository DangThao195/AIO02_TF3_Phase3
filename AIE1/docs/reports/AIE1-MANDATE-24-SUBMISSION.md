# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #24

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả đo lường quan sát hệ thống AI (LLM Observability & Traceability), khả năng truy vết black-box trace record qua gRPC metadata `x-trace-id`, các HTTP endpoints `/trace/{trace_id}` & `/replay` (cổng HTTP 8086), và kiểm toán an toàn của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #24`**.

---

## 👥 1. Thông Tin Thành Viên Thực Hiện (Task Force AIE1)
*   **Lê Hải Khoa** - Leader AIE1
*   **Ngô Thanh Kiên** - Thành viên AIE1
*   **Nguyễn Tiến Hoàng Thịnh** - Thành viên AIE1

---

## 🔗 2. Các Commit & PR Liên Quan
*   **Commit Tích Hợp LLM Observability & HTTP Trace Server:** [ab5913c](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ab5913c) (Tích hợp Tracing layer, HTTP handler port 8086, và Redis Dual-Key persistence).
*   **Commit Cập Nhật ADR 0008 & Telemetry Trace Schema:** [a033b35](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/a033b35)
*   **Nhánh làm việc chính thức:** `feature/product-review`

---

## 🛠️ 3. Lệnh Tái Tạo & Harness Kiểm Thử Trace HTTP Endpoints (Repro & Harness)

### A. Lệnh khởi chạy HTTP Trace Server & Khôi Phục Replay (Port 8086)
Bật các biến môi trường cấu hình cổng HTTP phụ và token bảo mật (tùy chọn):
```powershell
$env:PRODUCT_REVIEWS_TRACE_HTTP_PORT="8086"
$env:PRODUCT_REVIEWS_TRACE_HTTP_ALLOW_UNAUTHENTICATED="true"
```

### B. Lệnh Test Harness Truy Vấn Trace & Replay
1.  **Gửi Request Giả Lập Replay (`POST /replay`):**
    ```powershell
    curl.exe -X POST `
      -H "Content-Type: application/json" `
      -d "{\"question\":\"Do reviewers say the kit removes dust?\",\"product_id\":\"L9ECAV7KIM\",\"user_id\":\"jira-smoke\",\"session_id\":\"ai-124\"}" `
      http://localhost:8086/replay
    ```
2.  **Truy Vấn Black-box Trace Record Nhận Được (`GET /trace/{trace_id}`):**
    ```powershell
    curl.exe http://localhost:8086/trace/<trace-id>
    ```

---

## 📁 4. Đường Dẫn Mã Nguồn Trace & Báo Cáo Trong Repo

### A. Mã nguồn logic Trace & HTTP Server
*   **Logic Tracing & Audit-Safe Record Generator:** [guardrails/llm_trace.py](../../techx-corp-platform/src/product-reviews/guardrails/llm_trace.py)
*   **Logic gRPC Metadata Trailing & Class `LLMTraceHTTPHandler`:** [product_reviews_server.py](../../techx-corp-platform/src/product-reviews/product_reviews_server.py)
*   **Mã nguồn kiểm thử tự động Tracing:** [test_runtime_guardrails.py](../../techx-corp-platform/src/product-reviews/test_runtime_guardrails.py)

### B. Báo cáo kiến trúc & Tài liệu liên quan
*   **Tài liệu Kiến trúc ADR 0008 (Runtime LLM Trace):** [0008-LLM-OBSERVABILITY.md](../adr/0008-LLM-OBSERVABILITY.md)
*   **Chỉ thị gốc Mandate 24:** [MANDATE-24-llm-observability.md](../../mandates/MANDATE-24-llm-observability.md)

---

---

## 🔐 5. Đặc Điểm Kiến Trúc Observability & Security Compliance

### A. Quản Lý Trace ID & Trích Xuất Biên
- **OpenTelemetry Context Integration:** Tự động trích xuất `current_trace_id()` từ OpenTelemetry Context trong `get_ai_assistant_response()`.
- **gRPC Trailing Metadata `x-trace-id`:** Trả vết `x-trace-id` về gRPC client qua Trailing Metadata của gRPC response, cho phép client truy vết chính xác cuộc gọi.

### B. Dual-Key Redis Trace Storage (`TTL 86400s`)
Mỗi request được lưu song song dưới 2 khóa Redis để phục vụ cả truy vấn nội bộ lẫn HTTP API:
- `product_reviews:llm_trace:{trace_id}` (Key nội bộ theo namespace)
- `trace:{trace_id}` (Key chuẩn mở cho HTTP GET /trace/{trace_id})

### C. Đáp Ứng Đầy Đủ 8 Trường Lõi Của Yêu Cầu 1 (Mandate 24 Trace Schema Compliance)
Mỗi bản ghi Trace Record đều lưu vết chi tiết 8 nhóm thông tin cốt lõi theo đúng yêu cầu Mandate #24:
1. **Model + Version:** Ghi lại chính xác model & provider (`candidate.model`: `"amazon.nova-lite-v1:0"`, `judge.model`: `"amazon.nova-micro-v1:0"`).
2. **Token vào/ra:** Ghi nhận `input_tokens`, `output_tokens`, `total_tokens` cho từng lượt gọi candidate và judge.
3. **Chi phí ước tính (Estimated Cost):** Hàm `estimate_cost_usd()` tính chi phí USD tự động dựa trên bảng đơn giá tĩnh (`_PRICE_PER_1M_TOKENS`).
4. **Độ trễ (Latency):** Ghi nhận `latency_ms` cho từng model call và `total_latency_ms` cho toàn bộ end-to-end request.
5. **Tool calls:** Bề mặt `product-reviews` RAG Q&A ghi nhận trạng thái tool usage `tool_calls: []` (N/A cho bề mặt tóm tắt review).
6. **Phiên / User (Ẩn danh hợp lệ - Anonymized User/Session):** Lưu vết `user_id_hash` (SHA256 băm từ `x-user-id` / `x-replay-user-id`) và `session_id`. Tuyệt đối **không lưu chuỗi thô identity của người dùng**.
7. **Thời điểm (Timestamp):** Thời điểm bắt đầu `created_at` và thời điểm kết thúc `completed_at` dưới định dạng chuẩn ISO 8601 UTC (`_utc_now_iso()`).
8. **Kết quả (Outcome / Status / Fallback):** Phân loại kết quả rõ ràng qua `outcome` (`grounded_answer`, `fallback`, `unverified`, `out_of_scope`, `error`), `response_class` và `fallback_reason`.

### D. Khả Năng Truy Vết End-to-End & Dựng Lại Chuỗi Lời Gọi AI (Requirement 2 Compliance)
Chỉ với **một `trace_id` duy nhất** thu được từ gRPC metadata header (`x-trace-id`) hoặc HTTP `/replay`, khi truy vấn `GET /trace/{trace_id}`, hệ thống cho phép **dựng lại 100% chuỗi cuộc gọi AI (Call Chain Lifecycle)** theo đúng thứ tự thời gian:
1. **Bước 1 (Retrieval & Input Guardrails):** Truy vấn review Postgres + Kiểm tra an toàn `guardrails.input_safe: true`.
2. **Bước 2 (Cache Check):** Tra cứu Redis Cache $\rightarrow$ Ghi nhận `cache.hit: false` và `cache.key_sha256`.
3. **Bước 3 (Candidate LLM Call):** Gọi Bedrock Nova Lite sinh câu tóm tắt $\rightarrow$ Ghi nhận trong chuỗi `candidate.calls[0]` (`latency_ms: 900.12`, `input_tokens: 123`, `output_tokens: 45`).
4. **Bước 4 (Judge LLM Call):** Gọi Bedrock Nova Micro kiểm duyệt độ trung thực $\rightarrow$ Ghi nhận trong chuỗi `judge.calls[0]` (`status: approved`, `latency_ms: 700.34`, `input_tokens: 456`, `output_tokens: 78`).
5. **Bước 5 (Tool Calls Status):** Ghi nhận `tool_calls: []` (Bề mặt Q&A RAG tóm tắt không cần gọi external tool).
6. **Bước 6 (Final Output & Outcome):** Tổng hợp `total_latency_ms: 1750.46`, `outcome: grounded_answer` và băm kết quả `response_sha256`.

### E. View Tổng Hợp Cost / Token / Latency Theo Model, Bề Mặt & Thời Gian (Requirement 3 Compliance)
Hệ thống cung cấp khả năng **báo cáo & tổng hợp dữ liệu (Aggregate Metrics View)** giúp người vận hành theo dõi chi phí, token tiêu thụ và độ trễ mà **không phải đọc hay grep log thô**:
1. **Tổng hợp theo Model AI:** Tự động phân tách và tính tổng chi phí USD/tokens giữa Candidate (`amazon.nova-lite-v1:0`) và Judge (`amazon.nova-micro-v1:0`) trong tệp báo cáo tổng hợp [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json) & [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json).
2. **Tổng hợp theo Bề Mặt AI (Surface / Operation):** Đánh nhãn phân loại thuộc bề mặt `service: product-reviews`, `operation: AskProductAIAssistant` (RAG Summary Q&A).
3. **Tổng hợp theo Thời Gian (Time Window):** Ghi nhận các mốc mảng thời gian ISO 8601 (`created_at`, `completed_at`, `timestamp`) cùng các chỉ số thống kê tổng hợp `p50_latency_seconds`, `p95_latency_seconds`, `total_tokens`, `total_bedrock_calls`, `estimated_cost_usd`.
4. **Cấu Trúc Metric Log Chuẩn (Structured Telemetry):** Đưa ra dòng log định dạng chuẩn `AI_USAGE role=candidate provider=bedrock model=... input_tokens=... output_tokens=... latency_ms=...` hỗ trợ Grafana / Prometheus / CloudWatch tự động trích xuất dashboard tổng hợp theo thời gian thực.

### F. Cơ Chế Chống Rò Rỉ PII / Secret Trong Trace (Requirement 4 Compliance)
Hệ thống tuân thủ nghiêm ngặt nguyên tắc **Audit-Safe Black-Box Tracing (Không thành chỗ rò rỉ dữ liệu nhạy cảm)**:
1. **Mã Hóa SHA-256 Cho Toàn Bộ Prompt & Response:**
   - Khi request chứa chuỗi PII / bí mật (ví dụ: `PII-TOKEN-XYZ`, số thẻ credit, email, hoặc mật khẩu) trong prompt câu hỏi hoặc dữ liệu review, hệ thống **tuyệt đối KHÔNG lưu văn bản thô** của prompt hay response vào trace record.
   - Prompt câu hỏi được băm một chiều qua `question_sha256`: `hashlib.sha256(question.encode('utf-8')).hexdigest()`.
   - Kết quả phản hồi được băm một chiều qua `response_sha256`: `hashlib.sha256(response_text.encode('utf-8')).hexdigest()`.
   - Thông tin người dùng được băm một chiều qua `user_id_hash`.
2. **Minh Chứng Không Rò Chuỗi Thô (Zero Raw Leakage Proof):**
   - Truy vấn tệp trace JSON record thu được bằng từ khóa `PII-TOKEN-XYZ` hoặc chuỗi nhạy cảm bất kỳ $\rightarrow$ **Kết quả 0 match (không tồn tại chuỗi thô)**.
3. **Hướng Dẫn Mentor Kiểm Thử Ngày Chấm (Grading Day Verification):**
   - Bước 1: Gửi 1 request giả lập chứa đánh dấu PII:
     ```powershell
     curl.exe -X POST -H "Content-Type: application/json" -d "{\"question\":\"Review for PII-TOKEN-XYZ-SECRET\",\"product_id\":\"L9ECAV7KIM\"}" http://localhost:8086/replay
     ```
   - Bước 2: Kéo bản ghi trace về qua `GET http://localhost:8086/trace/<trace_id>`.
   - Bước 3: Tìm kiếm chuỗi `PII-TOKEN-XYZ-SECRET` trong nội dung trace nhận được $\rightarrow$ Xác nhận chuỗi thô **hoàn toàn không xuất hiện** (đã được băm thành `question_sha256`).

---

## 📊 6. Cấu Trúc Trace Record Chi Tiết (Trace JSON Schema)

```json
{
  "schema_version": 1,
  "trace_id": "6430920be99810c6d6255d620292a695",
  "trace_id_source": "otel",
  "created_at": "2026-07-28T15:00:00.123456+00:00",
  "completed_at": "2026-07-28T15:00:01.873916+00:00",
  "service": "product-reviews",
  "operation": "AskProductAIAssistant",
  "product_id": "L9ECAV7KIM",
  "user_id_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
  "session_id": "ai-session-124",
  "question_sha256": "8f9b2c1a4e5f...",
  "candidate": {
    "provider": "bedrock",
    "model": "amazon.nova-lite-v1:0",
    "calls": [
      {
        "call_index": 1,
        "provider": "bedrock",
        "model": "amazon.nova-lite-v1:0",
        "input_tokens": 123,
        "output_tokens": 45,
        "total_tokens": 168,
        "latency_ms": 900.12,
        "estimated_cost_usd": 0.000018
      }
    ],
    "total_usage": {
      "call_count": 1,
      "input_tokens": 123,
      "output_tokens": 45,
      "total_tokens": 168,
      "latency_ms": 900.12,
      "estimated_cost_usd": 0.000018
    }
  },
  "judge": {
    "provider": "bedrock",
    "model": "amazon.nova-micro-v1:0",
    "status": "approved",
    "calls": [
      {
        "call_index": 1,
        "provider": "bedrock",
        "model": "amazon.nova-micro-v1:0",
        "input_tokens": 456,
        "output_tokens": 78,
        "total_tokens": 534,
        "latency_ms": 700.34,
        "estimated_cost_usd": 0.000027
      }
    ],
    "total_usage": {
      "call_count": 1,
      "input_tokens": 456,
      "output_tokens": 78,
      "total_tokens": 534,
      "latency_ms": 700.34,
      "estimated_cost_usd": 0.000027
    }
  },
  "tool_calls": [],
  "guardrails": {
    "input_safe": true,
    "output_filtered": true,
    "runtime_fidelity_gate": "approved"
  },
  "cache": {
    "hit": false,
    "key_sha256": "3a1c9e8f...",
    "source_trace_id": null
  },
  "outcome": "grounded_answer",
  "fallback_reason": null,
  "response_class": "grounded_answer",
  "response_sha256": "e2f4a1b0...",
  "total_latency_ms": 1750.46
}
```

---

---

## 🏆 8. Bảng Đối Chiếu Tiêu Chí Hoàn Thành (Definition of Done - DoD Checklist)

| Tiêu chí DoD (Mandate #24 Specification) | Trạng thái | Minh chứng kỹ thuật & Kết quả thực tế |
| :--- | :---: | :--- |
| **DoD 1: ≥ 1 bề mặt AI có Trace đủ 8 trường lõi**<br>*(model+version, token in/out, latency, cost, outcome, trace_id, user/session)* | 🟢 **ĐÃ ĐẠT (100%)** | Bề mặt AI `product-reviews` tự động sinh trace record đủ 8 trường lõi (`trace_id`, `candidate.model`, `input_tokens`/`output_tokens`, `latency_ms`, `estimated_cost_usd`, `outcome`, `user_id_hash`, `session_id`, `created_at`/`completed_at`). xem [§5C](#c-đáp-ứng-đầy-đủ-8-trường-lõi-của-yêu-cầu-1-mandate-24-trace-schema-compliance) & [§6](#-6-cấu-trúc-trace-record-chi-tiết-trace-json-schema). |
| **DoD 2: Dựng lại 1 request end-to-end**<br>*(Một trace_id nối toàn bộ chuỗi lời gọi AI)* | 🟢 **ĐÃ ĐẠT (100%)** | Chỉ với 1 `trace_id` duy nhất (từ gRPC metadata `x-trace-id` hoặc HTTP `/replay`), truy vấn `GET /trace/{trace_id}` dựng lại 100% chuỗi cuộc gọi: Retrieval Postgres $\rightarrow$ Cache Check $\rightarrow$ Candidate Bedrock Nova Lite $\rightarrow$ Judge Bedrock Nova Micro $\rightarrow$ Output Filter $\rightarrow$ Outcome. xem [§5D](#d-khả-năng-truy-vết-end-to-end--dựng-lại-chuỗi-lời-gọi-ai-requirement-2-compliance). |
| **DoD 3: 1 View tổng hợp cost / latency**<br>*(Theo model, theo bề mặt, theo thời gian)* | 🟢 **ĐÃ ĐẠT (100%)** | Tệp artifact tổng hợp [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json) & [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json) cùng hàm `get_usage_trace()` tự động gom nhóm cost/token/latency theo mô hình, bề mặt Q&A và cửa sổ thời gian mà không cần đọc log thô. xem [§5E](#e-view-tổng-hợp-cost--token--latency-theo-model-bề-mặt--thời-gian-requirement-3-compliance). |
| **DoD 4: Không rò thô PII / Secret**<br>*(Tất cả prompt & PII đều được mask/hash)* | 🟢 **ĐÃ ĐẠT (100%)** | Prompt và response đều được băm một chiều `question_sha256`, `response_sha256` và `user_id_hash`. Request chứa chuỗi PII đánh dấu (ví dụ `PII-TOKEN-XYZ`) khi kiểm tra trace record thu được **0 match (không chứa chuỗi thô)**. xem [§5F](#f-cơ-chế-chống-rò-rỉ-pii--secret-trong-trace-requirement-4-compliance). |
| **DoD 5: ADR Ký Tên Duyệt** | 🟢 **ĐÃ ĐẠT (100%)** | Đã hoàn thiện và ký duyệt tài liệu kiến trúc [ADR 0008: Runtime LLM Trace & Auditability](../adr/0008-LLM-OBSERVABILITY.md). |


