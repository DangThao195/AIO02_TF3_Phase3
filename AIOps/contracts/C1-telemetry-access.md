# C1 — Telemetry Access Contract

| Trường | Giá trị |
|---|---|
| Version | 1.0.0 |
| Producer (bên cung cấp) | **CDO01 + CDO02** (chủ hạ tầng observability) |
| Consumer (bên dùng) | **AIO02** (AI engine — detection, RCA, cost meter) |
| Trạng thái | Draft — chờ CDO review |
| Review cadence | Standup hằng ngày khi có thay đổi; chốt lại mỗi Ops Review |

## Mục đích

AI engine của AIO02 **chỉ đọc** telemetry, không sở hữu nó. CDO sở hữu Prometheus /
OpenSearch / Jaeger / Grafana (deploy qua Helm chart). Contract này chốt: AIO được đọc
cái gì, ở đâu, và CDO cam kết gì để model/detector của AIO không gãy giữa chừng.

---

## INPUT — thứ CDO cung cấp cho AIO

### 1. Endpoints (trong cluster, namespace mặc định của chart)

| Nguồn | Endpoint | Giao thức | AIO dùng để |
|---|---|---|---|
| Prometheus | `http://prometheus:9090/api/v1/*` | HTTP API (PromQL) | Burn-rate SLO, ML anomaly, cost metrics |
| OpenSearch | `http://opensearch:9200/<index>/_search` | REST (DSL query) | Log mining, evidence cho RCA |
| Jaeger | `http://jaeger-query:16686/api/*` | HTTP API | Exemplar traces cho RCA |
| Grafana | `http://grafana:3000` (qua frontend-proxy `/grafana/`) | UI/API | Đặt dashboard AI health |

> Nếu CDO đổi tên service/namespace khi refactor chart → **phải cập nhật bảng này trước khi merge**.

### 2. Cam kết chất lượng dữ liệu (data SLA của CDO)

| Cam kết | Ngưỡng | Vì sao AIO cần |
|---|---|---|
| Scrape interval Prometheus | ≤ 30s, không đổi đột ngột | Cửa sổ ngắn 5m của burn-rate alert cần ≥ 10 điểm dữ liệu |
| Metric retention | ≥ 7 ngày | Cửa sổ dài nhất của alert là 3 ngày; baseline ML cần 1 tuần |
| Log retention (OpenSearch) | ≥ 3 ngày | Evidence Pack cho postmortem trong tuần |
| Trace sampling | Giữ nguyên chính sách sampling hiện tại; muốn đổi phải báo trước 1 ngày | Đổi sampling âm thầm = RCA mất exemplar, detector lệch baseline |
| Label/naming convention | Không rename metric/label đang được alert rule tham chiếu mà không báo | Rename âm thầm = alert rule chết im lặng (silent failure) |

### 3. Quyền truy cập
- AIO chạy component trong cùng cluster: cần NetworkPolicy (nếu CDO siết) cho phép
  namespace của AI engine gọi 3 endpoint trên, **read-only**.
- AIO **không** cần và **không** được cấp quyền ghi vào Prometheus/OpenSearch
  (trừ index riêng `ai-engine-*` cho log của chính engine — xem OUTPUT).

---

## OUTPUT — thứ AIO trả lại cho CDO

1. **Danh sách metric/label đang được AI engine tiêu thụ** — file
   `TF3/contracts/telemetry-dependencies.md` (AIO duy trì). CDO check file này trước khi
   refactor observability để biết đụng gì thì vỡ gì.
2. **Recording rules đề xuất** (PromQL) cho các SLI: AIO viết, CDO review + merge vào
   cấu hình Prometheus. Ví dụ:
   ```promql
   # SLI: tỉ lệ checkout thành công (rolling)
   sli:checkout_success:ratio_rate5m =
     sum(rate(http_requests_total{service="checkout",code!~"5.."}[5m]))
     / sum(rate(http_requests_total{service="checkout"}[5m]))
   ```
3. **Dashboard "AI Engine Health"** trong Grafana: trạng thái detector, số alert đã phát,
   precision ước tính, độ trễ pipeline — để CDO thấy engine sống hay chết.
4. Log của AI engine ghi vào index riêng `ai-engine-*` trong OpenSearch (không lẫn
   với log sản phẩm).

## Failure modes & xử lý

| Tình huống | Hành vi thỏa thuận |
|---|---|
| Prometheus down / không scrape được | AI engine ngừng phát alert mới, phát **1 alert meta** `ai_engine_blind` (severity warning) cho on-call biết "mắt đang mù", không im lặng |
| Metric bị rename không báo | AIO phát hiện qua absent-check hằng giờ; báo ở standup; CDO rollback hoặc AIO cập nhật rule — quyết định ghi ADR |
| OpenSearch chậm (>10s/query) | RCA Evidence Pack ghi chú "log evidence không đầy đủ" thay vì treo |

## Tiêu chí nghiệm thu (Definition of Done)

- [ ] AIO query được cả 3 nguồn từ pod trong cluster (có bằng chứng: script + output).
- [ ] `telemetry-dependencies.md` tồn tại và được CDO xác nhận đã đọc.
- [ ] Absent-check cho metric quan trọng chạy và có alert meta.
- [ ] Hai bên ký tên vào ADR khởi tạo contract này.
