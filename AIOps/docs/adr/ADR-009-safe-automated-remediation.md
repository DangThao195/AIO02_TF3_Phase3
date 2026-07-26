# ADR-009: Safe Automated Self-Remediation & Closed-Loop Control

* **Status:** Approved
* **Date:** 2026-07-22
* **Authors:** SRE & AIOps Task Force (TechX Corp)
* **Deciders:** SRE Team, Lead Architect, AIOps Engineer

---

## 📋 Context & Problem Statement

Theo yêu cầu của **AI MANDATE #22**, một hệ thống vận hành AIOps trưởng thành không thể chỉ dừng lại ở mức độ phát hiện và cảnh báo sự cố. Hệ thống phải có khả năng **Tự dập sự cố một cách an toàn (Closed-loop Self-Remediation)** mà không cần con người phải bấm nút can thiệp thủ công trên Slack.

Tuy nhiên, việc can thiệp tự động không có phanh an toàn có thể gây nguy hiểm (Blast Radius lớn, lặp lệnh vô hạn, hoặc tự dập sai làm sập Gateway). Do đó, kiến trúc tự dập sự cố bắt buộc phải thỏa mãn 5 tiêu chí an toàn:
1. **Safety Check & Dry-Run**: Kiểm tra an toàn và chạy thử (`--dry-run`) trước khi thi hành lệnh thật.
2. **Blast Radius Assessment**: Tính toán tỷ lệ phần trăm ảnh hưởng hạ nguồn trên 7 Application Microservices.
3. **Dynamic Risk Matrix**: Phân loại rủi ro linh hoạt (nâng từ LOW lên MEDIUM đối với `frontend` gateway hoặc khi Blast Radius > 60%).
4. **Telemetry Verification & Auto-Rollback**: Kiểm chứng bằng số liệu Prometheus real-time trong 5 phút; nếu không hồi phục, tự động thực thi kế hoạch lùi (Rollback).
5. **Structured Audit Logging**: Ghi nhận nhật ký kiểm toán tiêu chuẩn JSON Lines (`audit_log.jsonl`).

---

## 🎯 Decision Drivers

* **MTTR Reduction**: Giảm thời gian khắc phục sự cố (MTTR) từ hàng giờ xuống dưới 5 phút đối với các sự cố hạ tầng đã biết trước phương án xử lý.
* **Safety First**: Tuyệt đối không tự động can thiệp vào các dịch vụ cổng chính (`frontend`) hoặc các lệnh tác động trên 60% hạ tầng mà không có sự đồng ý của SRE.
* **Auditability & Traceability**: Mọi hành động tự động phải truy xuất được vết lịch sử đủ 4 bước: `Trigger -> Action -> Verify Result -> Rollback Status`.

---

## 🛠️ Decision Outcome

Chúng tôi quyết định chuẩn hóa kiến trúc Tự Dập Sự Cố Khép Kín (Closed-loop Self-Remediation) trong module `remediation_handler.py`, `alert_correlator.py`, `audit_logger.py` và `main.py` với các quy tắc sau:

### 1. Ma Trận Đánh Giá Rủi Ro (Risk Matrix)
* **BASE RISK**: `scale`, `restart`, `cache-flush`, `breaker-force` $\rightarrow$ **LOW RISK** (Cho phép tự dập không cần người bấm).
* **NÂNG LÊN MEDIUM RISK** (Gửi card Slack chờ SRE Approve) nếu thỏa mãn bất kỳ điều kiện nào:
  * `blast_radius_percent > 60.0%` VÀ action là `scale` / `restart`.
  * `confidence_score < 0.80` (Độ tự tin AI chưa đủ 80%).
  * `culprit_service == "frontend"` (Dịch vụ Gateway chính ảnh hưởng 100% người dùng).
* **NÂNG LÊN HIGH RISK** (Tự động từ chối): Lệnh không thuộc Whitelist hoặc can thiệp trái phép vào `flagd`.

### 2. Quy Trình Thi Hành 4 Bước (Auto-Remediation Workflow)
1. **Dry-Run Gate**: Thực thi lệnh với cờ `--dry-run=client` hoặc `--dry-run=server`. Nếu trả về lỗi, hủy bỏ quy trình ngay lập tức.
2. **Live Execution**: Thực thi lệnh chính thức lên cụm EKS Kubernetes (`kubectl -n techx-tf3 ...`).
3. **Telemetry Verification**: Kiểm chứng trong 5 phút với 2 cổng đồng thời (Z-Score $|Z| < 2.0$ và Isolation Forest prediction = 1).
4. **Automated Rollback**: Nếu Verification thất bại (sau 5 phút không khôi phục), tự động chạy lệnh Rollback (`rollout undo` hoặc scale lại). Nếu Rollback thất bại, escalate khẩn cấp ra Slack.

---

## 📊 Consequences & Validation

* **Kiểm thử tự động**: Xây dựng bộ test suite `tests/test_safe_self_remediation.py` bao phủ 100% các nhánh Dry-Run Fail, Blast Radius calculation, Replay success flow, và Replay Auto-Rollback flow (Passed 5/5).
* **Audit Trail**: Ghi nhận toàn bộ sự kiện vào `aiops-engine/audit_log.jsonl` và cung cấp API `GET /audit/logs`.
* **Cửa Replay**: Cung cấp API `POST /simulate/remediate_replay` giúp Ban Tổ Chức (BTC) kiểm thử tự động toàn bộ luồng tự dập và lùi tự động.
