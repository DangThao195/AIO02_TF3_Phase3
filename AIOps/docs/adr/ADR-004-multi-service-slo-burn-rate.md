# ADR-004: Thuật Toán SLO Burn Rate Đa Cửa Sổ Đa Dịch Vụ (Multi-Window Multi-Service SLO Burn Rate)

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-15
- **Tác giả / Ký tên**: Hảo (Leader team AIOps)
- **Phạm vi tác động**: AI Engine (`aiops-engine`), Giám sát SLO

---

## 1. Bối cảnh (Context)

Cơ chế kiểm tra SLO Burn Rate ban đầu chỉ theo dõi duy nhất dịch vụ `frontend` qua chỉ số HTTP 5xx của Prometheus. Thiết kế này có 2 hạn chế lớn:
1. **Bị mù lỗi Backend:** Nếu dịch vụ backend như `checkout` bị lỗi gRPC/HTTP âm thầm và `frontend` bắt exception này trả về giao diện bình thường kèm thông báo lỗi trên UI (HTTP 200 OK), chỉ số HTTP 5xx của frontend không đổi. SLO Burn Rate sẽ hoàn toàn bị mù trước lỗi của backend.
2. **Không phân biệt được Service lỗi:** Bộ giám sát không xác định được dịch vụ nào là nguồn gốc gây sụt giảm SLO.

---

## 2. Quyết Định Kiến Trúc (Decisions)

### **A. Nâng cấp lên OpenTelemetry Span Metrics**
* Thay vì chỉ quét HTTP status 5xx, hệ thống chuyển sang giám sát **OTel Span Metrics** (`traces_span_metrics_calls_total` và `traces_span_metrics_duration_milliseconds_bucket` lọc theo `span_kind="SPAN_KIND_SERVER"`).
* Mọi lỗi nội bộ của backend (bao gồm mã lỗi gRPC hoặc Server Span Error) đều được ghi nhận trực tiếp ở mức độ Service cụ thể.

### **B. Quét song song Đa cửa sổ & Đa dịch vụ (Multi-Service Multi-Window)**
* AI Engine sẽ thực hiện kiểm tra song song cho cả **7 dịch vụ chính** trong cụm.
* Ở mỗi chu kỳ quét 30 giây, hệ thống tính toán đồng thời tỷ lệ tiêu thụ ngân sách lỗi (Burn Rate) ở 2 cửa sổ:
  * **Cửa sổ 5 phút ($br_{5m}$):** Ngưỡng vỡ $\ge 14.4$.
  * **Cửa sổ 1 giờ ($br_{1h}$):** Ngưỡng vỡ $\ge 14.4$.
* **Công thức PromQL động:**
  `sum(rate(traces_span_metrics_calls_total{service_name="{service}", span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}[{window}])) / sum(rate(traces_span_metrics_calls_total{service_name="{service}", span_kind="SPAN_KIND_SERVER"}[{window}])) * 720`
* Nếu bất kỳ dịch vụ nào vi phạm đồng thời cả 2 ngưỡng trên ở cả hai cửa sổ, hệ thống lập tức báo động **Vỡ SLO** cho dịch vụ đó và kích hoạt luồng chẩn đoán tự động.

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
* **Bảo vệ toàn diện (Full Stack SLO):** Phát hiện lỗi gRPC/HTTP âm thầm của toàn bộ backend.
* **Giảm thiểu cảnh báo giả:** Việc yêu cầu vi phạm đồng thời cả 2 cửa sổ (5m và 1h) giúp loại bỏ các spike nhiễu tức thời (nhất thời vọt lên trong 1-2 giây rồi hết).

### **Đánh đổi**:
* Tăng số lượng câu lệnh PromQL gửi đến Prometheus mỗi 30 giây (7 services x 2 windows = 14 queries). Tuy nhiên, Prometheus được thiết kế để xử lý hàng ngàn query/giây nên tải lượng này là hoàn toàn không đáng kể.
