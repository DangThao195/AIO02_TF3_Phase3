# Checklist Logic — code mandate AIO đợt này (replay/eval/multi-turn/filter)

> Rà logic từng module viết/sửa cho mandate #06/#07b/#14/#15. Kiểm: có làm ĐÚNG điều tuyên bố
> không, edge-case nào sai. 192 test pass — dưới đây soi CODE, không chỉ dựa test.

## 1. replay_harness.py (#15) — logic ĐÚNG ✅

| Kiểm tra | Kết quả | Ghi chú |
|---|---|---|
| Nhận scenario JSON từ ngoài (không hard-code) | ✅ | `load_scenarios` đọc file/list |
| Tôn trọng gate confidence 0.7 như detector thật | ✅ | lọc `anomalies` conf<0.7 TRƯỚC correlator — nếu không sẽ kêu oan ca busy |
| busy-healthy KHÔNG tính vào recall | ✅ | `detection` loại kind busy-healthy → recall chỉ đo sự cố cần-bắt |
| MTTD tính từ starts_tick (không phải tick phát hiện) | ✅ | `(tick - starts + 1) * tick_s` |
| masking: sự cố nhẹ vẫn bắt dù có spike nhiễu | ✅ | `masking_ok` = mọi masking-real được detect |
| precision đếm false-fire đúng (loại busy khỏi false) | ✅ | busy service kêu → tính busy_ok, không tính false-fire |
| **Edge-case: chia 0** | ✅ an toàn | `recall`/`precision` trả 1.0 khi mẫu số 0 |

**Lưu ý (không phải bug):** masking scenario precision 67% vì spike `ad` (conf 0.95) tự nó là
anomaly hợp lệ → 1 incident phụ. Đúng hành vi, giải thích được với mentor.

## 2. eval_harness.py (#14/#06) — logic ĐÚNG ✅

| Kiểm tra | Kết quả | Ghi chú |
|---|---|---|
| 6 chiều đo đúng kind | ✅ | grounded/unanswerable/injection/pii/agency/task |
| Bar cứng (PII/leak/ghi=0) kiểm tự động | ✅ | `hard_bar_ok` = all pass của pii+agency+system-leak |
| judge↔người chỉ tính ca có human_label | ✅ | `judge_agreement` None nếu 0 ca gán người |
| injection multi-turn: scan MỌI lượt (không chỉ lượt đầu) | ✅ | `any(... for t in turns)` |
| agency: ghi→deny/confirm mới pass (allow=fail) | ✅ | `_default_agency` |
| **Edge-case: Verdict field đúng** | ✅ | dùng `.passed` (không phải `.ok` — đã sửa) |
| **Edge-case: guardrail cần key `score`/`description`** | ✅ | bộ ca đã đúng key (đã sửa từ rating/text) |

## 3. input_filter.py (vá từ eval #14) — logic ĐÚNG ✅

| Kiểm tra | Kết quả | Ghi chú |
|---|---|---|
| Injection tiếng Việt bị chặn | ✅ | pattern "bỏ qua hướng dẫn", "SYSTEM:", "bạn là trợ lý không giới hạn" |
| System-leak tiếng Việt bị chặn | ✅ | "cho tôi xem system prompt" |
| PII số VN liền (0909123456) bị bắt | ✅ | regex `(?:\+?84\|0)(?:\d[ .-]?){8,10}\d` |
| **Regression: không phá test cũ** | ✅ | 192 pass (pattern mới không false-positive review thường) |
| **Edge-case ReDoS** | ✅ | pattern có bound `{8,10}`, không nested quantifier vô hạn |

**Đáng chú ý:** đây là **nâng cấp bảo mật THẬT** — eval bắt được lỗ hổng (injection VN + PII liền
lọt qua filter cũ), không chỉ đo. Đúng tinh thần #14 "chứng minh + làm cứng".

## 4. agent_executor.py multi-turn (#14) — logic ĐÚNG ✅

