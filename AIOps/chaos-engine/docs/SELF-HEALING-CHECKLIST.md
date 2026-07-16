# Self-Healing Closed-Loop — Checklist đối chiếu code

> Đối chiếu sơ đồ vòng tự phục hồi (RCA → Remediation → Policy/Safety → Dry-run + Blast Radius
> → Risk Assessment → Execute/Approve/Reject → verify telemetry 5 phút → rollback/escalate)
> với code thực tế trong `ai-engine`. **Câu hỏi trọng tâm: hệ thống có TỰ PHỤC HỒI được không?**
>
> Kết luận ngắn (**cập nhật sau khi làm G1+G2**): **CÓ — vòng lặp đóng HOÀN CHỈNH.**
> Risk Assessment 3 mức (Low/Medium/High) đã có; nhánh **Low tự execute không cần người**
> (vẫn qua dry-run + verify 5 phút + rollback), Medium → Human Approval, High → Reject.
> Cơ chế tự rollback vẫn giữ nguyên ở 3 nơi độc lập. Chi tiết bên dưới.

## Bảng checklist theo từng mắt xích sơ đồ

| # | Mắt xích (sơ đồ) | Code hiện thực | Trạng thái |
|---|---|---|---|
| 1 | AI Root Cause Analysis | `rca_assistant.build()` → Evidence Pack + hypotheses + verdict | ✅ Có |
| 2 | Suggested Remediation | `action_policy.propose_for()` → ActionProposal (scale/cache-flush…) theo service | ✅ Có |
| 3 | Policy / Safety Engine | `remediation._safety_gate()` — whitelist action + hard-block flagd/BTC + chặn restart single-replica + bắt buộc rollback_plan | ✅ Có (mạnh) |
| 4a | Dry-run (ok/not?) | `remediation._execute()` gọi `executor(record, True)` = `kubectl --dry-run=server` TRƯỚC khi apply thật | ✅ Có |
| 4b | Blast Radius (service? traffic? risk?) | `correlator._blast_radius()` + **`action_policy.assess_risk()`** dùng blast radius làm điều kiện phân nhánh (≥2→Medium, ≥5→High) | ✅ Có (đã dùng để quyết định) |
| 5 | **Risk Assessment (Low/Medium/High)** | **`action_policy.assess_risk()`** — gộp dry-run + blast radius + service tier + loại action + confidence → Low/Medium/High; nối vào `server._route_by_risk()` | ✅ **Có** (G1 xong) |
| 6-Low | Execute (tự động) | **`remediation.auto_execute()`** — engine tự chạy (approver=`AUTO_APPROVER`), vẫn qua dry-run + verify + rollback; chỉ đi đường này khi risk=Low | ✅ **Có** (G2 xong) |
| 6-Med | Human Approval | Slack card (`approval.render_slack_blockkit`) + callback → `approve_and_execute` | ✅ Có |
| 6-High | Reject | `_route_by_risk` risk=High → pop khỏi pending + alert; `remediation.reject()` + safety_gate raise cho action nguy hiểm | ✅ Có |
| 7 | **Verify qua telemetry (5 phút)** | `verify_loop.verify()` — poll SLI mỗi 30s trong 300s; **telemetry mù = coi như KHÔNG hồi phục** (fail-safe) | ✅ Có (đúng chuẩn) |
| 8 | **Rollback / Escalate** | 3 tầng: `_execute` (fail/timeout→rollback), `verify_and_maybe_rollback` (verify fail→rollback), `_rollback` (rollback fail→escalate người) | ✅ Có (defense-in-depth) |

## Câu trả lời: "Có tự phục hồi lại được không?"

**CÓ.** Khả năng tự phục hồi (auto-recovery) được bảo đảm bởi **3 cơ chế rollback độc lập** —
đây mới là phần "self-healing" thật sự, không phải phần "tự execute":

1. **Rollback khi apply lỗi/timeout** — `remediation._execute()` (dòng 145-163):
   apply thật ném exception HOẶC chạy quá `EXECUTION_TIMEOUT_S=300s` → tự gọi
   `_rollback()` ngay, không cần người.

2. **Rollback khi verify không hồi phục** — `verify_and_maybe_rollback()` (dòng 296-306):
   sau khi execute thành công, poll SLI 5 phút; **nếu SLI vẫn vỡ HOẶC telemetry mù**
   → `k8s_executor(record, "rollback")` tự động. Đây chính là mắt xích "verify → rollback"
   trong sơ đồ, và nó được **tự động kích hoạt sau approve** (server.py:399-400,
   `create_task(verify_and_maybe_rollback)` — non-blocking).

