# ADR-009: Chuẩn phát hiện đáng tin — baseline lệch-khỏi-bình-thường + cửa replay nhận input ngoài

| | |
|---|---|
| **Status** | Accepted |
| **Ngày** | 2026-07-16 |
| **Người quyết + ký** | AIO02 / TF3 — _______________ (ký) |
| **Liên quan** | MANDATE #15, ADR-007 (multi-signal detection), `replay_harness.py` |

## Context

Mandate #15 đòi detector "đáng tin": bắt đúng sự cố thật, **phân biệt bận với hỏng**, không bị
nhiễu che (masking), chạy liên tục, và **chịu được bộ kịch bản ẩn BTC bơm lúc chấm**. Ba câu hỏi
kiến trúc:
1. Cảnh báo dựa trên mốc tuyệt đối hay độ lệch khỏi bình thường của chính service?
2. Làm sao chứng minh (không phải demo 1 lần) — mentor cần soi logic chấm + bơm ca ẩn?
3. Đo MTTD before/after thế nào?

## Decision

1. **Baseline lệch-khỏi-bình-thường, không mốc tuyệt đối.** Dùng robust z-score (median+MAD)
   per-service từ chuỗi 1 tuần. "Bận" = z tăng nhẹ nhưng **confidence < 0.7 → bị chặn** trước
   khi rời engine (C2 gate). "Hỏng" = z vượt ngưỡng có trọng số focus. Đây là cơ chế "không kêu
   oan khi service chỉ đang bận".
2. **Cửa replay nhận scenario JSON từ ngoài** (`replay_harness.py` + `scripts/replay.py`). Mentor
   soạn file JSON (windows + ground_truth có nhãn kind: real / masking-real / masking-noise /
   busy-healthy), harness replay qua `Correlator` + pipeline THẬT, chấm recall/precision/MTTD +
   masking-check + busy-check. **Logic chấm mở** (đọc được trong module), đúng yêu cầu "mentor soi
   cách chấm".
3. **MTTD before/after**: after = MTTD đo tự động qua replay; before = mốc soi-Grafana-thủ-công do
   mentor cấp (`--baseline-mttd`). Report tính % cải thiện.

Điều kiện xét lại: nếu bộ ca ẩn cho false-block hoặc miss → tune gate confidence / trọng số focus.

## Alternatives considered (≥2)

### Phương án A — baseline per-service + cửa replay JSON (ĐÃ CHỌN)
- ✅ Pros: "bận≠hỏng" nhờ z-score tương đối + confidence gate; mentor bơm ca ẩn không cần sửa code
  (chỉ soạn JSON); logic chấm mở; tái tạo 1-lệnh.
- ❌ Cons: cần soạn ground-truth nhãn; replay là mô phỏng tick, MTTD thật phải đo trên cluster.
- Chi phí: 0 hạ tầng thêm (thuần Python).

### Phương án B — ngưỡng tĩnh tuyệt đối (vd p95 > 1s luôn kêu)
- ✅ Pros: đơn giản.
- ❌ Cons: kêu oan mọi giờ cao điểm bình thường (vi phạm "không kêu oan khi bận"); mandate cấm rõ
  "không mốc tuyệt đối". **Loại.**

### Phương án C — test nội bộ hard-code (không nhận input ngoài)
- ✅ Pros: nhanh viết.
- ❌ Cons: mentor không bơm được ca ẩn → không chứng minh được "chịu bộ kịch bản ẩn"; #15 đòi
  "cửa nhận kịch bản từ ngoài". **Loại.**

## Consequences

- Tích cực: chứng minh 3 tiêu chí ẩn (#15) bằng `replay/report.md` — real→bắt, masking→vẫn bắt
  sự cố nhẹ, busy-healthy→không kêu; đo được recall/precision/MTTD.
- Tiêu cực chấp nhận: replay là mô phỏng — MTTD/precision THẬT phải đo trên cluster khi deploy
  liên tục (còn treo); masking scenario có thể có false-fire nếu spike nhiễu bản thân là anomaly
  hợp lệ (giải thích được, không phải bug).
- Việc phát sinh: deploy detector làm workload thường trực + merge trunk (#15 §4); đo MTTD before
  thật từ mentor.

---
**Ký xác nhận:** ____________ · Ngày: 2026-07-16
