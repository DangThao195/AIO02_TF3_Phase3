# Checklist Mandate AIO — TF3 / AIO02

> Đối chiếu **4 mandate BTC dành cho nhóm AIO** (nguồn: `TechX-Corp/xbrain-learners/phase3/mandates`)
> với code + docs thật. 21 mandate tổng, nhưng chỉ **06, 07, 14, 15** áp cho AIO
> (còn lại là CDO: network/scale/security/audit/DR/cost). Cập nhật 2026-07-16.
>
> Kết luận nhanh (**cập nhật 2026-07-16 — đã làm nhiều**): harness eval (#14) + replay (#15) +
> multi-turn agent + các ADR đã XONG (192 test pass, eval/replay/chaos đều PASS). Chỉ còn phần
> **cần cluster thật** (LLM thật, ảnh alert, MTTD before đo thật, deploy chạy liên tục) —
> không phải code.

## Đã hoàn thành đợt này (code + harness + ADR)

| Việc | Trạng thái | Bằng chứng |
|---|---|---|
| #15 replay harness nhận input ngoài | ✅ | `aiops/replay_harness.py` + `scripts/replay.py` + `scenarios/` · report PASS |
| #15 MTTD before/after + masking/busy | ✅ | replay: 30s vs 900s (−97%), masking✅, busy-healthy✅ |
| #14 eval harness 6 chiều | ✅ | `aie/eval_harness.py` + `scripts/eval_ai.py` + `evalsets/` · PASS 100% |
| #14 judge↔người | ✅ | `judge_agreement` 100% trên ca người-gán |
| Multi-turn agent (nền injection multi-turn) | ✅ | `agent_executor.handle(msg, history)` giữ transcript |
| **Vá lỗ hổng thật (eval bắt được)**: injection tiếng Việt + PII số VN liền | ✅ | `input_filter.py` (pattern VN) — nâng cấp bảo mật thật |
| ADR #15/#14/#06 ký tên | ✅ | ADR-009, ADR-010, ADR-011 |
| #07b/#15 doc chạy thật + repro | ✅ | `docs/MANDATE-07b-15-detection-live.md` |

---

## Bản đồ 4 mandate AIO

| Mandate | Hạn | Trụ | Chủ đề | Trạng thái tổng |
|---|---|---|---|---|
| **#06** ai-trust-safety | 18/07 | AIE | AI đáng tin: model thật + guardrail + eval ≥5+5 ca | ⚠️ Một phần |
| **#07** aiops-detection | 7a 18/07 · 7b 25/07 | AIOps | Phát hiện đa tín hiệu + baseline + e2e | ✅ 7a xong · ⚠️ 7b |
| **#14** ai-eval-standard | 25/07 | AIE | Eval chuẩn: grounding/abstention/injection/agency/task-success + judge↔người | ❌ Thiếu nhiều |
| **#15** aiops-detection-standard | 25/07 | AIOps | Detect đáng tin: busy≠broken, masking, chạy liên tục, MTTD before/after | ⚠️ Code đủ · thiếu bằng chứng cluster |

---

## MANDATE #06 — AI Trust & Safety (AIE, hạn 18/07)

| DoD | Trạng thái | Bằng chứng / thiếu |
|---|---|---|
| Model THẬT (bỏ mock) + fallback khi lỗi/chậm | ⚠️ | `aie/gateway.py`+`breaker.py` có fallback đầy đủ; **nhưng LLM thật chưa bật trên cluster** (mock llm) — cần `values-aio-llm.yaml` + secret |
| Không show nội dung sai (eval + chặn/fallback) | ✅ | `aie/guardrail.py` faithfulness 2 tầng, fail-closed |
| Chặn prompt-injection trong review | ✅ | `aie/input_filter.py` |
| Lọc PII | ✅ | `aie/input_filter.py` (redact) |
| Không lộ system prompt | ✅ | `aie/input_filter.py` (system-leak) |
| Trợ lý không tự checkout/xoá giỏ | ✅ | `agent/tools.py` FORBIDDEN_RPCS + confirmation; `test_agent.py` |
| **Eval ≥5 ca faithfulness + ≥5 ca injection, tái tạo được** | ⚠️ | `AI_BASELINE_EVAL.md` có golden set + `test_input_filter.py`; **cần đóng gói thành script eval 1-lệnh ra SỐ** (hiện rải trong test) |
| Bằng chứng chạy thật (ảnh/log mentor bắn) | ❌ | Cần chạy trên cluster + chụp: injection chặn, PII che, "không có thông tin", eval ra số |
| ADR ký tên (model/guardrail/fallback/eval) | ⚠️ | Có ADR-001/002 (provider/caching) trên repo nhóm; cần ADR gộp cho mandate #06 |

**#06 còn thiếu:** bật LLM thật trên cluster · script eval 1-lệnh ra số · ảnh/log bằng chứng chạy thật.

---

## MANDATE #07 — AIOps Detection (AIOps, 7a 18/07 · 7b 25/07)

### #7a — implement + phân tích (chấm như doc) ✅ ĐỦ

| DoD | Trạng thái | Bằng chứng |
|---|---|---|
| Đã implement detector + baseline (link code) | ✅ | `aiops/detector_{burnrate,latency,anomaly,iforest,logtemplate}.py` — 180 test |
| Phân tích ≥3 metrics (vì sao/baseline/ngưỡng/phương pháp) | ✅ | `docs/MANDATE-7a-detection-analysis.md` (4 metric) |
| ADR ký tên | ✅ | `docs/adr/ADR-007-multi-signal-detection.md` |

### #7b — chạy thật + đo đạc (hạn 25/07) ⚠️ CẦN CLUSTER

| DoD | Trạng thái | Thiếu gì |
|---|---|---|
| Ảnh/log detector kêu e2e khi bơm 1 sự cố | ⚠️ | Có chaos harness offline mô phỏng; **cần chạy thật trên cluster + chụp** (bơm qua flagd — dùng chaos-control-panel) |
| Precision/recall/lead-time trên bộ có nhãn | ⚠️ | `chaos_validate.py` đã có khung đo (recall/RCA/false-alarm); **cần chạy trên bộ mentor bơm, số THẬT** |
| Cảnh báo theo mức ảnh hưởng (burn-rate, không spam) | ✅ | `detector_burnrate.py` + `alert_emitter.py` (storm→digest) |
| Mở rộng thêm service | ✅ | forecast/drift phủ thêm product-catalog/recommendation/kafka |

**#7b còn thiếu:** bằng chứng chạy thật trên cluster (ảnh alert + số precision/recall/lead-time thật).

---

## MANDATE #14 — AI Eval Standard (AIE, hạn 25/07) ❌ THIẾU NHIỀU

| DoD | Trạng thái | Thiếu gì |
|---|---|---|
| Script eval ra từng chỉ số, tái tạo từ `repro` | ❌ | Có test rải rác, **chưa có harness eval 1-lệnh** |
| Harness nhận input NGOÀI (lệnh/endpoint) cho cả tóm tắt + copilot | ❌ | Chưa có endpoint/CLI nhận bộ ca từ ngoài |
| Grounding (faithfulness + hallucination rate) | ⚠️ | Logic có (`guardrail.py`); chưa đo ra số chuẩn |
| Abstention (unanswerable → "không có thông tin") | ⚠️ | system_prompt yêu cầu; **chưa có eval đo** |
| Injection-block + false-block rate (review + **multi-turn**) | ⚠️ | Review-injection có; **multi-turn injection chưa** (agent chưa multi-turn) |
| PII / lộ system-prompt = 0 (bar cứng) | ✅ | `input_filter.py` |
| Excessive-agency: ghi trái phép = 0 | ✅ | `agent/tools.py` |
| Task-success (không tính trôi chảy) | ❌ | **CHƯA CÓ eval task-success** — `test_agent.py` chỉ safety |
| Cost/latency before/after | ⚠️ | `cost_meter.py` đo; chưa có bảng before/after |
| **Judge↔người ≥10 ca + báo độ khớp** | ❌ | Chưa có rubric + nhãn người + đo khớp |
| Bộ dữ liệu có nhãn commit repo | ⚠️ | Có golden set nhỏ; cần chuẩn hoá theo yêu cầu #14 |
| ADR ký tên (định nghĩa chỉ số, hiệu chỉnh judge) | ❌ | Chưa có |

**#14 là mandate NẶNG nhất còn thiếu:** harness eval nhận input ngoài + task-success + judge↔người
+ multi-turn injection + bảng before/after + ADR. Đây là chỗ mất điểm lớn nhất của AIO.

---

## MANDATE #15 — AIOps Detection Standard (AIOps, hạn 25/07) ⚠️ CODE ĐỦ, THIẾU BẰNG CHỨNG

| DoD | Trạng thái | Bằng chứng / thiếu |
|---|---|---|
| Bắt đúng: precision/recall/lead-time bộ có nhãn | ⚠️ | `chaos_validate.py` đo được; cần số THẬT trên bộ mentor |
| **Không bị masking** (spike nhiễu không che sự cố nhẹ) | ✅ | chaos exp10 multi-fault tách 2 incident; correlator dedup không nuốt |
| **Không kêu oan khi bận** (lệch khỏi baseline, không mốc tuyệt đối) | ✅ | robust z-score median+MAD per-service; chaos control-panel có ca "tải-cao-healthy" |
| **Chạy liên tục + merged trunk** (không script-1-lần) | ⚠️ | `server.py` có loop `tick()` 30s; **cần deploy làm workload thường trực + merge nhánh chính** |
| Tự sinh incident summary đẩy ra kênh thật | ✅ | `alert_emitter.py` + `rca_assistant` Evidence Pack + Slack |
| **MTTD before/after** | ❌ | Chưa có số MTTD before (mốc cũ) để so — cần đo |
| ADR ký tên (baseline/ngưỡng, summary sinh thế nào) | ✅ | ADR-007 (có thể bổ sung cho #15) |
| Harness replay nhận kịch bản NGOÀI | ⚠️ | `chaos_validate.py` là script nội bộ; **cần cửa replay nhận bộ ca từ ngoài** (endpoint/lệnh) |

**Đạt khi (bộ ẩn):** sự cố thật→kêu ≤1 chu kỳ + summary + severity đúng ✅(logic có) ·
masking→vẫn bắt ✅ · tải-cao-healthy→không kêu ✅. **Thiếu:** MTTD before/after + harness ngoài + chạy liên tục thật.

**#15 còn thiếu:** MTTD before/after (số) · harness replay nhận input ngoài · bằng chứng chạy
liên tục trên cluster (không phải mô phỏng).

---

## Tổng hợp: CÒN THIẾU GÌ (ưu tiên theo hạn)

**🔴 Hạn 25/07 — Mandate #14 (AIE eval) — nặng nhất, thiếu nhiều nhất:**
1. Harness eval 1-lệnh nhận input ngoài (tóm tắt + copilot) → ra số per-case.
2. Task-success eval cho agent (3 intent).
3. Judge↔người ≥10 ca + rubric + độ khớp.
4. Multi-turn injection (cần agent multi-turn trước).
5. Bảng cost/latency before/after + ADR #14.

**🔴 Hạn 25/07 — Mandate #15 (AIOps standard):**
6. MTTD before/after (số thật).
7. Cửa replay nhận kịch bản ngoài (endpoint/lệnh).
8. Bằng chứng detector chạy liên tục trên cluster + merge trunk.

**🟡 Mandate #07b (25/07):** bằng chứng chạy thật e2e (ảnh alert + precision/recall/lead-time thật) — trùng phần lớn với #15.

**🟡 Mandate #06 (đã quá hạn 18/07 nếu chưa nộp):** bật LLM thật + script eval ra số + ảnh/log chạy thật.

---

## Điểm mạnh AIO nên nhấn (đã có, chứng minh được)

- **AIOps code đầy đủ + vững:** 2-tầng detection, self-healing đóng, forecast + drift + G4,
  180 test pass, chaos scoreboard (recall/RCA/false-alarm) — thừa cho #07a, đủ logic cho #15.
- **Chống masking + busy≠broken:** chaos exp10 (multi-fault) + robust z-score per-service +
  control-panel có ca "tải-cao-healthy" → đúng 3 tiêu chí ẩn của #15.
- **Guardrail AIE:** injection/PII/system-leak + excessive-agency = bar cứng của #06/#14 (ghi
  trái phép = 0, lộ PII = 0) đã đạt.

## Khoảng cách lớn nhất (nói thẳng)

Code **mạnh hơn bằng chứng**. Cả #07b/#14/#15 đều đòi **harness nhận input ngoài + chạy thật
trên cluster + số before/after** — đó là thứ đang thiếu, không phải năng lực. Ưu tiên: (1) harness
eval/replay nhận input ngoài, (2) deploy detector chạy liên tục, (3) đo MTTD + precision/recall thật.

---
*Nguồn mandate: đọc read-only qua gh API từ `TechX-Corp/xbrain-learners`. Đối chiếu với code local + repo nhóm.*