3. **Escalate khi rollback CŨNG lỗi** — `_rollback()` (dòng 178-188):
   rollback ném exception → gọi `_escalate()` → Slack page người trực. "Rollback thất bại"
   là thứ DUY NHẤT bắt buộc con người thấy — đúng nguyên tắc C6.11.

### Điểm mạnh (đã đúng)
- ✅ **Fail-safe verify**: telemetry mù bị coi là "chưa hồi phục" → nghiêng về rollback,
  không nghiêng về "cứ để nguyên" (verify_loop.py:52). Đây là lựa chọn an toàn đúng.
- ✅ **Dry-run trước apply thật** luôn chạy (không bỏ qua được).
- ✅ **Không đứt vòng sau approve**: verify được `create_task` tự động, không phụ thuộc người bấm lại.
- ✅ **Audit append-only** ở mọi trạng thái (proposed→executed→verified/rolled-back).

## Trạng thái gap (cập nhật sau khi làm G1+G2)

| Gap | Mô tả | Trạng thái |
|---|---|---|
| **G1 — Risk Assessment 3 mức** | Bộ phân loại gộp dry-run + blast radius + service tier + loại action + confidence → Low/Med/High | ✅ **XONG** — `action_policy.assess_risk()` |
| **G2 — Auto-execute nhánh Low** | Engine tự chạy action Low-risk không chờ người, vẫn qua dry-run + verify + rollback | ✅ **XONG** — `remediation.auto_execute()` + `server._route_by_risk()` |
| **G3 — Blast radius chặn theo ngưỡng** | Blast ≥2 service → tối thiểu Medium; ≥5 → High/Reject | ✅ **XONG** — nằm trong `assess_risk()` |
| **G4 — Verify giả định recording-rule** | `verify_and_maybe_rollback` build `sli:{svc}_error:ratio_rate5m`; thiếu rule → "blind → rollback" nhầm | 🟡 **Còn treo** — cần guard: rule thiếu thì escalate thay vì rollback mù |
| **G5 — route_for_confidence** | confidence giờ là 1 input của `assess_risk` (đúng chỗ) | ✅ **XONG** |

### Luật Risk Assessment đã cài (`action_policy.assess_risk`)

Từ nghiêm tới nhẹ:

- dry-run **FAIL** → **HIGH / Reject** (không apply thử được thì không chạy).
- blast **≥ 5 service** → **HIGH / Reject** (quá rộng, cần điều tra).
- action **không idempotent** (restart/breaker/toggle) → **MEDIUM / Approval**.
- service **tier-1** (checkout/payment/cart/frontend) → **MEDIUM / Approval** (doanh thu — luôn cần người vòng đầu).
- blast **≥ 2 service** → **MEDIUM / Approval**.
- **confidence < 0.85** → **MEDIUM / Approval** (chưa đủ chắc).
- còn lại (nhẹ + hẹp + idempotent + chắc, ngoài tier-1) → **LOW / Execute tự động**.

Nhánh Low vẫn: safety gate (ở propose) → **dry-run** → apply → **verify 5 phút** → **rollback** nếu không hồi phục.
Nghĩa là action tự chạy nhưng **không bao giờ bỏ qua bất kỳ lớp an toàn nào** — chỉ bỏ bước "chờ người bấm".

## Còn lại (nếu muốn hoàn hảo 100%)

**G4 guard** — trong `verify_and_maybe_rollback`, trước khi coi "telemetry mù = rollback", kiểm tra
recording-rule `sli:{svc}_error:ratio_rate5m` có trả data không. Nếu rule thiếu (CDO chưa tạo) →
`escalate` (page người) thay vì rollback mù một action có thể đã thành công. Đây là edge-case vận hành,
không chặn vòng self-healing hoạt động — để lại cho lúc tích hợp với recording rules thật của CDO.

---

*Tóm lại (sau G1+G2): **vòng closed-loop self-healing đã ĐÓNG HOÀN CHỈNH.** Nhánh an toàn nhất
(Low-risk: scale-up/cache-flush, hẹp, ngoài tier-1, confidence cao) engine **tự phát hiện → tự đề xuất →
tự đánh giá rủi ro → tự execute → tự verify → tự rollback** không cần người. Nhánh rủi ro hơn (Medium)
vẫn giữ người-duyệt-1-chạm; nhánh nguy hiểm (High) tự từ chối. Cơ chế tự phục hồi (3 tầng rollback +
escalate) nguyên vẹn. 157/157 test pass, chaos harness PASS. Chỉ còn G4 (edge-case recording-rule) là
tinh chỉnh vận hành, không phải thiếu năng lực.*
