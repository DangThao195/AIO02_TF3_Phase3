# Telemetry Dependencies — metric/label AI engine đang tiêu thụ

> Tham chiếu từ [C1](C1-telemetry-access.md). **CDO check file này trước khi refactor
> observability.** Rename/xóa mục nào trong bảng = vỡ detector/alert tương ứng.
> AIO02 cập nhật file này mỗi khi thêm rule mới.

| Nguồn | Metric / Index / API | Label bắt buộc | Dùng bởi |
|---|---|---|---|
| Prometheus | `http_requests_total` (frontend-proxy, checkout, cart) | `service`, `code` | Burn-rate SLO (C2 lớp 1) |
| Prometheus | `http_request_duration_microseconds` | `service`, `le` | SLO p95 < 1s |
| Prometheus | `app_ai_assistant_counter` (do AIO tự phát trong Tuần 1) | `product.id`, `cache`, `status` | C4 (AI Health, Cache & Error tracking) |
| Prometheus | `app_product_review_counter` (do AIO tự phát) | `product.id` | Giám sát tần suất review |
| Prometheus | `ai_gateway_*`, `ai_cost_*` (do AIO phát triển thêm ở Tuần 2-3) | `outcome`, `model`, `feature` | C4, C5 |
| Prometheus | kafka consumer lag, container CPU/memory | `pod`, `namespace` | ML anomaly (C2 lớp 2) |
| OpenSearch | `otel-logs-*` | `service`, `level`, `@timestamp` | Log mining, Evidence Pack (C3) |
| OpenSearch | `ai-engine-*`, `ai-engine-audit-*` (AIO ghi) | — | Log engine + audit (C6) |
| Jaeger | query API theo `service` + `tags(error=true)` | — | Exemplar traces (C3) |

_Trạng thái: khởi tạo trước khi deploy baseline — các tên metric chính xác sẽ được điền
ngay sau khi hệ thống chạy và AIO rà Prometheus thực tế (việc Tuần 1)._
