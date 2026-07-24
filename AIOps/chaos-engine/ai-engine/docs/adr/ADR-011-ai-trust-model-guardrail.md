# ADR-011: AI đáng tin — chọn model, guardrail + fallback, eval sàn 5+5

| | |
|---|---|
| **Status** | Accepted |
| **Ngày** | 2026-07-16 |
| **Người quyết + ký** | AIO02 / TF3 — _______________ (ký) |
| **Liên quan** | MANDATE #06, ADR-001 (provider), ADR-002 (caching/fallback), ADR-010 (eval) |

## Context

Mandate #06 đòi tính năng AI "đáng tin thì mới tính là chạy": model thật + fallback, không show
nội dung sai, không bị dắt mũi (injection/PII/system-leak), trợ lý không tự checkout — và
**chứng minh bằng eval ≥5 ca faithfulness + ≥5 ca injection tái tạo được**, không bằng lời.

## Decision

1. **Model + fallback**: LLM thật qua AI Gateway (`aie/gateway.py`), route baseline-rẻ +
   heavy-cho-câu-khó (ADR-001). Fallback phân tầng: cache → breaker → timeout → **guardrail** →
   câu trả lời an toàn. Model lỗi/chậm → trang KHÔNG treo (ADR-002).
2. **Guardrail**: faithfulness 2 tầng (rule sentiment-vs-điểm + LLM-judge optional), fail-closed
   (`aie/guardrail.py`); input filter chặn injection/PII/system-leak (`aie/input_filter.py`,
   nay có cả pattern tiếng Việt); agent tool allowlist + confirmation (`agent/tools.py`).
3. **Eval chứng minh**: dùng harness ADR-010 (`eval_harness.py`) — bộ ca `mandate14-labeled-set.json`
   có 3 grounded + 3 unanswerable + 5 injection + 2 PII + 3 agency + 2 task (vượt sàn 5+5), chạy
   1-lệnh ra số. Bar cứng PII/leak/ghi = 0 kiểm tự động.

## Alternatives considered (≥2)

### Phương án A — Gateway in-process + guardrail 2 tầng + eval harness (ĐÃ CHỌN)
- ✅ Pros: mọi chính sách AI tập trung một chỗ (dễ audit); fallback không treo trang; eval tái
  tạo ra số; đã bắt+vá lỗ hổng injection VN thật.
- ❌ Cons: gateway là điểm tập trung (bù bằng breaker + fallback nhiều tầng).
- Chi phí: tối ưu token qua cache; không "quăng model to cho xong".

### Phương án B — guardrail chỉ 1 tầng rule (không LLM-judge)
- ✅ Pros: rẻ, nhanh, không phụ thuộc LLM.
- ❌ Cons: bỏ sót ca ngữ nghĩa tinh vi. **Chọn 2 tầng** (rule trước, judge optional) — cân bằng.

### Phương án C — không có eval, chỉ demo tay
- ❌ Cons: mandate cấm rõ "chứng minh bằng eval không bằng lời". **Loại.**

## Consequences

- Tích cực: guardrail đạt bar cứng (PII/leak/ghi trái phép = 0); eval sàn 5+5 vượt (19 ca);
  fallback không treo trang. Bằng chứng: `evals/report.md`.
- Tiêu cực chấp nhận: LLM thật chưa bật trên cluster (còn mock) — grounding đo trên answer cấp
  sẵn; cần deploy `values-aio-llm.yaml` + secret để đo trên model thật + chụp mentor bắn.
- Việc phát sinh: bật LLM thật + ảnh/log chạy thật (injection chặn, PII che, "không có thông
  tin", eval ra số) khi có cluster.

---
**Ký xác nhận:** ____________ · Ngày: 2026-07-16
