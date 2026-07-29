# C6 — Remediation & Audit Trail Contract

| Trường | Giá trị |
|---|---|
| Version | 1.0.0 |
| Producer | **AIO02** (Remediation module trong AI engine) |
| Consumer | **CDO giữ trụ Auditability** (luân phiên hằng tuần) + hội đồng chấm (mọi quyết định truy được về người — RULES §7, §8) |
| Trạng thái | Draft — chờ CDO review |

## Mục đích

AI engine được phép **gợi ý và (có phê duyệt) thực thi** hành động khắc phục. Đây là chỗ
nguy hiểm nhất của AIOps: hành động tự động mà không truy được về người = vi phạm luật
chơi Phase 3. Contract này chốt: hành động nào được phép, ai duyệt, và mọi bước để lại
dấu vết gì cho trụ Auditability.

Nguyên tắc thiết kế (theo pattern production về agent safety): **validation gate trước
mọi hành động, human escalation cho hành động rủi ro, không có vòng retry vô hạn.**

---

## INPUT — thứ Remediation module cần

| Input | Nguồn |
|---|---|
| Alert/incident đang mở | C2 |
| Evidence Pack | C3 |
| **Action catalog** — danh mục hành động được phép (bảng dưới) | AIO đề xuất, **cả TF duyệt** — thêm action mới = sửa contract này + ADR |
| Approval | Người trực (qua nút/lệnh trong kênh chat, định danh rõ ai bấm) |

### Action catalog v1 (whitelist — ngoài danh sách này engine không được đề xuất thực thi)

| Action | Ví dụ | Cấp phê duyệt |
|---|---|---|
| `scale` | Tăng replicas một deployment trong giới hạn min/max ghi sẵn | Người trực approve |
| `restart` | Rollout restart 1 deployment | Người trực approve |
| `toggle-tf-flag` | Bật/tắt **flag do TF tự thêm** (vd tắt render tóm tắt AI) | Người trực approve |
| `cache-flush` | Xóa cache tóm tắt AI | Người trực approve |
| `breaker-force` | Ép mở/đóng circuit breaker AI gateway | Người trực approve |
| Mọi thứ khác (sửa config hạ tầng, đổi DB, network...) | — | **Không qua engine.** Người làm tay + ADR như thường |

**Cấm tuyệt đối (hard-block trong code, không chỉ trong văn bản):** mọi hành động đụng tới
`flagd` config của BTC, các flag incident (`llmRateLimitError`, `llmInaccurateResponse`, ...),
hook OpenFeature trong service lõi — RULES §8, vi phạm = disqualify cả TF.

## OUTPUT — thứ trụ Auditability nhận

### 1. Remediation Record — mỗi hành động một bản ghi

Ghi vào 2 nơi: OpenSearch index `ai-engine-audit-*` (query được) và file
`TF3/incidents/<incident_id>/actions.jsonl` (bền, vào git).

```json
{
  "schema_version": "1.0",
  "action_id": "TF3-ACT-20260713-0007",
  "incident_id": "TF3-20260713-0042",
  "proposed_at": "2026-07-13T09:47:02Z",
  "proposed_by": "ai-engine/remediation@v1.2",
  "action": "scale",
  "target": "deployment/payment",
  "parameters": { "replicas_from": 2, "replicas_to": 4, "max_allowed": 6 },
  "rationale": "p99 payment x8, CPU throttling 85%, evidence pack H1",
  "risk_note": "tăng cost ~$0.4/h; rollback = scale về 2",
  "approval": {
    "decision": "approved",
    "by": "<tên người trực — con người, định danh thật>",
    "at": "2026-07-13T09:48:11Z",
    "channel": "chat-button"
  },
  "execution": {
    "started_at": "2026-07-13T09:48:12Z",
    "finished_at": "2026-07-13T09:48:40Z",
    "result": "success",
    "verification": "p99 payment về baseline sau 4 phút (promql: ...)",
    "rollback_plan": "kubectl scale deploy/payment --replicas=2"
  }
}
```

### 2. Quy tắc bất biến (trụ Auditability kiểm tra được bằng máy)

1. **Không có execution nào thiếu approval của con người** — `approval.by` phải là
   người, không bao giờ là service account. Query kiểm tra: đếm record có
   `execution.result` mà `approval.decision != "approved"` → phải luôn = 0.
2. **Mọi record có rollback_plan trước khi thực thi** (không có = engine từ chối chạy).
3. **Idempotent + timeout:** action chạy quá 5 phút → tự hủy, ghi `result: "timeout"`.
4. **Rate limit:** tối đa 3 action được thực thi / incident / giờ — quá là dấu hiệu
   engine loạn, tự khóa lại chờ người.
5. Record là **append-only**: không sửa, không xóa; sai thì ghi record đính chính trỏ tới
   `action_id` cũ.

### 3. Báo cáo tuần cho trụ Auditability (1 mục trong Ops Review)

- Tổng số action đề xuất / được duyệt / bị từ chối / thất bại.
- 100% action có approval + rollback plan? (invariant check tự động, xuất pass/fail).
- Action bị từ chối nhiều nhất → tín hiệu chỉnh catalog hoặc chỉnh engine.

## Nghĩa vụ của consumer (CDO Auditability)

- Mỗi tuần chạy invariant check (AIO cung cấp script `TF3/scripts/audit-check.sh`) và
  xác nhận trong Ops Review — đây chính là bằng chứng "truy được về người" khi hội đồng vặn.
- Review action catalog khi AIO đề xuất thêm action mới.

## Failure modes

| Tình huống | Hành vi |
|---|---|
| Kênh approval chết | Engine không thực thi gì cả (fail-closed), chỉ còn chế độ gợi ý trong dashboard |
| Action thực thi thất bại giữa chừng | Chạy rollback_plan tự động, ghi cả hai vào record, page người trực |
| Nghi ngờ engine đề xuất bậy liên tục | Bất kỳ ai trong TF được phép bật `remediation_disabled` (flag TF tự thêm) — engine về chế độ chỉ-gợi-ý; ghi ADR |

## Tiêu chí nghiệm thu

- [ ] Diễn tập 1 action `scale` end-to-end: đề xuất → approve → thực thi → verify → record đầy đủ ở cả OpenSearch lẫn git.
- [ ] Diễn tập từ chối: record `rejected` được ghi, không có gì được thực thi.
- [ ] Hard-block với target `flagd`/flag BTC được test (engine từ chối ngay ở validation).
- [ ] `audit-check.sh` chạy pass trên dữ liệu diễn tập.
- [ ] ADR ký tên bởi AIO02 + CDO giữ Auditability tuần hiện tại.
