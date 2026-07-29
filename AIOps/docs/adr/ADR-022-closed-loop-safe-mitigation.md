# ADR-022: Kiến Trúc Vòng Khép Kín Tự Dập Sự Cố An Toàn (Closed-Loop Safe Mitigation)

- **Trạng thái**: Accepted
- **Ngày lập**: 2026-07-24
- **Tác giả / Ký tên**: Hảo (Leader team AIOps)
- **Phạm vi tác động**: AI Engine (`aiops-engine`), Auto-Healing & Remediation, Kubernetes Cluster `techx-corp-tf3`
- **Mandate liên quan**: MANDATE #22 — Closed-loop Mitigation

---

## 1. Bối cảnh (Context)

Hệ thống AIOps Engine đã phát triển qua nhiều giai đoạn: từ phát hiện bất thường đa chiều (Mandate #07), đến chuẩn hóa độ tin cậy phát hiện (Mandate #15). Tuy nhiên, việc chỉ dừng lại ở **phát hiện** (detect) mà chờ SRE thủ công xử lý dẫn đến MTTR (Mean Time to Resolve) kéo dài 10-50 phút — trong khi khách hàng phải chịu ảnh hưởng trực tiếp.

Mandate #22 yêu cầu nâng cấp lên **vòng khép kín hoàn chỉnh**: detect → safety check → auto-mitigate → verify → rollback/escalate → audit. Nhưng **hành động tự động sai còn tệ hơn không làm gì** — nên hệ phải có phanh (brakes) ở mọi bước.

### Các rủi ro cần giải quyết:
1. **Hành động bừa bãi**: Script chạy lệnh nguy hiểm (`rm`, `delete`) hoặc vượt phạm vi namespace.
2. **Lặp vô hạn**: Cùng một sự cố trigger hàng chục lần remediation gây cascade failure.
3. **False recovery**: Hệ thống báo "đã sửa" nhưng thực tế vẫn lỗi (chỉ kiểm tra 1 chiều).
4. **Không lùi được**: Hành động sai mà không có cơ chế rollback sẽ để lại hậu quả vĩnh viễn.
5. **Không truy vết**: Không biết ai/cái gì đã kích hoạt hành động, làm gì, kết quả ra sao.

---

## 2. Quyết Định Kiến Trúc (Decisions)

### **A. Cổng An Toàn Trước Hành Động (Pre-Action Safety Gate)**

Mỗi hành động tự động phải vượt qua **5 lớp bảo vệ** trước khi thực thi:

| Lớp | Cơ chế | Mã nguồn |
|-----|--------|----------|
| **1. Action Whitelist** | Chỉ cho phép 5 hành động: `scale`, `restart`, `toggle-tf-flag`, `cache-flush`, `breaker-force` | `remediation_handler.validate_action()` |
| **2. Keyword Injection Block** | Chặn đứng lệnh chứa: `rm`, `delete`, `flagd-sync`, `token`, `mkfs`, `bash` | `remediation_handler.validate_action()` |
| **3. Namespace Injection** | Tự động gắn `-n techx-tf3` vào mọi lệnh `kubectl` | `remediation_handler.sanitize_command()` |
| **4. Dry-Run Verification** | Chạy `--dry-run=client` kiểm tra tính hợp lệ trước khi thực thi thật | `remediation_handler.execute_k8s_command(dry_run=True)` |
| **5. Rate-Limiting / Cooldown** | Tối đa **3 lần/incident/giờ** — chống lặp vô hạn | `action_counters` trong `main.py` |

### **B. Phân Luồng Quyết Định Theo Mức Rủi Ro (Risk-Based Routing)**

Không phải mọi hành động đều cần phê duyệt. Hệ thống phân luồng tự động:

* **LOW Risk** (`cache-flush`, `breaker-force`): Tự động thực thi ngay — không cần người bấm nút.
* **MEDIUM Risk** (`scale`, `restart`, `toggle-tf-flag`): Gửi thẻ tương tác Slack với nút `[Approve]` / `[Reject]` — SRE quyết định.
* **HIGH Risk**: Tự động từ chối — chuyển thẳng sang Manual Mode.
* **Bổ sung**: Nếu confidence score < 0.80 thì tự động nâng `LOW` → `MEDIUM` (cần phê duyệt).

### **C. Xác Minh Lai Song Song Sau Hành Động (Hybrid Double-Gate Verification)**

Sau khi thực thi lệnh remediation, hệ thống **không giả định đã sửa xong** mà chạy vòng xác minh 5 phút:

* **Cổng 1 (Z-Score)**: Theo dõi tỷ lệ lỗi gRPC/HTTP của dịch vụ culprit. Yêu cầu `|Z| < 2.0`.
* **Cổng 2 (Isolation Forest ML)**: Quét 18 chỉ số sức khỏe đa chiều (CPU, Memory, Latency, RPS, Error Rate, Kafka Lag...) để phát hiện tác dụng phụ (side-effects) sau remediation.
* **Dampening Window**: Cả 2 cổng phải vượt qua đồng thời trong **5 chu kỳ liên tục (2.5 phút)**.
  * 1 chu kỳ thất bại → reset bộ đếm về 0, đếm lại từ đầu.
  * Hết 5 phút mà không đủ 5 chu kỳ thành công → kích hoạt **Rollback**.

*(Chi tiết kỹ thuật: xem ADR-006)*

### **D. Rollback Tự Động và Escalation (Fail-Safe Branch)**

Khi xác minh thất bại, hệ thống **tự lùi** theo thứ tự ưu tiên:

1. **Rollback Plan**: `kubectl rollout undo deployment/<service>` hoặc scale về replica gốc.
2. **Nếu Rollback thành công**: Ghi log cảnh báo, gửi thông báo Slack, chuyển incident sang Manual Mode.
3. **Nếu Rollback thất bại**: Kích hoạt **CRITICAL Escalation** — báo động khẩn cấp SRE on-call (tương lai: tích hợp PagerDuty).

> **Thiết kế G4 (Blind Escalation)**: Khi hệ thống không chắc chắn hành động nào đúng → **escalate** thay vì rollback mù. Đây là điểm khác biệt với script bấm bừa.

### **E. Nhật Ký Kiểm Toán Bất Biến (Append-Only Audit Log)**

Mọi hành động tự động được ghi lại trong `audit_log.jsonl` với cấu trúc:

```json
{
  "timestamp": "2026-07-24T15:30:00Z",
  "incident_id": "INC-1721824200",
  "culprit_service": "product-catalog",
  "risk_level": "LOW",
  "proposed_action": "restart",
  "command": "kubectl rollout restart deployment/product-catalog -n techx-tf3",
  "dry_run_passed": true,
  "execution_success": true,
  "verify_result": "PASSED",
  "rollback_triggered": false,
  "escalated": false,
  "total_duration_seconds": 180
}
```

Audit log cho phép tái dựng hoàn chỉnh: **ai/cái gì kích hoạt → làm gì → kết quả verify → có lùi không**.

---

## 3. Hệ Quả & Đánh Đổi (Consequences & Trade-offs)

### **Tích cực**:
* **MTTR giảm từ 10-50 phút xuống < 4 phút** (30s detect + 180s verify) cho sự cố Low-Risk.
* **An toàn tuyệt đối**: 5 lớp bảo vệ trước khi act + 2 cổng xác minh sau khi act.
* **Không bao giờ "bấm bừa"**: Risk routing + dry-run + cooldown đảm bảo hành động có kiểm soát.
* **Truy vết 100%**: Audit log append-only cho phép forensic analysis sau sự cố.
* **Có phanh**: Rollback + Escalation đảm bảo hệ không gây thêm thiệt hại.

### **Đánh đổi**:
* **Thời gian xác minh kéo dài**: Tối thiểu 2.5 phút (5 chu kỳ dampening) thay vì kết luận ngay. Đây là đánh đổi có chủ đích để tránh false recovery.
* **Chỉ cover 5 hành động whitelist**: Sự cố ngoài whitelist phải chờ SRE xử lý thủ công. Đây là design-by-choice — an toàn hơn mở rộng bừa.
* **Phụ thuộc Prometheus/ML model**: Nếu Prometheus hoặc model offline, verification gate sẽ fallback gracefully nhưng giảm độ tin cậy.

---

## 4. Luồng Vòng Khép Kín Tổng Thể (End-to-End Closed-Loop Flow)

```
1. DETECT
   └── Prometheus Alertmanager webhook HOẶC ML Isolation Forest scan chủ động
   └── AlertCorrelator gom nhóm alerts theo topology → xác định culprit service

2. SAFETY CHECK (Phanh trước khi act)
   ├── Validate action whitelist
   ├── Block injection keywords (rm, delete, bash...)
   ├── Sanitize namespace (-n techx-tf3)
   ├── Đánh giá Risk & Confidence (LOW→auto, MEDIUM→Slack, HIGH→reject)
   ├── Kiểm tra rate-limit (max 3 lần/incident/giờ)
   └── Dry-run (--dry-run=client)

3. ACT (Thực thi remediation)
   └── Chạy lệnh K8s (scale up, rollout restart...) qua K8s API

4. VERIFY (Xác minh lai 2 cổng — tối đa 5 phút)
   ├── Cổng 1: Z-score error rate < 2.0
   ├── Cổng 2: Isolation Forest 18-feature health check = Normal
   └── Yêu cầu 5 chu kỳ liên tục đạt cả 2 cổng (2.5 phút)

5. ROLLBACK / ESCALATE (Nhánh fail-safe)
   ├── Verify SUCCESS → Đóng incident, ghi audit log ✅
   └── Verify FAIL/TIMEOUT → Kích hoạt Rollback
       ├── Rollback SUCCESS → Cảnh báo Slack, chuyển Manual Mode
       └── Rollback FAIL → CRITICAL Escalation tới SRE on-call 🚨

6. AUDIT
   └── Ghi audit_log.jsonl: trigger → action → verify → rollback (append-only)
```
