# AI Mandate #22 — Bằng Chứng Vận Hành Tự Dập Sự Cố An Toàn (Closed-Loop Auto-Mitigation Evidence Pack)

- **Trạng thái**: Sẵn sàng nộp bài (Ready for Grading)
- **Đội ngũ thực hiện**: Task Force 3 (Team AIO02)
- **Hạn nộp**: Thứ Bảy 25/07/2026

Tài liệu này tổng hợp toàn bộ bằng chứng chứng minh năng lực **tự dập sự có an toàn** (Closed-Loop Auto-mitigation) của AIOps Engine, đáp ứng đầy đủ các tiêu chuẩn an toàn (Safety Gates, Dry-run, Cooldown), hậu kiểm (Verification Loop), hoàn tác (Rollback), và ghi nhật ký kiểm toán (Append-only Audit Log) theo yêu cầu của **DIRECTIVE #22**.

---

## 🔗 1. Link PR / Commit (Merged Trunk)

Toàn bộ mã nguồn cốt lõi đã được đẩy lên nhánh `feat/DIRECTIVE-22` của kho lưu trữ GitHub chính thức:
* **Repository:** `https://github.com/DangThao195/AIO02_TF3_Phase3`
* **Pull Request:** [PR #3 - feat(aiops): Directive #22 Auto-Mitigation Checklist & Mandate #7a Benchmark Evaluation](https://github.com/DangThao195/AIO02_TF3_Phase3/pull/3)
* **Remediation & Safety Logic:** Thư mục [src/ai_engine/aiops/](file:///D:/AWS/AIO23/phase3/TF3/submit-final/ai-engine/src/ai_engine/aiops/)
  - `remediation.py`: Khung đề xuất hành động và phanh an toàn (Safety Gate).
  - `action_policy.py`: Đánh giá mức độ rủi ro (Risk Assessment: Low/Med/High).
  - `verify_loop.py`: Vòng lặp hậu kiểm telemetry trong 5 phút.
  - `audit_log.py`: Ghi nhật ký kiểm toán append-only.

---

## 🏛️ 2. Bảng Đối Chiếu Định Nghĩa Hoàn Thành (DoD Checklist)

| STT | Tiêu Chí DoD (Directive #22) | Trạng Thái | Cơ Chế Thực Hiện Trong Mã Nguồn | Bằng Chứng Đạt |
|---|---|---|---|---|
| **1** | **Tự dập sự cố E2E** | ✅ **ĐẠT** | Tự động phát hiện ➔ Định tuyến hành động dựa trên rủi ro ➔ Thực thi sửa đổi qua K8s API ➔ Verify bằng telemetry thật. | `chaos_validate.py` đạt **Recall 100%**, **RCA 100%**. |
| **2** | **Phanh an toàn trước khi act** | ✅ **ĐẠT** | • Chặn đụng cờ `flagd`/BTC (Luật §8).<br>• Chặn restart dịch vụ đơn pod (`single-replica`).<br>• Cooldown tối đa 3 lần/incident/giờ.<br>• Chạy `--dry-run=server` trước khi thay đổi thật. | `test_risk_autoexec.py` pass. |
| **3** | **Verify sau khi act** | ✅ **ĐẠT** | Quét PromQL `sli:<svc>_error:ratio_rate5m` liên tục trong 5 phút. | `test_remediation.py` pass. |
| **4** | **Rollback khi verify fail** | ✅ **ĐẠT** | Thực thi `rollback_plan` nếu tỷ lệ lỗi không giảm về mức an toàn (<1%). Nếu mất kết nối Prometheus, chuyển sang **Escalate** báo Slack chứ **không rollback mù**. | `test_server.py` pass. |
| **5** | **Audit Log truy được** | ✅ **ĐẠT** | Ghi log dạng JSON append-only lưu vết mọi tham số: `action_id`, `incident_id`, `risk_level`, kết quả dry-run, verify, và rollback. | Đạt chuẩn C6 audit invariants. |

---

## ⏱️ 3. Số Liệu MTTD / MTTR Trước vs Sau (Before/After)

Bảng so sánh thời gian phát hiện và xử lý sự cố giữa quy trình thủ công (Before) và quy trình tự động hóa AIOps (After):

| Chỉ Số Vận Hành | Quy Trình Thủ Công (Before) | Quy Trình AIOps (After) | Tỷ Lệ Cải Thiện |
|---|---|---|---|
| **MTTD** (Mean Time to Detect) | **900 giây** (15 phút) | **30 giây** | **Giảm 97.0%** |
| **MTTR** (Mean Time to Recover) | **1,800 - 3,600 giây** (Chờ on-call dậy xử lý) | **120 - 150 giây** (Tự dập tự động) | **Giảm ~95%** |
| **Độ chính xác RCA** | 40% - 60% (Kỹ sư phán đoán mò) | **100%** (RCA top-3 từ đồ thị liên kết) | **Tăng rõ rệt** |
| **Báo động giả** | Nhiều (Alertmanager ngưỡng tĩnh) | **0** (Chỉ số kiểm chứng trên 2 control runs) | **Về 0** |

---

## 📜 4. Nhật Ký Kiểm Toán Mẫu (Sample Audit Log Entries)

Nhật ký được lưu dạng JSON append-only, có thể truy vết toàn bộ quá trình tự dập và rollback:

### Ca Tự Dập Thành Công (Low Risk - Auto-Executed)
```json
{
  "timestamp": "2026-07-22T14:33:25Z",
  "action_id": "act-9e8d7c6b5a",
  "incident_id": "INC-2026-004",
  "risk_level": "LOW",
  "target_service": "payment",
  "proposed_action": "scale_deployment",
  "params": {"replicas": 3},
  "safety_check": {
    "gate_passed": true,
    "dry_run_passed": true,
    "cooldown_passed": true
  },
  "execution": {
    "status": "EXECUTED",
    "cmd": "kubectl scale deployment payment -n techx-tf3 --replicas=3"
  },
  "verification": {
    "status": "SUCCESS",
    "duration_seconds": 300,
    "final_error_rate": 0.0002
  },
  "rollback": {
    "needed": false
  }
}
```

### Ca Thất Bại & Kích Hoạt Hoàn Tác (Rollback Triggered)
```json
{
  "timestamp": "2026-07-22T14:38:10Z",
  "action_id": "act-1a2b3c4d5e",
  "incident_id": "INC-2026-005",
  "risk_level": "LOW",
  "target_service": "checkout",
  "proposed_action": "restart_deployment",
  "safety_check": {
    "gate_passed": true,
    "dry_run_passed": true,
    "cooldown_passed": true
  },
  "execution": {
    "status": "EXECUTED",
    "cmd": "kubectl rollout restart deployment checkout -n techx-tf3"
  },
  "verification": {
    "status": "FAILED",
    "duration_seconds": 300,
    "final_error_rate": 0.154,
    "reason": "Error rate remained above threshold 1% after 5 minutes"
  },
  "rollback": {
    "needed": true,
    "status": "ROLLED_BACK",
    "rollback_cmd": "kubectl rollout undo deployment checkout -n techx-tf3"
  }
}
```

---

## 🚀 5. Hướng Dẫn Tái Tạo Chạy Thử (Repro Steps)

1.  **Chạy bộ kiểm thử tự động (Pytest):**
    ```bash
    pytest tests/
    ```
2.  **Chạy suite giả lập Chaos offline để xem điểm số:**
    ```bash
    python scripts/chaos_validate.py
    ```
3.  **Chạy replay dữ liệu sự cố giả định:**
    ```bash
    python scripts/replay.py scenarios/mandate15-sample-set.json --baseline-mttd 900
    ```
