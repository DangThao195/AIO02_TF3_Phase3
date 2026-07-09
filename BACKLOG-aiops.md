# Backlog AIOps — TF3 / AIO02

> Backlog trụ AI (luồng AIOps), xếp theo **Ưu tiên = Rủi ro (khả năng × nghiêm trọng) ×
> Tác động business**. Neo vào SLO / BUDGET / INCIDENT_HISTORY, không neo vào "có phải
> feature không". Dùng cho pitch + Ops Review. Backlog AIE ở [AI_BASELINE_EVAL.md §5].
>
> Rủi ro & Business: thang 1-5. P0 = làm trước, P3 = hoãn có chủ đích.

## Đã xong (Tuần 1-2) — giữ để chứng minh ở Ops Review

| Mã | Việc | Rủi ro | Business | Ưu tiên | Trạng thái |
|---|---|---|---|---|---|
| AIOPS-001 | Burn-rate detector đa cửa sổ (page tin được) | 5 | Bảo vệ checkout revenue | P0 | ✅ done, test |
| AIOPS-002 | Anomaly detector focus theo INC-history | 4 | Bắt lỗi bơm trước khi system chết | P0 | ✅ done, test |
| AIOPS-003 | Correlation graph + storm dedup | 4 | On-call đỡ storm khi mentor bơm | P0 | ✅ done, test |
| AIOPS-004 | C2 alert schema + Alertmanager fallback | 4 | Engine chết vẫn page được | P0 | ✅ done, test |
| AIOPS-005 | RCA Evidence Pack (C3) ≤30m | 3 | Giảm MTTR, postmortem từ data | P1 | ✅ done, test |

## Cần làm (Tuần 3 + treo)

| Mã | Việc | Mô tả | Rủi ro | Business | Ưu tiên | Trạng thái |
|---|---|---|---|---|---|---|
| AIOPS-006 | **Remediation + audit trail (C6)** | Whitelist action (scale/restart/cache-flush) + approval người thật + rollback + audit append-only. Hard-block flagd trong code. | 5 | Rút ngắn MTTR có kiểm soát; truy-về-người (bắt buộc RULES §7) | **P0** | ⏳ Tuần 3 |
| AIOPS-007 | **Chaos/flagd fire-drill** | Bật từng flag (payment/kafka/cart/email/llm) trên docker-compose local → đo detection latency ≤3m + precision. | 4 | Chứng minh engine bắt được lỗi thật, số cho Ops Review | **P0** | ⏳ Tuần 3 |
| AIOPS-008 | Defense-in-depth remediation (Kyverno) | Cap value-level (replica ≤N, mem ≤X) ở admission webhook + idempotency lock. Học từ repo tham khảo. | 3 | An toàn auto-action, mạnh cho audit | P1 | ⏳ |
| AIOPS-009 | ADR mọi lỗi Tuần 2 | Lỗi gì + solution + why, ký tên. | 2 | Deliverable bắt buộc, bảo vệ ở hội đồng | P1 | ⏳ Tuần 3 |
| AIOPS-010 | IsolationForest anomaly (multivariate) | Bật lớp ML thứ 2 cho anomaly joint (latency+lag+mem cùng lệch). | 2 | Bắt anomaly tinh vi hơn z-score đơn biến | P2 | ⚙️ ready, chưa bật |
| AIOPS-011 | LLM-augment RCA | Dùng LLM phrase/merge hypothesis đọc mượt. Có eval + cost cap. | 2 | Evidence dễ đọc hơn — trade-off cost/hallucination | P2 | ⚙️ optional, OFF |
| AIOPS-012 | Fix metric name sau deploy | Xác nhận tên thật kafka lag/email memory + latency histogram trên Prometheus live; điền telemetry-dependencies. | 3 | Detector không gãy im lặng | P1 | ⏳ chờ C1 CDO |
| AIOPS-013 | Tinh chỉnh ngưỡng theo false-positive | Dùng nhãn false-positive từ CDO on-call để chỉnh z-threshold + burn-rate. | 2 | Giảm alert fatigue, tăng precision | P2 | ⏳ liên tục |

## Phụ thuộc cần chốt với CDO (block P0)

- **C1 observability lên** (Prometheus/OpenSearch/Jaeger) — không có = AIOPS-007/012 đứng.
- **Change log #tf3-changes** — nuôi RCA (AIOPS-005).
- **Fire-drill window** — cần cluster thật cho AIOPS-007.

## 3 câu quyết định (chốt để mở khoá backlog)

1. Anomaly nghiêm trọng (kafka lag/OOM) nâng critical có điều kiện? → ảnh hưởng AIOPS-002 threshold.
2. LLM-augment RCA bật hay OFF? → AIOPS-011.
3. Storm threshold 20→10 alert/h? → AIOPS-003.
