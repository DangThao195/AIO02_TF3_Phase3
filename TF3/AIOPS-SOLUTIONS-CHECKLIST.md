# AIOPS SOLUTIONS CHECKLIST - TF3

Tài liệu tổng hợp toàn bộ các giải pháp kỹ thuật và giải thuật AIOps được triển khai trong hệ thống **AIOps Engine (CMDR)** của nhóm TF3.

---

## 1. PHÁT HIỆN SỰ CỐ (DETECTION LAYER)

- [x] **SLO Burn-rate Monitor (Google SRE Standard):**
  - Cảnh báo dựa trên tốc độ tiêu thụ Quỹ lỗi (Error Budget) thay vì ngưỡng tĩnh.
  - Áp dụng cơ chế đa cửa sổ (Multi-window Multi-burn-rate):
    - Cửa sổ ngắn (Short window): 5 phút (phản ứng nhanh).
    - Cửa sổ dài (Long window): 1 giờ (đảm bảo lỗi kéo dài).
  - Ngưỡng kích hoạt Alert: Burn-rate $\ge 14.4$ (đốt cháy hết 2% quỹ lỗi trong 1 giờ) trên cả 2 cửa sổ đồng thời.
  - Mức độ nghiêm trọng: `critical` (kích hoạt luồng sửa lỗi tự động).

- [x] **Dynamic Rolling Z-Score Monitor:**
  - Giám sát các chỉ số hạ tầng (CPU, RAM, DB Connections, Kafka Lag) cho từng service.
  - Tính toán ngưỡng động dựa trên giá trị trung bình ($\mu$) và độ lệch chuẩn ($\sigma$) trượt trong 7 ngày qua của từng dịch vụ từ Prometheus.
  - Công thức tính: $Z_t = \frac{x_t - \mu_{7d}}{\sigma_{7d}}$
  - Ngưỡng kích hoạt Alert: $|Z| > 3.0$ liên tục trong 5 chu kỳ quét (150 giây).
  - Mức độ nghiêm trọng: `warning` (chỉ thông báo lên Slack, không tự động sửa lỗi).

- [x] **Dự phòng Giám sát (Alertmanager Redundancy):**
  - Cấu hình các alert rules thô trực tiếp trên Prometheus server chạy song song.
  - Tự động phát alert `ai_engine_blind` (Severity: warning) khi Pod AI Engine chính bị sập (Crash/OOM) để SRE biết hệ thống chẩn đoán thông minh đang dừng hoạt động.

---

## 2. GOM NHÓM CẢNH BÁO (CORRELATION & DEDUP)

- [x] **Khử trùng lặp (Dedup):**
  - Tạo dấu vân tay (Fingerprint) duy nhất cho mỗi alert theo định dạng khóa `{service, sli, rule}`.
  - Tự động bỏ qua các alert trùng lặp phát sinh liên tục trong vòng 15 phút.

- [x] **Gom nhóm theo Topology (Correlation):**
  - Liên kết các cảnh báo phát sinh đồng thời trong cùng cửa sổ thời gian (120-300s).
  - Duyệt bản đồ dịch vụ (Service Dependency Graph) để gom các alert có khoảng cách liên kết $\le 2$ bước nhảy (hops) thành một Incident duy nhất.

---

## 3. CHẨN ĐOÁN NGUYÊN NHÂN GỐC (RCA & EVIDENCE PACK)

- [x] **Graph-based RCA (Jaeger Spans):**
  - Dựng cây đồ thị cuộc gọi (Call Tree) từ dữ liệu Jaeger Spans thời gian thực.
  - Duyệt cây từ nút gốc (frontend) xuống để tìm nút lỗi sâu nhất (leaf-most error node) trả về mã lỗi HTTP 5xx hoặc gRPC error.
  - Xác định chính xác nút này là **Thủ phạm gốc (Culprit Service)** thay vì sắp xếp bảng chữ cái thông thường.

