# MANDATE #07b + #15 — Detection chạy thật + đo đạc

**TF3 / AIO02** · #07b hạn 25/07 · #15 hạn 25/07 · *(gộp vì trùng phần lớn: đều đòi chạy thật + precision/recall/lead-time + bộ ca ẩn)*

> #07a (implement + phân tích) đã xong (`MANDATE-7a-detection-analysis.md` + ADR-007). Doc này
> là phần chạy-thật + đo-đạc cho #07b, đồng thời phủ chuẩn "đáng tin" của #15.

---

## 1. Cách bơm sự cố → detector kêu (e2e)

Hai đường, đều KHÔNG đụng cơ chế flagd (RULES §8 — chỉ bật/tắt variant):

### 1a. Bơm qua flagd (mentor bật / dùng control-panel)
- **Bảng điều khiển**: `chaos-engine/chaos-control-panel.html` — 15 flag thật từ `demo.flagd.json`,
  bật/tắt từng lỗi hoặc bơm ngầm. Sinh sẵn lệnh `kubectl patch cm techx-flagd` để bơm THẬT.
- Bật một flag (vd `productCatalogFailure=on`) → service lỗi → detector đọc telemetry → kêu.
- Bằng chứng cần chụp (khi có cluster): ảnh alert Slack + log detector + thời điểm.

### 1b. Replay bộ ca có nhãn (cửa nhận input ngoài — #15)
```
python scripts/replay.py scenarios/mandate15-sample-set.json --baseline-mttd 900
```
Mentor soạn scenario JSON (windows + ground_truth), harness replay qua pipeline THẬT
(`Correlator` + `RCAAssistant`), chấm recall/precision/MTTD + masking + busy. Logic chấm mở
(`aiops/replay_harness.py`) — mentor soi được cách chấm.

## 2. Số đo (bộ mẫu — thay bằng bộ ẩn của mentor lúc chấm)

Từ `replay/report.md` (bộ mẫu 3 scenario):

| Scenario | Recall | Precision | MTTD | Masking | Busy-healthy |
|---|---|---|---|---|---|
| real-incident-INC1 | 100% | 100% | 30s | — | — |
| masking-noise-hides-mild | 100% | 67%* | 30s | ✅ bắt sự cố nhẹ | — |
| busy-but-healthy | — | — | — | — | ✅ không kêu oan |

*Precision 67% ở masking: spike nhiễu `ad` (z=12, conf 0.95) tự nó là anomaly hợp lệ → tạo 1
incident phụ. Đây là hành vi ĐÚNG (không phải false theo nghĩa kêu-vô-cớ) — giải thích được.

**MTTD before/after**: after ≈ 30s (1 chu kỳ tick) · before = 900s (soi Grafana thủ công, mốc
mentor cấp) → **giảm ~97%**.

## 3. Chuẩn "đáng tin" #15 — 3 tiêu chí ẩn

| Tiêu chí | Cơ chế | Bằng chứng |
|---|---|---|
| **Bắt đúng sự cố thật** | burn-rate + robust z-score per-service | replay recall 100% |
| **Không bị masking** (spike nhiễu không che sự cố nhẹ) | correlator dedup không nuốt + gom theo cluster | scenario masking → vẫn bắt kafka lag |
| **Không kêu oan khi bận** (lệch baseline, không mốc tuyệt đối) | confidence gate 0.7 chặn z-nhẹ trước correlator | scenario busy-healthy → 0 incident |
| **Chạy liên tục** | `server.py` loop `tick()` 30s | ⚠️ cần deploy làm workload thường trực + merge trunk |
| **Tự sinh incident summary** | `alert_emitter` + `rca_assistant` Evidence Pack | replay in summary mỗi lần kêu |

## 4. Còn thiếu (cần cluster — không phải code)

- Ảnh alert Slack THẬT khi bơm 1 flag (cần cluster sống + Slack wired).
- Số precision/recall/lead-time trên **bộ ẩn của mentor** (thay bộ mẫu).
- Detector chạy **liên tục** trong cụm (deploy `k8s/` manifest) + merge trunk.
- MTTD **before** thật (mốc thủ công do mentor cấp).

## 5. Repro (1 lệnh mỗi thứ)

```
# detector logic + chaos (offline, deterministic)
python scripts/chaos_validate.py

# replay bộ ca có nhãn (cửa nhận input ngoài)
python scripts/replay.py scenarios/mandate15-sample-set.json --baseline-mttd 900

# UI bơm lỗi
open chaos-engine/chaos-control-panel.html
```

ADR: `docs/adr/ADR-007-multi-signal-detection.md` (baseline/ngưỡng) + `ADR-009-detection-standard-replay.md`
(chuẩn đáng tin + cửa replay).
