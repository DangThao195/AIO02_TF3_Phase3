# Kiến trúc AI Engine — TF3 (AIO02)

> Thiết kế dựa trên kinh nghiệm production tổng hợp từ Google SRE Workbook (SLO burn-rate
> alerting), các nền tảng AIOps (Splunk, BigPanda, Walmart AIDR), OpenAI guardrails cookbook,
> và FinOps Foundation (FinOps for AI). Xem mục Nguồn tham khảo trong [README.md](README.md).

## Bức tranh tổng

```
                 ┌─────────────────────── LUỒNG AIOps ───────────────────────┐
                 │                                                            │
 Prometheus ──┐  │  ┌──────────┐   ┌─────────────┐   ┌──────────────┐        │
 OpenSearch ──┼──┼─▶│ Ingest & │──▶│  Detection   │──▶│ Correlation  │──▶ C2 Alert ──▶ CDO on-call
 Jaeger ──────┘  │  │ Baseline │   │ (burn-rate + │   │ & Dedup      │        │
     (C1)        │  └──────────┘   │  ML anomaly) │   └──────┬───────┘        │
                 │                 └─────────────┘          │                │
                 │                                          ▼                │
                 │                                 ┌────────────────┐        │
                 │                                 │ RCA Assistant  │──▶ C3 Evidence Pack
                 │                                 └────────┬───────┘        │
                 │                                          ▼                │
                 │                                 ┌────────────────┐        │
                 │                                 │ Remediation    │──▶ C6 Audit Trail
                 │                                 │ (approval gate)│        │
                 │                                 └────────────────┘        │
                 └────────────────────────────────────────────────────────────┘

                 ┌─────────────────────── LUỒNG AIE ─────────────────────────┐
                 │                                                            │
 frontend ──▶ product-reviews ──▶ [ AI Gateway: timeout / retry / breaker ]  │
                 │                        │                                   │
                 │                        ▼                                   │
                 │                  llm (OpenAI-compatible)   ◀── C4 Serving Contract
                 │                        │                                   │
                 │                        ▼                                   │
                 │            [ Guardrail: faithfulness check ]               │
                 │                 │pass          │fail                       │
                 │                 ▼              ▼                           │
                 │            hiển thị      ẩn tóm tắt (fallback)             │
                 │                                                            │
                 │            [ Cost Meter: token/request ] ──▶ C5 Cost Report│
                 └────────────────────────────────────────────────────────────┘
```

## Luồng AIOps — 4 tầng

### 1. Ingest & Baseline
- Nguồn dữ liệu theo [C1](contracts/C1-telemetry-access.md): Prometheus (metrics),
  OpenSearch (logs), Jaeger (traces).
- Dựng baseline động (dynamic baselining) thay vì ngưỡng tĩnh: học pattern theo giờ/ngày
  từ load-generator để giảm false positive — bài học số 1 của mọi hệ AIOps
  (77% team on-call nhận ≥10 alert/ngày nhưng <30% actionable).

### 2. Detection — hai lớp bổ trợ nhau
- **Lớp 1 (deterministic, tin cậy cao): SLO burn-rate multiwindow, multi-burn-rate**
  theo Google SRE Workbook ch.5. Với checkout SLO 99% (error budget 1%):
  - burn rate **14.4×** trên cửa sổ 1h (kèm cửa sổ ngắn 5m) → `critical` — page ngay.
  - burn rate **6×** trên 6h (kèm 30m) → `warning` — xử trong ca.
  - burn rate **1×** trên 3 ngày (kèm 6h) → `info` — đưa vào backlog/Ops Review.
  - Alert chỉ bắn khi **cả cửa sổ dài và ngắn** cùng vượt ngưỡng (tránh spike 5 phút).
- **Lớp 2 (ML, phủ rộng): anomaly detection** trên các metric không có SLO trực tiếp
  (latency từng service, Kafka lag, memory, tỉ lệ 429 từ llm...) — percentile/isolation-based,
  huấn luyện trên baseline tuần 1, đánh giá bằng precision trên incident thật.
- Nguyên tắc: **lớp 1 là nguồn page duy nhất**; lớp 2 chỉ tạo `warning`/`info` và
  làm giàu ngữ cảnh cho lớp 1 — chống alert fatigue từ thiết kế.

