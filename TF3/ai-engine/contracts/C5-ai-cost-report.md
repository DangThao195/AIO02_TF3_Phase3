# C5 — AI Cost Report Contract (showback chi phí AI)

| Trường | Giá trị |
|---|---|
| Version | 1.0.0 |
| Producer | **AIO02** (Cost Meter trong AI gateway) |
| Consumer | **CDO giữ trụ Cost Optimization** (tổng hợp vào ngân sách TF theo `onboarding/BUDGET.md`) + cả TF ở Ops Review |
| Nhịp giao | Báo cáo tuần (trước Ops Review) + cảnh báo tức thời khi chạm ngưỡng |
| Trạng thái | Draft — chờ CDO review |

## Mục đích

Theo FinOps Foundation (FinOps for AI): chi phí AI phải theo dõi được **ở mức request,
không phải mức hóa đơn** — nếu không giải thích được feature/model/retry nào tạo ra
spike thì chưa gọi là quản chi phí. Contract này cho CDO Cost pillar một dòng dữ liệu
chuẩn để cộng chi phí AI vào bức tranh ngân sách chung, và cho cả TF một con số
để đánh đổi (ví dụ: bật LLM thật đáng giá bao nhiêu/tuần).

---

## INPUT — thứ Cost Meter cần

| Input | Nguồn | Ghi chú |
|---|---|---|
| Token count mỗi request (input/output riêng) | AI gateway đếm tại chỗ (từ response `usage` của API OpenAI-compatible) | Không cần CDO làm gì |
| Bảng giá model | AIO duy trì file `TF3/cost/model-pricing.yaml` (giá/1K token in-out theo model) | Mock llm = $0; cập nhật khi đổi model, kèm ADR |
| **Trần ngân sách AI tuần** | **CDO Cost pillar cấp** — con số $/tuần cho tầng AI, trích từ ngân sách TF | **Input duy nhất CDO phải cung cấp.** Chưa có số → AIO đề xuất, CDO duyệt |
| Chi phí hạ tầng AI (pod llm, cache) | CDO cung cấp cách tính (từ công cụ cost của CDO) hoặc chấp nhận ước lượng resource-request × đơn giá node | Thống nhất 1 lần, ghi vào contract |

## OUTPUT — thứ CDO nhận

### 1. Metrics realtime (Prometheus, CDO tự query được bất cứ lúc nào)

| Metric | Ý nghĩa |
|---|---|
| `ai_cost_tokens_total{direction=input\|output, model, feature}` | Token tiêu thụ, tag đầy đủ để attribution |
| `ai_cost_usd_total{model, feature}` | Chi phí quy đổi lũy kế (counter) |
| `ai_cost_per_request_usd` (gauge, trung bình trượt 1h) | Đơn giá mỗi lần tóm tắt |
| `ai_cache_hit_ratio` | Mỗi cache hit = một lời gọi model không phải trả tiền |

Tag `feature` hiện có: `review-summary`, `review-qa` (hỏi-đáp), `rca-assistant`,
`guardrail-judge` — chi phí AIOps nội bộ cũng được đếm, không giấu.

### 2. Báo cáo tuần (file `TF3/cost/reports/YYYY-Www.md`, nộp trước Ops Review)

```markdown
# AI Cost Report — Tuần <ww>
## Tổng quan
- Tổng chi AI tuần: $X.XX / trần $Y.YY (Z%)   [tuần trước: $..., thay đổi: ±..%]
- Cost/request trung bình: $0.000X  | Cache hit: XX%  | Retry overhead: X% tổng lời gọi

## Phân rã
| Feature | Requests | Tokens in/out | USD | % |
|---|---|---|---|---|
| review-summary | ... | ... | ... | ... |
| guardrail-judge | ... | ... | ... | ... |
| rca-assistant | ... | ... | ... | ... |

## Hạ tầng AI (pod llm + cache): $X.XX (theo cách tính đã thống nhất với CDO)

## Diễn giải spike (nếu có)
<ngày nào, feature nào, vì sao — vd: incident 429 làm retry tăng, hay flag BTC>

## Đề xuất tối ưu tuần tới (kèm ước tính tiết kiệm)
<vd: tăng TTL cache 24h→72h ước tiết kiệm $X; đổi model judge rẻ hơn...>
```

### 3. Cảnh báo ngưỡng (đi qua kênh alert C2, `source_layer: cost`)

| Ngưỡng | Severity |
|---|---|
| Chi tuần chạm 80% trần | `warning` — bàn ở standup |
| Chạm 100% trần | `critical` — AIO tự động hạ chế độ: tăng cache TTL, tắt feature AI không cốt lõi (rca-assistant dùng model rẻ/mock), **không được tự tắt guardrail** |
| Cost/request tăng >3× baseline trong 1h | `warning` — thường là retry storm hoặc prompt phình |

## Cam kết SLA

| Cam kết | Ngưỡng |
|---|---|
| Độ trễ số liệu | Metrics realtime ≤ 1 phút; báo cáo tuần đúng hạn 100% |
| Sai số quy đổi USD | ≤ 5% so với hóa đơn thật (nếu dùng LLM ngoài); đối chiếu mỗi tuần |
| Attribution | ≥ 95% chi phí AI có tag `feature` (phần không tag được ghi `untagged` và phải giải trình nếu >5%) |

## Failure modes

| Tình huống | Hành vi |
|---|---|
| Meter chết | Lời gọi llm **vẫn chạy** (meter nằm ngoài critical path); lỗ hổng số liệu được ghi chú trong báo cáo tuần |
| Bảng giá lỗi thời | Đối chiếu hóa đơn tuần lộ sai số >5% → sửa `model-pricing.yaml` + ghi chú hồi tố |

## Tiêu chí nghiệm thu

- [ ] CDO Cost pillar query được 4 metric trên trong Prometheus.
- [ ] Báo cáo tuần đầu tiên nộp đúng format, CDO đọc hiểu không cần AIO giải thích miệng.
- [ ] Trần ngân sách AI tuần đã được CDO chốt bằng văn bản (ADR).
- [ ] Test cảnh báo 80% bằng trần giả lập thấp.