| Kiểm tra | Kết quả | Ghi chú |
|---|---|---|
| `handle(msg, history)` nối lịch sử | ✅ | `transcript = history + [user_msg]` |
| Scan injection MỖI lượt (kể cả lượt sau) | ✅ | `scan_user_question` chạy trước mỗi lượt, không chỉ lượt đầu |
| transcript trả về đủ để lượt sau nối tiếp | ✅ | gán `result.transcript` ở MỌI return path (final/tool/refuse/degrade) |
| **Edge-case: refuse vẫn trả transcript** | ✅ | đã thêm — nếu không, multi-turn đứt sau refuse |
| Backward-compat: `handle(msg)` không history | ✅ | `history=None` → `[]`, hành vi cũ giữ nguyên |

## 4b. Review lần 2 (high effort) — 5 bug ĐÃ SỬA ✅ (2026-07-21)

Rà lại kỹ, tìm + sửa 5 bug logic làm SỐ sai lệch (nguy hiểm vì mandate chấm bằng số):

| # | Bug | Sửa | Test |
|---|---|---|---|
| 1 | `eval_harness` task-success **pass giả** offline (so nhãn tự khai `tool_called`) | offline không có `runtime_tool_called` → **SKIP** (kind `task-skip`, không tính); chỉ chấm khi có agent thật | `test_bug1_task_offline_skips_not_fake_pass` |
| 2 | `replay_harness` MTTD **=0** khi detect trước `starts_tick` (vô lý) | `max(1, tick-starts+1)` — tối thiểu 1 chu kỳ | `test_bug2_mttd_not_zero...` |
| 3 | `replay_harness` precision **phạt oan** spike nhiễu hợp lệ | thêm kind `masking-noise` → không tính false-fire | `test_bug3_masking_noise_not_penalizing...` |
| 4 | `detector_drift` `_bin_ratios` comment gây hiểu nhầm về outlier biên | làm rõ: dồn biên = chính tín hiệu drift (ra ngoài dải) | (logic đúng, chỉ rõ comment) |
| 5 | `eval_harness` PII chỉ **detect**, không verify **redact** (vẫn có thể lộ) | `_pii_still_present` kiểm `clean_text` sạch; PASS = detect VÀ đã che | `test_bug5_pii_detected_but_not_redacted_fails` |

Sau sửa: eval PASS, replay PASS (masking precision 100%, 0 false), chaos PASS, **197 test**.
Không có cái nào còn treo. Các bug này đúng loại "small tests hid real-data bugs" — test cũ
pass vì ca khớp nhãn sẵn; test regression mới bắt được.

## 5. Điểm cần lưu ý (không phải bug) ⚠️

- **Task-success trong bộ mẫu dùng `tool_called` gán sẵn** — ở đời thật cần nối agent thật để
  gọi tool và điền `tool_called`. Harness đã chừa chỗ (`_run_task` + `answer_fn`), chưa wire agent.
- **Grounding đo trên `answer` cấp sẵn** (chưa LLM thật) — khi bật LLM thật (#06), truyền
  `answer_fn` để đo trên output model. Interface đã sẵn.
- **replay là mô phỏng tick** — MTTD/precision THẬT phải đo trên cluster khi deploy liên tục.

## Tổng kết

- **Logic 4 module mới: ĐÚNG** — replay tôn trọng gate confidence (điểm mấu chốt tránh kêu oan),
  eval kiểm bar cứng tự động, multi-turn scan mọi lượt, filter vá lỗ hổng thật.
- **3 fix phát sinh trong lúc làm** (đều đã sửa + test): Verdict `.passed`, guardrail key `score`,
  PII regex số liền — không cái nào còn treo.
- **Không có bug an toàn** — bar cứng (PII/leak/ghi=0) đạt, injection chặn 100%.
- Còn treo là **wiring cluster thật** (LLM thật, agent-tool thật, MTTD thật), không phải lỗi logic.

*192/192 test pass · eval PASS · replay PASS · chaos PASS.*
