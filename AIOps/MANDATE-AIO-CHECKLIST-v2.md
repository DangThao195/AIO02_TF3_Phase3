# Checklist Mandate AIO (v2) — cập nhật 2026-07-21

> Cập nhật sau khi BTC thả **MANDATE #22 (closed-loop mitigation)** ngày 20/07. Đối chiếu
> **5 mandate AIO** (06, 07, 14, 15, **22**) với code thật ở 2 nơi:
> - `AIOps/chaos-engine/ai-engine` — engine detect→RCA→remediation (code closed-loop).
> - `AIE2/shopping-copilot` — copilot + eval (nhánh feature/copilot: eval 20/20 llm-judge).
>
> Kết luận nhanh: **#22 gần đủ nhất** (vòng closed-loop đã code sẵn từ G1/G2 + self-healing) —
> chỉ cần chứng minh e2e 1 loại sự cố + 1 rollback trên cluster. **AIE (06/14) nhóm đã mạnh**
> (eval 20/20, llm-judge thật). Phần còn thiếu chung: **bằng chứng chạy thật trên cluster**.

---

## Bản đồ 5 mandate AIO

| Mandate | Hạn | Trụ | Chủ đề | Trạng thái |
|---|---|---|---|---|
| **#06** ai-trust-safety | 18/07 | AIE | model thật + guardrail + eval 5+5 | ✅ eval nhóm 20/20 · ⚠️ LLM thật cluster |
| **#07** aiops-detection | 7a 18/07 · 7b 25/07 | AIOps | phát hiện đa tín hiệu + baseline | ✅ 7a · ⚠️ 7b cluster |
| **#14** ai-eval-standard | 25/07 | AIE | eval chuẩn + judge↔người | ✅ harness + llm-judge · ⚠️ before/after |
| **#15** aiops-detection-standard | 25/07 | AIOps | busy≠broken + masking + chạy liên tục | ✅ replay harness · ⚠️ cluster |
| **#22** closed-loop-mitigation | 25/07 | AIOps | **tự dập an toàn: safety→act→verify→rollback→audit** | ✅ **code đủ** · ⚠️ e2e cluster |

---

## ⭐ MANDATE #22 — Closed-loop mitigation (MỚI, hạn 25/07)

Đây là mandate mới nhất. Điểm mừng: **vòng closed-loop đã được code sẵn** (từ G1/G2 + self-healing
làm các đợt trước). #22 chỉ đòi chứng minh e2e 1 loại sự cố + 1 rollback.

