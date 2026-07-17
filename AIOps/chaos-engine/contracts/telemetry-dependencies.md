# Phụ thuộc Telemetry (Telemetry Dependencies)

> Tham chiếu từ [C1](C1-telemetry-access.md). **CDO check file này trước khi refactor observability.** Rename/xóa mục nào trong bảng = vỡ detector/alert tương ứng.
> AIO02 cập nhật file này mỗi khi thêm rule mới.

| Nguồn | Metric / Index / API | Label bắt buộc | Dùng bởi | Trạng thái |
|---|---|---|---|---|
| Prometheus | `http_requests_total` | `service`, `code` | Burn-rate SLO (C2 lớp 1) | **Đang hoạt động** |
| Prometheus | `db_connection_pool_status` | `service`, `pool_id` | Giám sát Connection Pool (INCIDENT-2026-004) | **Đang hoạt động** |
| Prometheus | `ai_gateway_requests_total` | `outcome`, `model`, `feature` | C4 (AI Gateway health) | **Đang hoạt động** |
| Prometheus | `ai_cost_tokens_total`, `ai_cost_usd_total` | `model`, `feature` | C5 (AI cost tracker) | **Đang hoạt động** |
| Prometheus | `container_cpu_usage_seconds_total` | `pod`, `namespace` | ML anomaly detection (C2 lớp 2) | **Đang hoạt động** |
| Prometheus | `container_memory_working_set_bytes` | `pod`, `namespace` | ML anomaly detection (C2 lớp 2) | **Đang hoạt động** |
| OpenSearch | `otel-logs-*` | `service`, `level`, `@timestamp` | Log mining, Evidence Pack (C3) | **Đang hoạt động** |
| OpenSearch | `ai-engine-*`, `ai-engine-audit-*` | — | Log engine + audit trail (C6) | **Đang hoạt động** |
| Jaeger | `http://jaeger-query:16686/api/traces` | `service` | Trích xuất trace, lập RCA (C3) | **Đang hoạt động** |

_Trạng thái: Đã cập nhật đầy đủ và chính xác các tên metric và index hoạt động thực tế trên cụm EKS `techx-tf3` sau khi chạy baseline._
