# SPEC — Tuần 2 AIOps (TF3 / AIO02)

> Roadmap "hardcore" của anh, chốt thành spec thi công. Mỗi mục có: mục tiêu, deliverable,
> DoD (đo được), trạng thái. Tuần 2 tập trung **detection + correlation + RCA** vì chưa có
> healing tin cậy — mục tiêu là on-call không bị storm khi mentor bơm lỗi.

## Bối cảnh & nguyên tắc
- Chưa có auto-healing → **con người vẫn là người xử**. Nhiệm vụ AIOps tuần 2: *phát hiện sớm
  + gom nhiễu* để on-call đỡ "dùng máy thở" khi bị bơm storm, và có evidence sẵn khi vào ca.
- Deterministic (burn-rate) là nguồn page duy nhất; ML/anomaly chỉ warning; LLM chỉ augment RCA.

---

## Timeline & trạng thái

### T6 → T2: Anomaly Detection ✅ DONE
- **Mục tiêu:** bắt lỗi bơm TRƯỚC khi system chết / trước khi on-call nhận ra.
- **Focus service** (từ INCIDENT_HISTORY): checkout, payment, cart, kafka, email — weighted, hạ ngưỡng ở service hay đau.
- **Kỹ thuật:** robust z-score (median+MAD, không cần train, chịu outlier) + IsolationForest-ready ([ml] extra). Flat baseline → relative-change fallback (tránh false positive).
- **Deliverable:** [detector_anomaly.py](src/ai_engine/aiops/detector_anomaly.py). Metric: checkout/payment/cart p95, kafka lag, email memory.
- **DoD:** ✅ warning-max (không page); confidence<0.7 bị lọc; test spike→fire, normal→silent.

### T3 → T4: Alert Correlation ✅ DONE
- **Mục tiêu:** một incident thay vì storm 10 alert; on-call đọc 1 trang.
- **Kỹ thuật:** graph-based (dependency map) — anomaly cùng cluster **enrich** burn-rate incident thay vì page riêng; anomaly đứng riêng → early-warning incident. Dedup fingerprint + time-window 15m. Storm→digest.
- **Deliverable:** [correlator.py](src/ai_engine/aiops/correlator.py) + [alert_emitter.py](src/ai_engine/aiops/alert_emitter.py).
- **DoD:** ✅ test: checkout-burn + payment-anomaly → 1 incident; repeat trong window → folded; standalone anomaly → warning incident.

### T5 → CN: RCA ✅ DONE (v1)
- **Mục tiêu:** Evidence Pack ≤30 phút, on-call khỏi đào tay; postmortem viết từ data.
- **Trade-off 3 tầng** (đúng như anh nêu):
  | Tầng | Rẻ/tin | Vai trò | Chọn |
  |---|---|---|---|
  | Topology walk | rẻ, deterministic | downstream anomalous sâu nhất = culprit | ✅ primary |
  | Causal-by-time | rẻ, deterministic | cái gì moved trước = có khả năng nhân quả | ✅ |
  | LLM augment | đắt, có hallucination | phrase/merge hypothesis đọc mượt | ⚙️ optional, default OFF |
- **Deliverable:** [rca_assistant.py](src/ai_engine/aiops/rca_assistant.py). ≥2 hypothesis (anti-anchor), có bằng chứng chống, fail-graceful (blind→"evidence incomplete", không treo).
- **DoD:** ✅ test: pack ship dù telemetry mù; downstream anomaly = top hypothesis; human sign-off bắt buộc.

---

## Tuần 3 (spec sau, phác)
- **ADR** cho mọi lỗi gặp tuần 2 (lỗi gì + solution + why) — ký tên.
- **Auto-healing/remediation** (C6): whitelist action + approval + rollback + audit. Học từ repo tham khảo: Kyverno cap value-level + idempotency lock + S3 Object Lock audit.
- **Chaos/flagd test:** bật từng flag (paymentFailure/kafka/cart/email/llm...) trên docker-compose local → đo detection latency ≤3m, precision.

---

## Checklist tổng (roadmap ↔ code)

| Hạng mục | Trạng thái | File | Test |
|---|---|---|---|
| Burn-rate detector (layer 1) | ✅ | detector_burnrate.py | ✅ |
| Anomaly detector (layer 2, focus) | ✅ | detector_anomaly.py | ✅ |
| Correlation graph + dedup + storm | ✅ | correlator.py | ✅ |
| C2 Alert emitter + digest | ✅ | alert_emitter.py | ✅ |
| RCA Evidence Pack (C3) | ✅ | rca_assistant.py | ✅ |
| Recording + burnrate rules (Alertmanager fallback) | ✅ | prometheus/ | promtool |
| SLO + Engine Health dashboard | ✅/⏳ | grafana/ | — |
| Wire vào engine loop | ✅ | server.py | smoke |
| Fire-drill trên cluster thật | ⏳ | cần C1 CDO | — |
| **Tuần 3:** remediation C6 + chaos | ⏳ | — | — |

**Test tổng: 53/53 pass.** Còn treo: fire-drill cluster (chờ observability CDO), IsolationForest (optional), LLM-augment RCA (optional).

---

## Ý cho anh bổ sung (chốt mai)
1. **Precision > recall cho critical**: hiện chỉ burn-rate page; anomaly toàn warning. Đủ chưa hay muốn 1-2 anomaly nghiêm trọng (kafka lag/OOM) được nâng critical có điều kiện?
2. **RCA LLM augment**: bật default hay giữ OFF? Trade-off: đọc mượt vs cost/hallucination. Tôi nghiêng OFF tuần 2, bật thử tuần 3 có eval.
3. **Storm threshold**: hiện digest khi >20 alert/h. Mentor bơm mạnh có thể vượt — chỉnh xuống 10?
