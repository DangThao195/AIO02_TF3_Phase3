# Shopping Copilot — Đặc tả kỹ thuật (Spec)

| Trường | Giá trị |
|---|---|
| Version | 1.1.0 |
| Owner | **AIO02** (AIE — tầng AI trong sản phẩm) |
| Consumer | `frontend` (trải nghiệm khách) + CDO (Security/Reliability/Cost) |
| Trạng thái | Draft — cập nhật theo review (Bedrock, catalog thật, keyword-extract) |
| Backend LLM | **AWS Bedrock** (`us-east-1`) — chi phí trong trần AWS $300/tuần |

> Cập nhật v1.1 (theo review): chuyển LLM backend Groq → **Bedrock**; sửa ví dụ theo **catalog
> thật**; thêm bước **keyword-extract tiếng Anh + lọc giá ở tầng agent**; làm rõ **input filter
> cho review** (indirect injection); `max_iterations` **theo intent**. Mọi mục đối chiếu code
> thật trong [ai-engine/](ai-engine/).

---

## 1. Mục tiêu

Shopping Copilot là trợ lý mua sắm hội thoại, trả lời **grounded trên review + thông tin sản
phẩm thật**, giúp khách tìm sản phẩm và thêm vào giỏ — **không bao giờ** tự thanh toán, xóa giỏ,
hay đụng hạ tầng. Nguyên tắc: *thà từ chối/thiếu thông tin còn hơn bịa hoặc hành động vượt quyền.*

Ba intent lõi (v1):
1. **Tìm sản phẩm** — theo mô tả/danh mục/giá (Intent 1, NL search).
2. **Hỏi-đáp về sản phẩm** — chỉ dựa trên review thật (grounded Q&A).
3. **Thêm vào giỏ** — luôn qua Confirmation Gate.

---

## 2. Kiến trúc agent

Executor: [agent/agent_executor.py](ai-engine/src/ai_engine/agent/agent_executor.py) —
`ShoppingCopilot`. Framework-agnostic: `llm_step` + `run_tool` được inject (LangChain optional,
không phải hard dependency). Lớp vỏ an toàn (safety envelope) bọc quanh mọi planner:

```
user_message
   │
   ▼ scan_user_question()  ── injection/system-leak? → REFUSAL (không gọi model)
   ▼ vòng lặp ≤ max_iterations:
       llm_step(SYSTEM_PROMPT, transcript)
         ├─ final_answer → trả lời
         └─ tool_call → authorize() → run_tool() → append observation
   ▼ hết vòng lặp / exception → fallback thân thiện (không treo app)
```

- **Input filter TRƯỚC model** ([input_filter.py](ai-engine/src/ai_engine/aie/input_filter.py)).
- **Tool allowlist + confirmation gate** ([tools.py](ai-engine/src/ai_engine/agent/tools.py)).
- **try/except fallback** quanh LLM call — khách không bao giờ thấy lỗi đỏ.

---

## 3. Intent routing + NL search (Intent 1)

### 3.1 Thực trạng tool (đối chiếu code product-catalog)

`ProductCatalogService.SearchProducts` là **SQL LIKE substring** — chỉ khớp chuỗi ký tự trong
tên/mô tả, **không hiểu ngôn ngữ tự nhiên, không lọc giá**. Catalog thật là **~10 sản phẩm thiên
văn** (kính thiên văn, ống nhòm, lens kit…), phần lớn **tên tiếng Anh**.

> Hệ quả: đưa nguyên câu tiếng Việt "Tìm tai nghe chống ồn dưới 50 đô" vào `SearchProducts` sẽ
> trả **rỗng**. Đây là điểm reviewer nêu — spec v1.1 xử lý như dưới.

### 3.2 Luồng NL search chuẩn (bắt buộc)

Agent **KHÔNG** đưa nguyên câu người dùng vào tool. Thay vào đó:

1. **Trích keyword tiếng Anh** từ câu người dùng (bước LLM nhẹ hoặc rule) — ví dụ
   "kính thiên văn cho người mới dưới 200 đô" → keyword `telescope beginner`.
2. Gọi `search_products(keyword="telescope beginner")` — tool ghi rõ trong registry:
   *"RPC không lọc giá — lọc giá ở tầng agent"*
   ([tools.py:27-29](ai-engine/src/ai_engine/agent/tools.py)).
3. **Lọc giá ở tầng agent** sau khi có kết quả (price ≤ ngưỡng người dùng nêu).
4. Trả danh sách đã lọc, kèm lý do nếu rỗng ("không có SP nào dưới $X").

### 3.3 Ví dụ (đã sửa theo catalog thật)

