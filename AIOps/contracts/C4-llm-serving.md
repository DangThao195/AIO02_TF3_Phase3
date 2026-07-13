# C4 — LLM Serving & Guardrail Contract (tính năng tóm tắt review AI)

| Trường | Giá trị |
|---|---|
| Version | 1.0.0 |
| Owner | **AIO02** (AIE — chủ tầng AI sản phẩm: `llm`, AI gateway, guardrail) |
| Consumer | `product-reviews` → `frontend` (trải nghiệm khách) và **CDO** (Reliability/Performance: cần biết tầng AI đóng góp gì vào SLO tổng; Security: secret/egress) |
| Trạng thái | Draft — chờ CDO review |

## Mục đích

Chốt **hành vi cam kết** của tầng AI trong sản phẩm để CDO tính được SLO tổng và
người trực bất kỳ trụ nào cũng xử được sự cố AI. Hai sự cố BTC chắc chắn sẽ bơm
(flag có sẵn trong source):

- `llmRateLimitError` — llm trả **429** chập chờn.
- `llmInaccurateResponse` — llm trả **tóm tắt sai** cho product `L9ECAV7KIM`.

Luật chơi (RULES §8): **không tắt flag, không gỡ đường dây đọc flag** — chỉ làm hệ
chịu được. Contract này mô tả chính xác "chịu được" nghĩa là gì.

---

## INPUT — thứ tầng AI nhận

### 1. API interface (giữ nguyên chuẩn hiện có)

`product-reviews` gọi `llm` theo **OpenAI chat-completions API**:

```
POST http://llm:8000/v1/chat/completions
{ "model": "techx-llm", "messages": [...], "tools": [<database tool>] }
```

Flow 2 bước (như hiện tại, xem `techx-corp-platform/src/llm/README.md`):
1. Request 1 kèm database tool → llm trả `tool_calls` yêu cầu lấy review.
2. Request 2 kèm kết quả tool (list review của product) → llm trả tóm tắt.

Cấu hình qua env (`.env` / `.env.override`): `LLM_BASE_URL`, `LLM_MODEL`, `OPENAI_API_KEY`.
Nếu AIO chuyển sang LLM thật (OpenAI-compatible), **interface không đổi** — chỉ đổi env.

### 2. Thứ AIO cần từ CDO (input hạ tầng)

| Cần | Từ trụ | Chi tiết |
|---|---|---|
| Secret management | Security | `OPENAI_API_KEY` để trong K8s Secret (không hardcode, không commit); nếu dùng LLM ngoài: mở egress HTTPS tới đúng domain provider, còn lại chặn |
| Resource | Reliability/Perf | `llm` + `product-reviews`: requests/limits AIO đề xuất trong values file, CDO review khi merge chart |
| Cache backend | Reliability | Dùng chung valkey (hoặc 1 instance nhỏ riêng) cho cache tóm tắt — quyết định chung, ghi ADR |

## OUTPUT — hành vi cam kết (thứ CDO dựa vào)

### 1. Ngân sách độ trễ (bảo vệ SLO p95 < 1s của trang sản phẩm)

| Cam kết | Giá trị |
|---|---|
| Timeout mỗi lời gọi llm (từng bước trong flow 2 bước) | 800ms |
| Tổng ngân sách tóm tắt AI trong request trang sản phẩm | ≤ 2s; quá hạn → trả trang **không có tóm tắt** (khối AI là best-effort, render phần review thô trước) |
| Cache hit | Trả từ cache < 50ms; tóm tắt được cache theo `product_id` + phiên bản tập review, TTL 24h |

### 2. Xử lý lỗi — ma trận cam kết

| Lỗi từ llm | Hành vi gateway | Khách thấy gì |
|---|---|---|
| Timeout / 5xx | Retry tối đa 2 lần, exponential backoff + jitter (200ms → 400ms); có retry budget — tối đa 20% tổng lời gọi trong 5 phút được phép là retry | Tóm tắt từ cache, hoặc không có khối tóm tắt |
| **429 rate-limit** | **Không retry ngay** (retry mù vào 429 làm bão tệ hơn). Backoff theo `Retry-After` nếu có; vượt ngưỡng → mở circuit breaker | Cache / ẩn khối tóm tắt. **Không bao giờ** thấy lỗi đỏ |
| ≥ 5 lỗi liên tiếp hoặc error-rate 5 phút > 50% | **Circuit breaker mở**: trả fallback ngay không gọi llm; sau 60s vào half-open, thử 1 request probe; thành công → đóng mạch | Như trên |
| Response 200 nhưng nội dung đáng ngờ | Sang mục Guardrail bên dưới | — |