| DoD #22 | Trạng thái | Bằng chứng (code đã có) |
|---|---|---|
| **1. Safe trước act** (dry-run + blast-radius + cooldown) | ✅ | `remediation._safety_gate` (whitelist, hard-block flagd, single-replica) + `action_policy.assess_risk` (blast-radius) + dry-run + rate-limit (cooldown 3/incident/h) |
| **2. Tự dập không cần người** (nhánh Low) | ✅ | `remediation.auto_execute` + `server._route_by_risk` (risk Low → tự chạy) |
| **3. Verify bằng telemetry thật** | ✅ | `verify_loop.verify` (poll SLI 5', không suy đoán) |
| **4. Rollback khi verify fail** | ✅ | `verify_and_maybe_rollback`: fail→rollback; **blind→escalate** (G4, không rollback mù) |
| **5. Audit log truy được** | ✅ | `audit_log` append-only: trigger→action→verify→rollback |
| **Cửa replay nhận kịch bản ngoài** | ✅ | `replay_harness.py` + `scripts/replay.py` (đã làm cho #15, dùng chung) |
| **Do AIOps đội điều khiển (không phải HPA/k8s tự restart)** | ✅ | Hành động kích hoạt từ detector của đội → correlator → risk → auto_execute (chuỗi của đội) |

**#22 còn thiếu (cần cluster, không phải code):**
- Chọn 1 loại sự cố (vd `productCatalogFailure` qua flagd) → chạy e2e THẬT trên cluster, chụp:
  detect → auto-execute → verify → (SLI hồi phục).
- Ép 1 hành động sai (hoặc verify fail) → chụp hệ **tự rollback/escalate** trong log.
- Audit log cho lần đó + MTTR before/after.
- ADR #22 ký tên.

> **Đây là mandate AIO đội có lợi thế nhất** — code vòng closed-loop hoàn chỉnh sẵn (192 test),
> chỉ cần 1 buổi trên cluster để quay bằng chứng. `chaos-control-panel.html` bơm lỗi qua flagd.

---

## MANDATE #06 — AI Trust & Safety (AIE)

| DoD | Trạng thái | Bằng chứng |
|---|---|---|
| Model thật + fallback | ⚠️ | Gateway fallback đủ; copilot eval chạy trên **llama3-70b thật** (judge) — nhưng answer path cần xác nhận LLM thật trên cluster |
| Không show sai (eval + chặn) | ✅ | shopping-copilot eval: factuality 5/5 |
| Injection/PII/leak | ✅ | copilot guardrails: prompt_injection 7/7, pii_leakage 5/5 (100%) |
| Trợ lý không tự checkout | ✅ | `guardrails/confirmation.py` + `tool_validator.py` |
| **Eval ≥5+5 tái tạo** | ✅ | `src/evaluation/` baseline 20 ca + `llm_judge.py` + report 20/20 |
| ADR ký tên | ✅ | `docs/ADR/ADR1_Trust_And_Safety_Guardrails.md` |

**#06 gần đủ** — chỉ cần ảnh/log mentor bắn thật trên cluster.

## MANDATE #07 — AIOps Detection (7a ✅ / 7b ⚠️)

- **7a ✅**: `MANDATE-7a-detection-analysis.md` + ADR-007 (đã xong đợt trước).
- **7b ⚠️**: cần chạy thật + số precision/recall/lead-time trên cluster. Doc + repro sẵn:
  `MANDATE-07b-15-detection-live.md`.

## MANDATE #14 — AI Eval Standard (AIE)

| DoD | Trạng thái | Bằng chứng |
|---|---|---|
| Harness nhận input ngoài (tóm tắt + copilot) | ✅ | copilot `eval_baselines.py` + engine `eval_harness.py` |
| Grounding/abstention/injection/PII/agency/task | ✅ | copilot per-kind metrics + engine 6 chiều |
| **Judge↔người + rubric** | ✅ | copilot `llm_judge.py` (llama3-70b) + `EVAL_BIAS_GUARD.md` |
| Multi-turn injection | ✅ | engine `agent_executor` multi-turn + copilot |
| Cost/latency before/after | ⚠️ | có avg_latency (5.7s judge); cần bảng before/after tính năng |
| ADR | ✅ | ADR-010 (engine) + copilot ADR |

**#14 nhóm mạnh** — 2 harness (copilot + engine), llm-judge thật, bias guard. Thiếu: before/after.

## MANDATE #15 — AIOps Detection Standard (AIOps)

| DoD | Trạng thái | Bằng chứng |
|---|---|---|
| Precision/recall/lead-time bộ nhãn | ✅ | `replay_harness.py` (recall/precision/MTTD) |
| Không masking | ✅ | replay scenario masking → vẫn bắt sự cố nhẹ |
| Không kêu oan khi bận | ✅ | confidence gate 0.7 → busy-healthy 0 incident |
| Chạy liên tục + trunk | ⚠️ | `server.tick` loop có; cần deploy thường trực + merge |
| Incident summary tự sinh | ✅ | `alert_emitter` + Evidence Pack |
| MTTD before/after | ⚠️ | after đo được (30s); before cần mốc mentor |
| Cửa replay ngoài | ✅ | `scripts/replay.py` |
| ADR | ✅ | ADR-009 |

---

## Tổng hợp: CÒN THIẾU (ưu tiên hạn 25/07)

**🔴 Cùng hạn 25/07, cùng cần cluster — làm 1 buổi được nhiều mandate:**
1. **#22**: bơm 1 flag → quay e2e tự dập + 1 rollback + audit log. ← *lợi thế nhất, code sẵn*
2. **#15/#07b**: cùng buổi đó đo precision/recall/lead-time + MTTD thật trên cluster.
3. **#14**: bảng cost/latency before/after.
4. **#06**: ảnh mentor bắn injection/PII trên cluster.

**Các ADR còn cần ký:** ADR-#22 (closed-loop). Các ADR khác đã có.

## Điểm mạnh AIO (nói khi trình bày)

- **#22 closed-loop code hoàn chỉnh** — safety gate + auto-execute + verify + rollback (blind→escalate) + audit, 192 test. Đây là mandate khó nhất mà đội đã có sẵn nền.
- **AIE eval production** — copilot 20/20 với llm-judge thật (llama3-70b), per-kind metrics, bias guard.
- **2 cửa replay/eval nhận input ngoài** — chịu được bộ ca ẩn BTC bơm (#14/#15/#22).
- **Fail-safe có phân biệt (G4)** — blind → escalate, không rollback mù. Đúng tinh thần "phanh" của #22.

## Khoảng cách lớn nhất

Vẫn là: **code mạnh hơn bằng chứng**. Cả 5 mandate hạn 25/07 đều đòi **chạy thật trên cluster**.
Một buổi trên `techx-corp-tf3` (đã ACTIVE) với `chaos-control-panel` bơm lỗi → quay được bằng
chứng cho #22 + #15 + #07b cùng lúc. Đó là việc cần làm, không phải code.

---
*Nguồn: mandate đọc read-only từ `TechX-Corp/xbrain-learners`. Code: chaos-engine/ai-engine + AIE2/shopping-copilot (worktree feature/copilot).*
