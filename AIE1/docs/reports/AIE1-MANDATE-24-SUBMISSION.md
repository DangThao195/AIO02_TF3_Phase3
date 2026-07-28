# 🏆 BẰNG CHỨNG NGHIỆM THU - AI MANDATE #24
## 📡 AI LLM Observability, End-to-End Traceability & Audit-Safe Compliance

Tài liệu này tổng hợp toàn bộ bằng chứng nghiệm thu, kết quả đo lường quan sát hệ thống AI (**LLM Observability & Traceability**), khả năng truy vết black-box trace record qua gRPC metadata `x-trace-id`, các HTTP endpoints `/trace/{trace_id}` & `/replay` (cổng HTTP 8086), và kiểm toán an toàn dữ liệu của tầng AI (AIE1 - Product Reviews), sẵn sàng để nộp cho Jira Ticket **`AI MANDATE #24`**.

---

## 👥 1. Thông Tin Thành Viên & Metadata Dự Án

*   **Task Force AIE1:** 
    *   **Lê Hải Khoa** (Leader AIE1)
    *   **Ngô Thanh Kiên** (Thành viên AIE1)
    *   **Nguyễn Tiến Hoàng Thịnh** (Thành viên AIE1)
*   **Nhánh làm việc chính thức:** `feature/product-review`
*   **Commit Tích Hợp LLM Observability & HTTP Trace Server:** [`ee5a2e5`](https://github.com/DangThao195/AIO02_TF3_Phase3/commit/ee5a2e5)

---

## 🏆 2. Bảng Đối Chiếu Tiêu Chí Hoàn Thành (Definition of Done - DoD Checklist)

| Tiêu chí DoD (Mandate #24 Specification) | Trạng thái | Minh chứng kỹ thuật & Kết quả thực tế |
| :--- | :---: | :--- |
| **DoD 1: ≥ 1 bề mặt AI có Trace đủ 8 trường lõi**<br>*(model+version, token in/out, latency, cost, outcome, trace_id, user/session)* | 🟢 **ĐÃ ĐẠT (100%)** | Bề mặt AI `product-reviews` tự động sinh trace record chứa đủ 8 trường lõi (`trace_id`, `candidate.model`, `input_tokens`/`output_tokens`, `latency_ms`, `estimated_cost_usd`, `outcome`, `user_id_hash`, `session_id`, `created_at`/`completed_at`). Xem [§3.3](#33-dáp-ứng-dầy-dủ-8-trường-lõi-của-yêu-cầu-1) & [§4](#-4-cấu-trúc-trace-record-chi-tiết-trace-json-schema). |
| **DoD 2: Dựng lại 1 request end-to-end**<br>*(Một trace_id nối toàn bộ chuỗi lời gọi AI)* | 🟢 **ĐÃ ĐẠT (100%)** | Chỉ với 1 `trace_id` duy nhất (từ gRPC metadata `x-trace-id` hoặc HTTP `/replay`), truy vấn `GET /trace/{trace_id}` dựng lại 100% chuỗi cuộc gọi: Retrieval Postgres $\rightarrow$ Cache Check $\rightarrow$ Candidate Bedrock Nova Lite $\rightarrow$ Judge Bedrock Nova Micro $\rightarrow$ Output Filter $\rightarrow$ Outcome. Xem [§3.4](#34-khả-năng-truy-vết-end-to-end--dựng-lại-chuỗi-lời-gọi-ai-yêu-cầu-2). |
| **DoD 3: 1 View tổng hợp cost / latency**<br>*(Theo model, theo bề mặt, theo thời gian)* | 🟢 **ĐÃ ĐẠT (100%)** | Tệp artifact tổng hợp [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json) & [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json) cùng hàm `get_usage_trace()` tự động gom nhóm cost/token/latency theo mô hình, bề mặt Q&A và cửa sổ thời gian mà không cần đọc log thô. Xem [§3.5](#35-view-tổng-hợp-cost--token--latency-theo-model-bề-mặt--thời-gian-yêu-cầu-3). |
| **DoD 4: Không rò thô PII / Secret**<br>*(Tất cả prompt & PII đều được mask/hash)* | 🟢 **ĐÃ ĐẠT (100%)** | Prompt và response đều được băm một chiều `question_sha256`, `response_sha256` và `user_id_hash`. Request chứa chuỗi PII đánh dấu (ví dụ `PII-TOKEN-XYZ`) khi kiểm tra trace record thu được **0 match (không chứa chuỗi thô)**. Xem [§3.6](#36-cơ-chế-chống-rò-rỉ-pii--secret-trong-trace-yêu-cầu-4). |
| **DoD 5: ADR Ký Tên Duyệt** | 🟢 **ĐÃ ĐẠT (100%)** | Đã hoàn thiện và ký duyệt tài liệu kiến trúc [ADR 0008: Runtime LLM Trace & Auditability](../adr/0008-LLM-OBSERVABILITY.md). |

---

## 🔐 3. Phân Tích Kỹ Thuật Chi Tiết Theo 4 Yêu Cầu Chỉ Thị

### 3.1 Quản Lý Trace ID & Trích Xuất Biên (Boundary Extraction)
- **OpenTelemetry Context Integration:** Tự động trích xuất `current_trace_id()` từ OpenTelemetry Context trong `get_ai_assistant_response()`.
- **gRPC Trailing Metadata `x-trace-id`:** Trả vết `x-trace-id` về gRPC client qua Trailing Metadata của gRPC response, cho phép client truy vết chính xác từng cuộc gọi.

### 3.2 Dual-Key Redis Trace Storage (`TTL 86400s`)
Mỗi request được lưu song song dưới 2 khóa Redis để phục vụ cả truy vấn nội bộ lẫn HTTP API:
- `product_reviews:llm_trace:{trace_id}` (Key nội bộ theo namespace)
- `trace:{trace_id}` (Key chuẩn mở cho HTTP GET /trace/{trace_id})

### 3.3 Đáp ứng đầy đủ 8 Trường Lõi của Yêu Cầu 1
Mỗi bản ghi Trace Record đều lưu vết chi tiết 8 nhóm thông tin cốt lõi theo đúng chỉ thị Mandate #24:
1. **Model + Version:** Ghi chính xác model & provider (`candidate.model`: `"amazon.nova-lite-v1:0"`, `judge.model`: `"amazon.nova-micro-v1:0"`).
2. **Token vào/ra:** Ghi nhận `input_tokens`, `output_tokens`, `total_tokens` cho từng lượt gọi candidate và judge.
3. **Chi phí ước tính (Estimated Cost):** Hàm `estimate_cost_usd()` tính chi phí USD tự động dựa trên bảng đơn giá tĩnh (`_PRICE_PER_1M_TOKENS`).
4. **Độ trễ (Latency):** Ghi nhận `latency_ms` cho từng model call và `total_latency_ms` cho toàn bộ end-to-end request.
5. **Tool calls:** Bề mặt `product-reviews` RAG Q&A ghi nhận trạng thái tool usage `tool_calls: []` (N/A cho bề mặt tóm tắt review).
6. **Phiên / User (Ẩn danh hợp lệ):** Lưu vết `user_id_hash` (SHA256 băm từ `x-user-id` / `x-replay-user-id`) và `session_id`. Tuyệt đối **không lưu chuỗi thô identity của người dùng**.
7. **Thời điểm (Timestamp):** Thời điểm bắt đầu `created_at` và thời điểm kết thúc `completed_at` dưới định dạng chuẩn ISO 8601 UTC (`_utc_now_iso()`).
8. **Kết quả (Outcome / Status / Fallback):** Phân loại kết quả rõ ràng qua `outcome` (`grounded_answer`, `fallback`, `unverified`, `out_of_scope`, `error`), `response_class` và `fallback_reason`.

### 3.4 Khả năng truy vết End-to-End & Dựng lại Chuỗi lời gọi AI (Yêu Cầu 2)
Chỉ với **một `trace_id` duy nhất** thu được từ gRPC metadata header (`x-trace-id`) hoặc HTTP `/replay`, khi truy vấn `GET /trace/{trace_id}`, hệ thống cho phép **dựng lại 100% chuỗi cuộc gọi AI (Call Chain Lifecycle)** theo đúng thứ tự thời gian:
1. **Bước 1 (Retrieval & Input Guardrails):** Truy vấn review Postgres + Kiểm tra an toàn `guardrails.input_safe: true`.
2. **Bước 2 (Cache Check):** Tra cứu Redis Cache $\rightarrow$ Ghi nhận `cache.hit: false` và `cache.key_sha256`.
3. **Bước 3 (Candidate LLM Call):** Gọi Bedrock Nova Lite sinh câu tóm tắt $\rightarrow$ Ghi nhận trong chuỗi `candidate.calls[0]` (`latency_ms: 900.12`, `input_tokens: 123`, `output_tokens: 45`).
4. **Bước 4 (Judge LLM Call):** Gọi Bedrock Nova Micro kiểm duyệt độ trung thực $\rightarrow$ Ghi nhận trong chuỗi `judge.calls[0]` (`status: approved`, `latency_ms: 700.34`, `input_tokens: 456`, `output_tokens: 78`).
5. **Bước 5 (Tool Calls Status):** Ghi nhận `tool_calls: []` (Bề mặt Q&A RAG tóm tắt không cần gọi external tool).
6. **Bước 6 (Final Output & Outcome):** Tổng hợp `total_latency_ms: 1750.46`, `outcome: grounded_answer` và băm kết quả `response_sha256`.

### 3.5 View tổng hợp Cost / Token / Latency theo Model, Bề mặt & Thời gian (Yêu Cầu 3)
Hệ thống cung cấp khả năng **báo cáo & tổng hợp dữ liệu (Aggregate Metrics View)** giúp người vận hành theo dõi chi phí, token tiêu thụ và độ trễ mà **không phải đọc hay grep log thô**:
1. **Tổng hợp theo Model AI:** Tự động phân tách và tính tổng chi phí USD/tokens giữa Candidate (`amazon.nova-lite-v1:0`) và Judge (`amazon.nova-micro-v1:0`) trong tệp báo cáo tổng hợp [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json) & [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json).
2. **Tổng hợp theo Bề Mặt AI (Surface / Operation):** Đánh nhãn phân loại thuộc bề mặt `service: product-reviews`, `operation: AskProductAIAssistant` (RAG Summary Q&A).
3. **Tổng hợp theo Thời Gian (Time Window):** Ghi nhận các mốc thời gian ISO 8601 (`created_at`, `completed_at`, `timestamp`) cùng các chỉ số thống kê tổng hợp `p50_latency_seconds`, `p95_latency_seconds`, `total_tokens`, `total_bedrock_calls`, `estimated_cost_usd`.
4. **Cấu Trúc Metric Log Chuẩn (Structured Telemetry):** Đưa ra dòng log định dạng chuẩn `AI_USAGE role=candidate provider=bedrock model=... input_tokens=... output_tokens=... latency_ms=...` hỗ trợ Grafana / Prometheus / CloudWatch tự động trích xuất dashboard tổng hợp theo thời gian thực.

### 3.6 Cơ chế chống rò rỉ PII / Secret trong Trace (Yêu Cầu 4)
Hệ thống tuân thủ nghiêm ngặt nguyên tắc **Audit-Safe Black-Box Tracing (Không thành chỗ rò rỉ dữ liệu nhạy cảm)**:
1. **Mã Hóa SHA-256 Cho Toàn Bộ Prompt & Response:**
   - Khi request chứa chuỗi PII / bí mật (ví dụ: `PII-TOKEN-XYZ`, số thẻ credit, email, hoặc mật khẩu) trong prompt câu hỏi hoặc dữ liệu review, hệ thống **tuyệt đối KHÔNG lưu văn bản thô** của prompt hay response vào trace record.
   - Prompt câu hỏi được băm một chiều qua `question_sha256`: `hashlib.sha256(question.encode('utf-8')).hexdigest()`.
   - Kết quả phản hồi được băm một chiều qua `response_sha256`: `hashlib.sha256(response_text.encode('utf-8')).hexdigest()`.
   - Thông tin người dùng được băm một chiều qua `user_id_hash`.
2. **Minh Chứng Không Rò Chuỗi Thô (Zero Raw Leakage Proof):**
   - Truy vấn tệp trace JSON record thu được bằng từ khóa `PII-TOKEN-XYZ` hoặc chuỗi nhạy cảm bất kỳ $\rightarrow$ **Kết quả 0 match (không tồn tại chuỗi thô)**.

---

## 📊 4. Cấu Trúc Trace Record Chi Tiết (Trace JSON Schema)

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

## 🛠️ 5. Hướng Dẫn Mentor Kiểm Thử & Lệnh Tái Tạo (Repro & Mentor Test Guide)

### A. Khởi chạy HTTP Trace Server (Port 8086)
```powershell
$env:PRODUCT_REVIEWS_TRACE_HTTP_PORT="8086"
$env:PRODUCT_REVIEWS_TRACE_HTTP_ALLOW_UNAUTHENTICATED="true"
```

### B. Kiểm thử Request Thường & Truy vết End-to-End (`POST /replay` & `GET /trace/{id}`)
1. **Gửi Request giả lập Replay:**
   ```powershell
   curl.exe -X POST `
     -H "Content-Type: application/json" `
     -d "{\"question\":\"Do reviewers say the kit removes dust?\",\"product_id\":\"L9ECAV7KIM\",\"user_id\":\"jira-smoke\",\"session_id\":\"ai-124\"}" `
     http://localhost:8086/replay
   ```
2. **Kéo Trace Record theo ID nhận được:**
   ```powershell
   curl.exe http://localhost:8086/trace/<trace-id>
   ```

### C. Kiểm thử Bảo mật PII Marker (`PII-TOKEN-XYZ`)
1. Gửi request có chứa đánh dấu PII:
   ```powershell
   curl.exe -X POST -H "Content-Type: application/json" -d "{\"question\":\"Review for PII-TOKEN-XYZ-SECRET\",\"product_id\":\"L9ECAV7KIM\"}" http://localhost:8086/replay
   ```
2. Kéo trace theo ID và tìm kiếm `PII-TOKEN-XYZ-SECRET` $\rightarrow$ Xác nhận kết quả **0 match** (đã băm thành `question_sha256`).

### D. Kiểm thử Ghi Vết Lỗi & Fallback Outcome (`POST /inject/error`)
1. Kích hoạt giả lập lỗi Fallback:
   ```powershell
   curl.exe -X POST -H "Content-Type: application/json" -d "{\"active\": true, \"error_type\": \"rate_limit_exceeded\"}" http://localhost:8086/inject/error
   ```
2. Gửi request replay và fetch trace $\rightarrow$ Trace record ghi nhận `outcome: fallback` và `fallback_reason: rate_limit_exceeded`.
3. Tắt giả lập lỗi:
   ```powershell
   curl.exe -X POST -H "Content-Type: application/json" -d "{\"active\": false}" http://localhost:8086/inject/error
   ```

---

## 📁 6. Danh Mục Mã Nguồn & Tệp Bằng Chứng Trong Repo (Artifact Registry)

### A. Mã nguồn Tracing & Server Handler
*   **Logic Tracing & Audit-Safe Record Generator:** [guardrails/llm_trace.py](../../techx-corp-platform/src/product-reviews/guardrails/llm_trace.py)
*   **Logic gRPC Metadata Trailing & Class `LLMTraceHTTPHandler`:** [product_reviews_server.py](../../techx-corp-platform/src/product-reviews/product_reviews_server.py)
*   **Mã nguồn kiểm thử tự động Tracing:** [test_runtime_guardrails.py](../../techx-corp-platform/src/product-reviews/test_runtime_guardrails.py)

### B. Báo cáo kiến trúc & Tài liệu liên quan
*   **Tài liệu Kiến trúc ADR 0008 (Runtime LLM Trace):** [0008-LLM-OBSERVABILITY.md](../adr/0008-LLM-OBSERVABILITY.md) & [0008-runtime-llm-trace-auditability.md](../adr/0008-runtime-llm-trace-auditability.md)
*   **Chỉ thị gốc Mandate 24:** [MANDATE-24-llm-observability.md](../../mandates/MANDATE-24-llm-observability.md)
*   **Artifact JSON Báo cáo Baseline Sau Khi Có Cache:** [cost_latency_baseline.json](../../repro/artifacts/cost_latency_baseline.json)
*   **Artifact JSON Báo cáo Baseline So Sánh Caching:** [cost_latency_comparison.json](../../repro/artifacts/cost_latency_comparison.json)