### 3. Guardrail — cam kết "không hiển thị tóm tắt sai lệch" (SLO cứng)

Mọi tóm tắt **phải qua faithfulness check trước khi render**:
- Đối chiếu tóm tắt với chính các review đầu vào (sentiment tổng + các claim chính
  phải có căn cứ trong review; pattern LLM-as-judge / rule-based hybrid).
- **Pass** → hiển thị. **Fail** → ẩn tóm tắt, hiện review thô, log
  `guardrail_block{product_id, reason}`.
- Nguyên tắc thiết kế: *thà thiếu tóm tắt còn hơn tóm tắt sai* — SLO cho phép
  best-effort về availability nhưng cấm sai lệch về nội dung.

### 4. Metrics tầng AI phát ra (CDO dùng được trong dashboard chung)

| Metric | Ý nghĩa |
|---|---|
| `ai_gateway_requests_total{outcome=ok\|timeout\|429\|5xx\|guardrail_block\|breaker_open}` | Sức khỏe tầng AI một cái nhìn |
| `ai_gateway_latency_seconds` (histogram) | Đóng góp của AI vào latency trang |
| `ai_cache_hit_ratio` | Hiệu quả cache (cả cost lẫn latency) |
| `ai_guardrail_block_total` | Số tóm tắt bị chặn — tăng đột biến = có thể flag `llmInaccurateResponse` đang bật |
| `ai_breaker_state` (0 đóng /1 half-open /2 mở) | Người trực nhìn là biết đang degrade |

> **⚠️ Lưu ý ánh xạ Metric thực tế của Tuần 1**:
> Trong Tuần 1, khi chưa chạy AI gateway độc lập, hệ thống sử dụng metric duy nhất là `app_ai_assistant_counter` để ánh xạ sức khỏe tầng AI:
> - `app_ai_assistant_counter{cache="hit"}`: Sử dụng để tính toán hiệu quả cache (tương đương `ai_cache_hit_ratio`).
> - `app_ai_assistant_counter{status="error"}`: Sử dụng để đếm số lỗi (tương đương `outcome=timeout|429|5xx`).
> - `app_ai_assistant_counter` (không tag): Tổng số lượt gọi AI thành công (`outcome=ok`).
> Toàn bộ 5 metric nâng cao trong bảng trên sẽ được triển khai đầy đủ ở Tuần 2-3 cùng với AI gateway riêng.


### 5. Runbook đi kèm (để CDO trực cũng xử được)

- `RB-LLM-429.md` — bão 429: xác nhận qua metrics → kiểm tra breaker đã mở chưa →
  không làm gì thêm nếu fallback đang phục vụ (by design) → ghi nhận vào incident.
- `RB-LLM-BADSUMMARY.md` — nghi tóm tắt sai: kiểm tra `guardrail_block_total` →
  nếu guardrail *không* chặn mà khách vẫn thấy sai → tắt render tóm tắt bằng **flag riêng
  của TF** (được phép tự thêm flag mới — RULES §8) → escalate AIO02 chỉnh guardrail.

## Failure modes tổng

| Tình huống | Hành vi |
|---|---|
| llm chết hẳn | Breaker mở, toàn bộ trang chạy không tóm tắt — **không ảnh hưởng SLO browse/checkout** |
| Cache backend chết | Gọi llm trực tiếp (chậm hơn, đắt hơn nhưng đúng); metric `ai_cache_hit_ratio` = 0 sẽ lộ ra ngay |
| Guardrail model chết | Fail-closed: không hiển thị tóm tắt (an toàn nội dung > tính năng) |

## Tiêu chí nghiệm thu

- [ ] Load test với flag `llmRateLimitError` bật (tự tái hiện trong môi trường dev bằng flag riêng): trang sản phẩm giữ p95 < 1s, 0 lỗi hiển thị cho khách.
- [ ] Test guardrail với product `L9ECAV7KIM` khi flag `llmInaccurateResponse` bật: tóm tắt sai bị chặn.
- [ ] 5 metrics trên xuất hiện trong Prometheus + panel Grafana.
- [ ] 2 runbook tồn tại, người CDO đọc và diễn tập được.
- [ ] Secret không nằm trong git (CDO Security xác nhận).
- [ ] ADR ký tên (bao gồm quyết định mock vs LLM thật, nếu đổi).