| Câu người dùng | Keyword tool | Lọc agent | Kết quả |
|---|---|---|---|
| "Tìm kính thiên văn cho người mới bắt đầu" | `telescope beginner` | — | list telescope |
| "Ống nhòm dưới 100 đô" | `binocular` | price ≤ 100 | list đã lọc giá |
| "Lens kit chụp thiên văn" | `lens kit` | — | list lens |

> Ví dụ cũ ("tai nghe chống ồn dưới 50 đô", SKU `WHHD01`) **đã loại** vì không có trong catalog
> thiên văn. *(Cần BTC xác nhận danh sách SKU chính xác để khớp 100% khi viết test.)*

---

## 4. Guardrail & An toàn (defence in depth)

### 4.1 Input filter — hai bề mặt injection

| Bề mặt | Hàm | Xử lý |
|---|---|---|
| Câu hỏi chat (direct) | `scan_user_question()` | phát hiện injection/system-leak → **REFUSAL** (không gọi model) |
| **Nội dung review** (indirect) | `scan_reviews()` | **neutralise câu injection**, giữ review thật, redact PII |

> Reviewer đúng: review trả về từ tool là bề mặt indirect injection. Ở TF3 **`scan_reviews()`**
> quét review *trước khi* vào LLM ([input_filter.py:71](ai-engine/src/ai_engine/aie/input_filter.py)).
> **Chốt chặn cuối** vẫn là allow-list tool + confirmation gate: dù summary bị lèo lái, agent
> không thể tự checkout/charge/empty-cart.

### 4.2 Tool allowlist + hành động cấm tuyệt đối

Registry [tools.py](ai-engine/src/ai_engine/agent/tools.py) là **allowlist** — tool không có trong
danh sách bị **deny khi thực thi**. Ghi (write) vào giỏ **bắt buộc confirmation token**.

**FORBIDDEN_RPCS (hard-block trong code, không chỉ văn bản):**
`CheckoutService.PlaceOrder`, `PaymentService.Charge`, `CartService.EmptyCart`,
`FeatureFlagService.{Update,Create,Delete}Flag` (RULES §8).

### 4.3 Confirmation Gate (excessive-agency)

`add_to_cart` (WRITE) → `authorize()` chặn nếu chưa `confirmed` → UI hiện
`confirmation_prompt()` ("Bạn có muốn thêm N × SP … vào giỏ? [Xác nhận] [Hủy]") → chỉ thực thi
sau khi có token confirm. Test: [test_agent.py](ai-engine/tests/test_agent.py).

### 4.4 System prompt
[system_prompt.py](ai-engine/src/ai_engine/agent/system_prompt.py) cấm tiết lộ prompt/tool/config,
cấm làm theo mệnh lệnh nhúng, cấm checkout/pay/empty-cart. Excessive-agency denied ở prompt **AND**
code.

### 4.5 `max_iterations` theo intent
Mặc định `MAX_ITERATIONS = 3` (bảo vệ p95 SLO trang / chống reasoning loop —
[agent_executor.py:26](ai-engine/src/ai_engine/agent/agent_executor.py)).

> Reviewer đúng: intent "so sánh 2 SP" = search + 2×get_reviews = **đúng 3 vòng**, thêm quy đổi
> tiền tệ là vỡ. **v1.1: cho `max_iterations` theo intent** — `compare` = 5, còn lại giữ 3
> (`ShoppingCopilot(max_iterations=…)` đã nhận tham số, chỉ cần route theo intent).

---

## 5. LLM backend — AWS Bedrock (không dùng Groq)

Backend = **AWS Bedrock** (`us-east-1`). Chi phí **nằm trong trần AWS $300/tuần** (Cost
Explorer/Budgets) — giải quyết mối lo "chi phí ngoài hệ đo" và "dữ liệu ra bên thứ ba" (dữ liệu
không rời hạ tầng AWS). Giao tiếp qua AI Gateway (C4): timeout 800ms, retry budget, circuit
breaker, guardrail.

### 5.1 Route model (bảo vệ trần)

| Vai trò | Model | $/1K req* | Trạng thái access (acct 197826770971) |
|---|---|---|---|
| **Baseline** (tóm tắt review, Q&A thường, volume cao) | `amazon.nova-lite-v1:0` | ~$0.084 | ✅ **ACTIVE — đã test converse OK** |
| **Route heavy hiện tại** (tạm) | `amazon.nova-lite-v1:0` | ~$0.084 | ✅ ACTIVE |
| Nâng cấp heavy (đã có quyền) | `us.anthropic.claude-sonnet-4-5` | ~$4.65 | ✅ ACTIVE — reasoning mạnh cho câu khó/RCA |
| Nâng cấp heavy (rẻ hơn) | `amazon.nova-pro-v1:0` | ~$1.12 | ✅ ACTIVE |
| ~~Route heavy dự kiến~~ | ~~`us.anthropic.claude-opus-4-8`~~ | ~~~$23.3~~ | ❌ **AccessDenied** — chưa cấp quyền |