- [x] **Tích hợp Nhật ký Thay đổi (Change Log):**
  - Đối chiếu thời gian xảy ra sự cố với kênh `#tf3-changes`.
  - Nếu phát hiện có sự kiện thay đổi (`[change]`) trong vòng $\le 10$ phút trước sự cố (ví dụ: `helm upgrade`), tự động gắn nhãn sự kiện này làm nghi phạm số 1.

- [x] **Gom cụm Log (Drain3 Log Clustering):**
  - Tự động truy vấn log lỗi của culprit service từ OpenSearch trong cửa sổ $t \pm 30s$.
  - Áp dụng thuật toán Drain3 để loại bỏ các biến động (IPs, IDs, Timestamps) và gom các log thô thành các Template mẫu kèm số lượng đếm để gửi LLM.

- [x] **Đóng gói Bằng chứng (Evidence Pack):**
  - Tự động tạo tệp `evidence-pack.md` bao gồm: Ảnh chụp metrics Prometheus quanh sự cố, 3 Trace IDs lỗi nặng nhất từ Jaeger, và mẫu log lỗi tiêu biểu từ Drain3.

---

## 4. CHẨN ĐOÁN BẰNG AI & THƯ VIỆN LỊCH SỬ (LLM DIAGNOSTIC ENGINE)

- [x] **AWS Bedrock Gateway:**
  - Kết nối và gọi mô hình ngôn ngữ lớn (AWS Bedrock / OpenAI gpt-4o-mini) qua API bảo mật.
  - Nạp tệp tri thức lịch sử `INCIDENT_HISTORY.md` vào ngữ cảnh (In-Context Learning) để AI chẩn đoán.

- [x] **Giải thuật Đối chiếu Sự cố:**
  - Sử dụng Keyword Matching dựa trên bộ từ khóa định nghĩa sẵn (`INCIDENT_PATTERNS`) đối với từng sự cố INC-1 đến INC-8 để đảm bảo phản hồi nhanh và chính xác.
  - Hỗ trợ phân tích độ tin cậy và đề xuất hành động sửa lỗi tương ứng.

---

## 5. PHỤC HỒI & PHÊ DUYỆT (REMEDIATION & VERIFICATION)

- [x] **Cổng phê duyệt (Human-in-the-loop):**
  - Gửi thẻ chẩn đoán chi tiết và đề xuất giải pháp vá lỗi (Action) lên kênh Slack.
  - Đợi phản hồi phê duyệt (Approve/Reject) từ SRE trực qua nút nhấn Slack webhook.

- [x] **Thực thi lệnh vá lỗi an toàn:**
  - Sử dụng `shlex.split` để phân tách lệnh K8s an toàn, ngăn chặn hoàn toàn lỗ hổng Command Injection.
  - Chạy các lệnh vá lỗi (như `kubectl scale`, `kubectl rollout restart`) thông qua `asyncio.to_thread` để tránh gây nghẽn Event Loop của máy chủ FastAPI.

- [x] **Vòng lặp xác minh (Verify Loop) & Tự động Hoàn tác (Rollback):**
  - Sau khi vá lỗi, hệ thống liên tục đo lường lại metrics Prometheus mỗi 30 giây trong vòng 5 phút.
  - Nếu SLO xanh trở lại: Tự động đóng sự cố.
  - If hệ thống vẫn lỗi sau 5 phút: Tự động chạy lệnh **Rollback** để hoàn tác hành động cũ, tránh làm lỗi nặng thêm, đồng thời cảnh báo khẩn cấp cho SRE.

- [x] **An toàn khi Mất Giám sát (Fail-safe):**
  - Nếu dữ liệu giám sát (telemetry) bị mất kết nối hoặc trả về rỗng, hệ thống coi như chưa phục hồi và tự động kích hoạt rollback an toàn.

---

## 6. KIỂM THỬ TỰ ĐỘNG (VERIFICATION SUITE)

- [x] **Bộ kiểm thử tích hợp & Unit Tests:**
  - Tổng số **112 test cases** bao phủ toàn bộ các module (Cache, Correlation, RCA, Remediation, Guardrail, Server, Config).
  - Tỷ lệ kiểm thử thành công: **100% PASS** ổn định.
