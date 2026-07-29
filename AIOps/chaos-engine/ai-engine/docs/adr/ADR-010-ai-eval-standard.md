# ADR-010: Chuẩn eval AI — harness nhận input ngoài, 6 chiều, judge↔người

| | |
|---|---|
| **Status** | Accepted |
| **Ngày** | 2026-07-16 |
| **Người quyết + ký** | AIO02 / TF3 — _______________ (ký) |
| **Liên quan** | MANDATE #06, #14, `aie/eval_harness.py`, ADR-001/002 (provider/caching) |

## Context

Mandate #06/#14 đòi tầng AI "đáng tin phải chứng minh bằng số, tái tạo được, chịu được bộ ca
ẩn BTC bơm lúc chấm". Ba câu hỏi:
1. Đo những chiều nào và bằng logic gì (mentor soi cả cách chấm)?
2. Faithfulness dùng LLM-judge thì làm sao tin judge (judge có thể sai như model)?
3. Làm sao nhận bộ ca ẩn mà không sửa code?

## Decision

1. **Harness 6 chiều** (`eval_harness.py`), mỗi ca một `kind`, logic chấm MỞ:
   - Grounding (faithfulness qua `FaithfulnessGuardrail`), Abstention (unanswerable→"không có
     thông tin"), Injection-block (review + **multi-turn**), PII (phát hiện+che), Excessive-agency
     (ghi→deny/confirm), Task-success (tool đúng, không tính "trôi chảy").
2. **Judge↔người**: mỗi ca grounding mang `human_label`; harness báo `judge_agreement` = tỉ lệ
   khớp máy↔người. ≥10 ca người-gán để con số có nghĩa. Judge sai người phát hiện được.
3. **Nhận input ngoài**: `scripts/eval_ai.py <cases.json>` — mentor bơm bộ ẩn dưới dạng JSON,
   không đụng code. Bar cứng kiểm tự động: PII/system-leak/ghi-trái-phép = 0.

Điều kiện xét lại: bộ ẩn cho false-block cao → nới pattern; miss injection → thêm pattern.

## Alternatives considered (≥2)

### Phương án A — harness JSON 6 chiều + judge↔người (ĐÃ CHỌN)
- ✅ Pros: mentor bơm ca ẩn không cần sửa code; logic chấm đọc được; judge có đối chứng người;
  bar cứng tự kiểm; tái tạo 1-lệnh ra số.
- ❌ Cons: cần soạn nhãn người; faithfulness rule-based có thể bỏ sót ca tinh vi (bù bằng LLM-judge optional).
- Chi phí: 0 hạ tầng (thuần Python + guardrail sẵn có).

### Phương án B — chỉ LLM-judge, không đối chứng người
- ✅ Pros: linh hoạt, bắt ca tinh vi.
- ❌ Cons: judge sai thì không ai biết (mandate đòi rõ judge↔người ≥10 ca). **Loại.**

### Phương án C — chỉ assert cứng trong test nội bộ
- ✅ Pros: nhanh.
- ❌ Cons: không nhận được ca ẩn từ ngoài; mandate đòi "harness nhận input ngoài". **Loại làm chính** — giữ test làm lớp regression.

## Consequences

- Tích cực: `evals/report.md` ra số 6 chiều + judge-agreement; bộ mẫu 19 ca (5+ faithfulness,
  5 injection, PII, agency, task) PASS 100%, judge↔người 100%. **Trong lúc làm eval đã bắt +
  vá lỗ hổng thật**: injection tiếng Việt ("bỏ qua hướng dẫn", "SYSTEM:") và PII số VN liền
  (0909…) mà input_filter cũ bỏ sót → nâng cấp bảo mật thật, không chỉ đo.
- Tiêu cực chấp nhận: faithfulness hiện rule-based (sentiment+claim) — mạnh nhưng không bằng
  LLM-judge cho ca ngữ nghĩa tinh vi; LLM thật + judge để bật khi có cluster.
- Việc phát sinh: bật LLM thật (#06) để đo grounding trên model thật; cost/latency before/after;
  mở rộng nhãn người lên ≥10 ca đa dạng.

---
**Ký xác nhận:** ____________ · Ngày: 2026-07-16