### 3. Correlation & Dedup
- Gom alert cùng cửa sổ thời gian + cùng nhánh phụ thuộc (theo bản đồ service trong
  `onboarding/ARCHITECTURE.md`) thành **một incident** — một trang gọi, không phải mười.
- Fingerprint theo `{service, sli, rule}` để dedup; alert lặp trong 15 phút bị gộp.
- Output chuẩn hóa theo schema [C2](contracts/C2-anomaly-alert-event.md).

### 4. RCA Assistant & Remediation
- Khi incident mở: tự động chụp cửa sổ telemetry (metrics quanh ±30m, exemplar traces
  từ Jaeger, log query kết quả từ OpenSearch) → sinh **Evidence Pack**
  ([C3](contracts/C3-rca-report.md)) để người trực khỏi đào tay.
- Remediation: engine chỉ **gợi ý** hành động (scale, restart, bật fallback). Thực thi
  cần approval của người trực, mọi bước ghi audit log ([C6](contracts/C6-remediation-audit.md)).
  Không bao giờ tự động can thiệp vào flagd/cơ chế sự cố của BTC (RULES §8).

## Luồng AIE — tầng AI trong sản phẩm

### AI Gateway (bọc quanh lời gọi `llm`)
Điểm kiểm soát duy nhất giữa `product-reviews` và `llm`, thực thi cam kết
[C4](contracts/C4-llm-serving.md):
- **Timeout budget** để trang sản phẩm giữ p95 < 1s: tóm tắt AI là best-effort,
  không được kéo cả trang xuống.
- **Retry có kỷ luật:** timeout/5xx retry với exponential backoff + jitter, tối đa 2 lần;
  **429 rate-limit không retry vô hạn** — đây là bài học production quan trọng nhất:
  retry mù vào 429 chỉ làm bão tệ hơn.
- **Circuit breaker:** N lỗi liên tiếp → mở mạch, trả fallback ngay; half-open probe
  từng request một để tự phục hồi.
- **Fallback phân tầng:** (1) cache tóm tắt đã sinh (TTL dài — review ít đổi);
  (2) không có cache → ẩn khối tóm tắt, vẫn hiện review thô. Khách không bao giờ thấy lỗi.

### Guardrail (chặn tóm tắt sai lệch)
- SLO ràng buộc cứng: *"không được hiển thị tóm tắt sai lệch"* — flag `llmInaccurateResponse`
  của BTC sẽ thử điều này (trả tóm tắt sai cho product `L9ECAV7KIM`).
- Pattern **LLM-as-judge / faithfulness check** (OpenAI cookbook): kiểm tra tóm tắt có
  được *chống lưng bởi chính các review đầu vào* không (đối chiếu sentiment + claim).
  Fail → ẩn tóm tắt (fallback), log lý do, đếm metric `guardrail_block_total`.
- Guardrail chạy **trước khi render** — thà không có tóm tắt còn hơn tóm tắt sai.

### Eval Harness
- Golden set: ~20 sản phẩm, tóm tắt chuẩn + nhãn sentiment kỳ vọng.
- Chạy trước mọi thay đổi model/prompt (CI) và định kỳ hằng ngày trên production sample.
- Metric: faithfulness pass-rate, guardrail block-rate, độ trễ p95 của lời gọi llm.

### Cost Meter
- Đếm input/output token + số request **tại gateway** (theo khuyến nghị FinOps Foundation:
  theo dõi ở mức request, không phải mức hóa đơn), tag theo `feature`, `product_id`, `model`.
- Xuất báo cáo tuần theo [C5](contracts/C5-ai-cost-report.md); cảnh báo khi chạm 80% trần tuần.

## Thứ tự triển khai đề xuất (map vào timeline)

| Tuần | AIOps | AIE |
|---|---|---|
| 1 | SLO dashboard + burn-rate rules (lớp 1) | Gateway timeout/fallback + cache; đo baseline cost |
| 2 | ML anomaly (lớp 2) + correlation; Evidence Pack v1 | Guardrail faithfulness + eval golden set |
| 3 | Remediation gợi ý + audit trail; tinh chỉnh ngưỡng | Chai hóa cost report, tối ưu (cache hit, prompt) |

Mọi mốc đều có deliverable chấm được: dashboard, alert rule đã bắn thật, Evidence Pack
của incident thật, eval report trước/sau, cost report tuần.
