# Telemetry Contract - AIE2 Shopping Copilot

<!-- Owner: AIO02 | Signed by: AI Lead + CDO Leads | Date: 2026-07-14 -->

## Mục đích

Đặc tả các **Metrics và Traces AIE phát ra** để CDO mở rộng Dashboard Grafana/Jaeger hiện có của TF.

---

## Metrics (Prometheus)

AIE expose endpoint `/metrics` (Prometheus format) tại port `8001`.  
CDO thêm scrape target này vào Prometheus config của TF là đủ.

| Metric name | Type | Labels | Mục đích CDO dùng |
|---|---|---|---|
| `copilot_request_latency_seconds` | Histogram | `endpoint`, `status_code` | Alert khi P99 > 3s hoặc error rate tăng |
| `copilot_llm_tokens_total` | Counter | `model_id`, `token_type` | Dashboard chi phí Bedrock |
| `copilot_guardrail_blocks_total` | Counter | `guardrail_layer` | Alert khi block rate tăng đột biến |
| `copilot_tool_calls_total` | Counter | `tool_name`, `status` | Dashboard sức khoẻ tool (search, cart,...) |

---

## Traces (OpenTelemetry)

AIE gửi traces qua OTLP đến OTel Collector của TF (cấu hình qua env var `OTEL_EXPORTER_OTLP_ENDPOINT`).

CDO có thể xem trên Jaeger với các span name sau:

| Span name | Ý nghĩa |
|---|---|
| `api_chat_request` | Toàn bộ một lượt chat (span cha) |
| `LLMInvoke` | Thời gian gọi AWS Bedrock |
| `InputFilter` / `OutputFilter` | Thời gian qua guardrail |
| `Exec: <tool_name>` | Thời gian gọi gRPC tới microservice (vd `Exec: search_products_v2`) |

---

## Phân định giám sát

| Ai giám sát | Nội dung |
|---|---|
| **AIE** | Token/chi phí Bedrock, guardrail blocks, chất lượng phản hồi, lỗi agent |
| **CDO** | CPU/RAM Pod, trạng thái Pod (CrashLoop, OOM), kết nối mạng, uptime ALB |

> Khi AIE phát hiện lỗi tầng AI → AIE sửa code và push image mới lên ECR → CDO cập nhật deployment.  
> Khi CDO phát hiện Pod sập / tài nguyên vượt ngưỡng → CDO xử lý hạ tầng, báo AIE nếu cần.
