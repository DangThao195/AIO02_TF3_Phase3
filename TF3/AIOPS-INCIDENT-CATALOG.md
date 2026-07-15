# AIOps — Danh mục sự cố phải xử lý (TechX-Corp phase3)

> Nguồn: `phase3/techx-corp-chart/flagd/demo.flagd.json` (15 flag BTC bơm) +
> `onboarding/INCIDENT_HISTORY.md` (3 sự cố lịch sử) + `onboarding/SLO.md` + `RULES.md`.
>
> **Luật vàng (RULES §8):** sự cố là để **xử lý**, KHÔNG phải để tắt. Cấm tắt/gỡ/refactor
> đường dây đọc flag → **disqualify**. Cách đúng: **fallback · retry · containment** để hệ
> chịu được, giữ ảnh hưởng khách nhỏ nhất, phục hồi nhanh.

## SLO phải bảo vệ

| Luồng | SLI | SLO | Error budget |
|---|---|---|---|
| Duyệt/tìm SP | non-5xx | ≥ 99.5% | 0.5% |
| Duyệt — độ trễ | p95 storefront | < 1s | — |
| Giỏ hàng | thao tác giỏ thành công | ≥ 99.5% | 0.5% |
| **Checkout (ra tiền)** | đặt hàng thành công | **≥ 99.0%** | 1% — ưu tiên bảo vệ nhất |

---

## A. 15 flag lỗi BTC bơm (danh sách chính engine phải bắt + xử)

| # | Flag | Service | Triệu chứng | SLO đe dọa | Cách xử ĐÚNG (không tắt flag) |
|---|---|---|---|---|---|
| 1 | `paymentFailure` | payment | charge lỗi n% | Checkout | retry có budget + fallback; báo động burn-rate checkout |
| 2 | `paymentUnreachable` | payment | payment down hẳn | Checkout | circuit breaker → fallback; containment, page on-call |
| 3 | `cartFailure` | cart | thao tác giỏ lỗi | Cart | retry + degrade mềm; **KHÔNG restart** (INC-2 SPOF) |
| 4 | `failedReadinessProbe` | cart | readiness probe fail | Cart | chờ probe/scale; không restart pod single-replica |
| 5 | `productCatalogFailure` | product-catalog | 1 SP lỗi | Browse | fallback cache/ẩn SP lỗi; cô lập theo product |
| 6 | `kafkaQueueProblems` | kafka | lag spike + consumer delay | Browse/async | anomaly consumer-lag → cảnh báo; scale consumer/containment |
| 7 | `recommendationCacheFailure` | recommendation | cache lỗi | Browse (phụ) | fallback không-cache; cache-flush |
| 8 | `emailMemoryLeak` | email | rò rỉ bộ nhớ → OOM | phụ trợ | anomaly memory → cảnh báo sớm trước OOM; scale/restart (multi-replica) |
| 9 | `adFailure` | ad | ad service lỗi | Browse (phụ) | degrade: ẩn ad, giữ trang |
| 10 | `adHighCpu` | ad | CPU cao | Browse (phụ) | anomaly CPU; scale/containment |
| 11 | `adManualGc` | ad | full GC → latency | Browse (phụ) | anomaly latency (multi-window z-score) |
| 12 | `imageSlowLoad` | frontend | ảnh tải chậm | **p95 storefront <1s** | multi-window robust z-score latency → cảnh báo |
| 13 | `loadGeneratorFloodHomepage` | frontend | flood request | p95 storefront / browse | scale frontend; rate-limit/containment |
| 14 | `llmRateLimitError` | llm (AIE) | 429 chập chờn | trang SP (AI) | **không retry mù**; breaker + cache/ẩn tóm tắt (C4) |
| 15 | `llmInaccurateResponse` | llm (AIE) | tóm tắt sai SP `L9ECAV7KIM` | nội dung (C4) | **guardrail faithfulness chặn**, hiện review thô |

> Riêng #14/#15 thuộc **tầng AIE (C4)**, không phải AIOps hạ tầng — xử ở AI Gateway + Guardrail.
> Tất cả còn lại là AIOps: detect (burn-rate/anomaly) → correlate → alert → RCA → remediation.

---

## B. 3 sự cố lịch sử (đã đóng — vùng yếu hay lặp lại)

| Mã | Sự cố | Nguyên nhân gốc | Bài học còn treo → engine phải nhớ |
|---|---|---|---|
| **INC-1** | Checkout chậm/lỗi giờ cao điểm | cạn DB connection pool khi tải tăng | cảnh báo pool gần cạn; scale để giãn tải (local_matcher → scale) |
| **INC-2** | Mất giỏ hàng khi node reschedule | cart single-replica, state in-memory mất | **TUYỆT ĐỐI không auto-restart cart** (mất giỏ) → action=none, cảnh báo SRE |
| **INC-3** | Lỗi thanh toán lúc deploy | traffic vào pod chưa readiness | readiness gating; rollout có kiểm soát |

**Điểm chung:** cả 3 xoay quanh **độ tin cậy dưới áp lực** (quá tải, mất node, deploy). Đây là
vùng engine phải canh trước tiên.

---

## C. Ánh xạ sang engine (đã có gì để xử)

| Năng lực | Bắt lỗi nào | Module |
|---|---|---|
| Burn-rate SLO (critical) | 1,2,3,5,6,13 (SLO vỡ) | `detector_burnrate.py` |
| Anomaly z-score (warning) | 8,10,11 (mem/cpu/gc) | `detector_anomaly.py` |
| Multi-window latency | 11,12,13 (p95 storefront) | `detector_latency.py` |
| Guardrail + gateway | 14,15 (LLM) | `aie/gateway.py`, `aie/guardrail.py` |
| RCA + local fallback | tất cả (diagnosis) | `rca_assistant.py`, `local_matcher.py` |
| Remediation an toàn | scale/restart/cache-flush; **INC-2 → none** | `remediation.py` (safety gate + verify-loop) |

> Nguyên tắc remediation: chỉ scale/restart/cache-flush/breaker-force trong whitelist; hard-block
> flagd/BTC flag; INC-2 không restart; verify 5 phút → auto-rollback nếu không hồi phục.
