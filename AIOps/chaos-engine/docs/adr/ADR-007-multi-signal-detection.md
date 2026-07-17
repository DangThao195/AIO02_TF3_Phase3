# ADR-007: Phát hiện bất thường đa tín hiệu, 2 tầng (deterministic burn-rate + statistical z-score)

| | |
|---|---|
| **Status** | Accepted |
| **Ngày** | 2026-07-16 |
| **Người quyết + ký** | AIO02 / TF3 — _______________ (ký) |
| **Liên quan** | Directive #7 (Detection), INC-1/INC-5, contracts C2, `SELF-HEALING-CHECKLIST.md` |

## Context

Directive #7 yêu cầu dựng "đôi mắt" tự phát hiện sự cố trước khi khách kêu, trên telemetry thật
(Prometheus/OpenSearch/Jaeger), với 4 ràng buộc: (1) sàn = univariate per service×signal có baseline
riêng, multivariate là bonus; (2) baseline per-service để không báo nhầm lúc tải cao bình thường;
(3) cảnh báo theo mức ảnh hưởng, không spam; (4) chạy được e2e. Thêm ràng buộc: đo phải nhẹ, trong
ngân sách, không đụng flagd.

Câu hỏi kiến trúc: dùng **một** phương pháp cho mọi tín hiệu (đơn giản nhưng hoặc quá nhạy hoặc quá
điếc), hay **phân tầng** theo độ tin cậy của tín hiệu?

## Decision

Dùng kiến trúc **2 tầng**:
- **Layer 1 (deterministic):** burn-rate multi-window multi-burn-rate (Google SRE 14.4×/6×/1×) trên SLI
  error-budget — là **nguồn page `critical` DUY NHẤT**. Chỉ fire khi cả long + short window cùng breach.
- **Layer 2 (statistical):** robust z-score (median + MAD) per-service cho latency/saturation/queue-lag/429,
  tối đa WARNING, không page. Baseline = chuỗi 1 tuần. Bonus multivariate: IsolationForest + log-template.

Mọi tín hiệu gom qua `correlator` (dedup + cluster theo dependency graph) rồi `alert_emitter` báo theo
mức ảnh hưởng. Điều kiện xét lại: nếu precision burn-rate < 90% hoặc false-alarm layer-2 > 1/ngày sau
2 tuần baseline → tune ngưỡng.

## Alternatives considered (≥2)

### Phương án A — 2 tầng deterministic + statistical (ĐÃ CHỌN)
- ✅ Pros: burn-rate cho precision cao ở page (không đánh thức người vì gợn nhỏ); z-score bắt sớm ở
  layer-2 mà không page; baseline robust (median+MAD) miễn nhiễm outlier + tải-cao-bình-thường.
- ❌ Cons/trade-off: 2 code path phải bảo trì; cần recording-rule SLI từ CDO cho layer-1.
- Chi phí: chỉ đọc PromQL có sẵn (nhẹ), không hạ tầng mới, không thêm cụm.

### Phương án B — chỉ ngưỡng tĩnh (static threshold)
- ✅ Pros: đơn giản nhất, không cần baseline.
- ❌ Cons: directive cấm rõ "không chỉ ngưỡng tĩnh"; báo nhầm lúc tải cao bình thường; không thích ứng
  theo service. **Loại.**

### Phương án C — chỉ ML (autoencoder/LSTM đa biến toàn hệ)
- ✅ Pros: bắt pattern tinh vi, một mô hình chung.
- ❌ Cons: nặng (GPU/train 1-2 tuần), khó giải thích cho on-call, vượt ngân sách "đừng dựng cụm nặng cho
  oách"; multivariate chỉ là bonus chứ không phải sàn. **Loại làm lõi** — giữ IsolationForest nhẹ làm bonus.

## Consequences

- Tích cực (đo được): MTTD giảm (sự cố tự lộ qua alert, không đợi soi Grafana); precision page cao nhờ
  multi-window AND; đo bằng recall/precision/lead-time ở #7b.
- Tiêu cực chấp nhận: phụ thuộc recording-rule SLI của CDO (nếu thiếu → burn-rate layer-1 mù; đã ghi
  guard G4 trong SELF-HEALING-CHECKLIST); 2 tầng cần bảo trì.
- Việc phát sinh: #7b đo precision/recall/lead-time trên bộ sự cố có nhãn; guard G4 (verify recording-rule
  tồn tại trước khi rollback mù).

---
**Ký xác nhận:** ____________ · Ngày: 2026-07-16
