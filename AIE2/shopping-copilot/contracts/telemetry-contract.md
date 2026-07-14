# Telemetry Contract - Task force 02 (Phase 3)
**Dự án:** Shopping Copilot (AIE2)

<!-- Owner: Nhóm AI 02
     Signed by: AI Lead + CDO Leads
     Date signed: 2026-07-14
     🔒 FREEZE - no change without formal change request -->

## 1. Mục đích

Định nghĩa **các tín hiệu giám sát (Metrics & Traces)** mà AI Engine (AIE) chủ động phát ra (emit) thông qua chuẩn OpenTelemetry để bên CDO thu thập (ingest). Handshake này giúp đảm bảo khả năng quan sát trạng thái của AI Agent (Observability) trên môi trường production.

---

## 2. Traces (Dấu vết thực thi)

AIE tự động tạo và xuất (export) các OpenTelemetry Spans cho mỗi request của người dùng, phân rã chi tiết quá trình suy luận (ReAct loop).

### 2.1 Trace Propagation (Lan truyền mã định danh)
* AIE nhận `X-Correlation-Id` hoặc HTTP context propagation headers (W3C Trace Context) từ API Gateway/Frontend.
* AIE truyền tiếp `TraceContext` này vào các cuộc gọi gRPC nội bộ đến các microservices (Catalog, Cart...) để CDO có thể vẽ sơ đồ vết cuộc gọi từ client tới tận cơ sở dữ liệu.

### 2.2 Các Spans đặc trưng trong ReAct Loop
CDO có thể theo dõi và tính toán độ trễ (latency breakdown) của AIE dựa trên các Span Name sau:

| Span Name | Type | Description |
|---|---|---|
| `api_chat_request` | Parent Span | Toàn bộ vòng đời xử lý của một API request chat |
| `LLMInvoke` | Child Span | Thời gian gọi API AWS Bedrock để sinh câu trả lời |
| `InputFilter` | Child Span | Thời gian lọc prompt của người dùng tránh prompt injection |
| `OutputFilter` | Child Span | Thời gian quét nội dung phản hồi tránh lộ thông tin PII |
| `Exec: <tool_name>` | Child Span | Thời gian gọi gRPC Client thực thi công cụ (vd `Exec: search_products_v2`) |

---

## 3. Metrics (Chỉ số đo lường)

AIE xuất các Prometheus Metrics theo định dạng OpenTelemetry Prometheus Exporter để CDO cấu hình Dashboard Grafana.

### Metric 1: `copilot_llm_tokens_total`
* **Type:** Counter
* **Labels:** `model_id` (vd `amazon.nova-lite-v1`), `user_id`, `token_type` (`input` / `output`)
* **Used for:** Giám sát chi phí gọi API Bedrock theo thời gian thực và phát hiện hành vi spam token của người dùng.

### Metric 2: `copilot_guardrail_blocks_total`
* **Type:** Counter
* **Labels:** `guardrail_layer` (`L2a_InputFilter`, `L2b_BedrockGuardrail`, `L3_ToolValidator`, `L4_OutputFilter`), `user_id`
* **Used for:** Giám sát mức độ an toàn của hệ thống. Nếu tỷ lệ block tăng cao đột biến, có thể hệ thống đang bị tấn công Prompt Injection hoặc phát sinh dữ liệu lỗi.

### Metric 3: `copilot_tool_calls_total`
* **Type:** Counter
* **Labels:** `tool_name` (vd `add_to_cart_tool`), `status` (`OK`, `ERROR`, `BLOCK`)
* **Used for:** Đo lường hành vi khách hàng sử dụng các tính năng tìm kiếm, giỏ hàng, xem reviews.

### Metric 4: `copilot_request_latency_seconds`
* **Type:** Histogram (Buckets: `[0.1, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0]`)
* **Labels:** `endpoint` (vd `/api/chat`), `status_code` (`200`, `429`, `500`)
* **Used for:** Đo lường trải nghiệm người dùng và thiết lập cảnh báo SLA latency.

---

## 4. Đặc tả kỹ thuật xuất dữ liệu (Data Export Spec)

* **Protocol:** OTLP/gRPC (OpenTelemetry Protocol).
* **OTel Collector Endpoint:** Được cấu hình thông qua biến môi trường `OTEL_EXPORTER_OTLP_ENDPOINT` (CDO thiết lập Service DNS trong Kubernetes).
* **Export Interval:**
  * Traces: Batch export mỗi 5 giây.
  * Metrics: Pull-based Prometheus endpoint `/metrics` hoặc Push-based OTLP metric exporter mỗi 30 giây.

---

## 5. Phân định Trách nhiệm Giám sát (Monitoring Ownership)

Để tối ưu hóa vận hành, trách nhiệm giám sát (Alerting & Dashboards) được phân định rõ ràng giữa hai nhóm:

### 5.1 Nhóm AI (AIE Team) - Giám sát tầng Ứng dụng & Nghiệp vụ AI
Nhóm AI chịu trách nhiệm thiết lập Dashboard và Cảnh báo cho các chỉ số đặc thù của AI:
* **Token & Chi phí:** Theo dõi lượng token tiêu thụ (`copilot_llm_tokens_total`) để kiểm soát hóa đơn AWS Bedrock.
* **Độ an toàn (Guardrails):** Theo dõi số lượng request bị block bởi các lớp Guardrail (`copilot_guardrail_blocks_total`) để phát hiện tấn công Prompt Injection hoặc lỗi logic lọc dữ liệu.
* **Hiệu năng ReAct Loop:** Theo dõi độ trễ của từng bước trong Agent (`LLMInvoke`, `InputFilter`, `OutputFilter`, `Exec: <tool_name>`).
* **Hành vi gọi Tool:** Thống kê tỷ lệ gọi thành công/thất bại của các tools (`copilot_tool_calls_total`).

### 5.2 Nhóm DevOps/Platform (CDO Team) - Giám sát Hạ tầng & Kết nối mạng
Nhóm CDO chịu trách nhiệm thiết lập Dashboard và Cảnh báo cho các chỉ số hạ tầng vật lý:
* **Tài nguyên tính toán:** CPU/RAM của EKS Pods, trạng thái khởi động Pod, số lượng replica thực tế.
* **Mạng & Cổng kết nối:** Trạng thái hoạt động của VPC Endpoint kết nối Bedrock, kết nối gRPC nội bộ giữa các microservices.
* **Lưu lượng tổng:** Số lượng request và HTTP status code tổng quát tại Application Load Balancer (ALB).
* **Database & Storage:** Tài nguyên máy chủ RDS PostgreSQL (CPU, IOPS, Connections).