\* giả định ~800 in / 150 out tokens/request; giá thật từ AWS Price List API (2026-07-10, trừ
Claude 4.x là giá niêm yết). Cost meter tag theo `feature` + `model` (C5). Config: `LLM_MODEL` +
`LLM_MODEL_HEAVY` ([config.py](ai-engine/src/ai_engine/common/config.py)) — đổi model = đổi env.

> **Trạng thái Bedrock (đã kiểm tra thật):** Nova Lite/Pro, Sonnet 4.5, Haiku 4.5 đều gọi được.
> **Opus 4.8 bị AccessDenied** — cần request Model Access trên Bedrock Console nếu muốn dùng.
> Không cần "tạo" hạ tầng Bedrock (serverless) — chỉ cần model access + IAM `bedrock:InvokeModel`.

### 5.2 PII & bảo mật
Redact email/phone/credit-card **trước khi gửi Bedrock** (`_redact_pii`). Secret (AWS creds) chỉ
từ env/IAM role, không hardcode, không commit.

---

## 6. Đánh giá (Eval) & Definition of Done

### 6.1 Task-success eval — 20 câu hỏi mẫu ≥ 90%

**Task riêng có owner** (khắc phục comment: eval trước đây chỉ ở ghi chú tuần 3):
- Bộ 20 câu **xây từ catalog + review THẬT** trong hệ thống (không câu giả) để phản ánh đúng môi
  trường chấm. Phủ 3 intent: tìm SP, hỏi review, thêm giỏ (+ 1 nhánh so sánh, 1 nhánh injection).
- Chấm: intent đúng + tool đúng + câu trả lời grounded (không bịa) + guardrail chặn đúng.
- **DoD:** pass-rate ≥ 90%; regression gate CI (tụt >5% baseline → chặn deploy).

### 6.2 Fidelity eval (tóm tắt review)
Golden set + guardrail hybrid (rule-based + LLM-judge, fail-closed) — chi tiết
[AI_BASELINE_EVAL.md](ai-engine/AI_BASELINE_EVAL.md). Block tóm tắt sai trên `L9ECAV7KIM` khi flag
`llmInaccurateResponse` bật, 0 false-block trên tóm tắt đúng.

### 6.3 DoD tổng
- [ ] 3 intent lõi chạy được trên catalog thật.
- [ ] Eval 20 câu ≥ 90% (task có owner).
- [ ] Guardrail: chặn injection review + confirmation gate cho write (có test).
- [ ] Không rò rỉ system prompt (direct + indirect).
- [ ] LLM qua Bedrock, cost meter attribution ≥95% có tag `feature`.
- [ ] ADR ký tên cho quyết định model + trần ngân sách (RULES §7/§8).

---

## 7. Model catalog & giá (Bedrock us-east-1)

| Model | $/1M in | $/1M out | $/1K req | Vai trò |
|---|---|---|---|---|
| `amazon.nova-lite-v1:0` | 0.06 | 0.24 | $0.084 | **baseline** |
| `amazon.nova-micro-v1:0` | 0.03 | 0.14 | $0.049 | dự phòng rẻ nhất |
| `google.gemma-3-12b-it` | 0.09 | 0.29 | $0.116 | tham chiếu (gần "Gemini" nhất trên Bedrock) |
| `anthropic.claude-3-haiku-…` | 0.25 | 1.25 | $0.20 | tham chiếu Claude rẻ |
| `us.anthropic.claude-opus-4-8` | ~15 | ~75 | ~$23.3 | **route heavy** |

> Giá lấy thật từ AWS Price List API (acct 197826770971, us-east-1, 2026-07-10), trừ Opus 4.8 là
> giá niêm yết (API chưa expose on-demand cho account) — đối chiếu hoá đơn tuần đầu, sai số ≤5%
> (C5). **Gemini không có trên Bedrock** (là Google Vertex AI); gần nhất là `google.gemma-3`.

---

## 8. Failure modes

| Tình huống | Hành vi |
|---|---|
| LLM chết / timeout | AI Gateway fallback (cache/ẩn) → fallback thân thiện, không treo app |
| Tool trả rỗng (search) | agent giải thích "không tìm thấy", gợi ý nới điều kiện — không bịa SP |
| Injection trong review | `scan_reviews` neutralise, giữ review thật |
| Khách ép checkout/xóa giỏ | REFUSAL (prompt + code) — hard-block |
| Vượt `max_iterations` | trả REFUSAL/degraded, không loop vô hạn |
