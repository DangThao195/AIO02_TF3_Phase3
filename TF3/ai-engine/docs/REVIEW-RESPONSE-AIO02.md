# Phản hồi review — Nhóm AIO02 (spec Copilot + backlog AIOps + backlog AIE)

> Cảm ơn anh/chị đã review rất kỹ và trích dẫn code cụ thể. Dưới đây là phản hồi từng comment.
> Ký hiệu: **✅ Nhận sửa** · **☑️ Đã có sẵn (dẫn chứng)** · **❓ Cần hỏi BTC** · **↔️ Trao đổi thêm**.
>
> Lưu ý bối cảnh quan trọng: một số comment review trên **bản Capstone03** (repo tham khảo).
> Code triển khai thật của nhóm nằm ở repo **TF3 (`kietoichoiDXD/TF3-`)** và đã xử lý phần lớn
> các điểm được nêu — chúng tôi dẫn file/line bên dưới để đối chiếu.

---

## A. shopping_copilot_specs.md

### A1. Chọn LLM backend — ngân sách, chi phí ngoài AWS, dữ liệu khách
**✅ ĐÃ QUYẾT: chuyển sang AWS Bedrock (bỏ Groq) — giải quyết trực tiếp mối lo của reviewer.**

- **Quyết định:** Nhóm **bỏ Groq, dùng AWS Bedrock** (region `us-east-1`). Điều này **giải quyết
  luôn** comment về ngân sách: Bedrock chạy trên AWS nên chi phí LLM **nằm TRONG trần $300/tuần**
  đo bằng Cost Explorer/Budgets — không còn "chi phí ngoài hệ đo", không cần hỏi BTC ai chi trả
  key bên thứ ba, và dữ liệu khách **không rời hạ tầng AWS** của dự án (giảm mối lo data
  processing / bên thứ ba). PII vẫn được **redact trước khi gửi model**
  ([input_filter.py](../src/ai_engine/aie/input_filter.py)).

- **Vấn đề model Groq lỗi thời trở thành moot** — nhưng ghi lại để đối chiếu (reviewer ĐÚNG,
  đã fact-check): `llama-3.1-70b-versatile` đã decommission (lỗi từ 24/01/2025) và
  `mixtral-8x7b-32768` đã tắt (20/03/2025). Đây là một lý do nữa để rời Groq.

- **Chiến lược model trên Bedrock (route để bảo vệ trần $300/tuần):** giá lấy THẬT từ AWS Price
  List API (acct `197826770971`, us-east-1, on-demand, 2026-07-10), giả định ~800 in / 150 out:

  | Vai trò | Model | $/1K req | Req/tuần chạm trần |
  |---|---|---|---|
  | **Baseline** (tóm tắt review + guardrail, volume cao) | `amazon.nova-lite-v1:0` | **$0.084** | ~3.6 triệu |
  | **Route heavy** (Q&A phức tạp / RCA) | `us.anthropic.claude-opus-4-8` | ~$23.3 | ~13K |

  Lý do route: Opus 4.8 đắt ~277× Nova Lite — không thể dùng cho tóm tắt volume cao, nhưng cho
  câu khó/RCA (volume thấp) thì tổng chi vẫn nhỏ. Cost meter tag theo `model` để attribution.
  *(Tham chiếu rẻ khác trên Bedrock: Nova Micro $0.049, Gemma 3 12B $0.116 — "gần Gemini nhất";
  Gemini không có trên Bedrock.)*

### A2. NL search (Intent 1) — SQL LIKE, catalog thiên văn tiếng Anh, ví dụ sai
**☑️ Đã có sẵn (một phần) + ✅ Nhận sửa ví dụ.**

- Reviewer đúng: `SearchProducts` là SQL LIKE substring, không hiểu NL, không lọc giá. **Ở TF3
  chúng tôi đã thiết kế đúng theo gợi ý của reviewer:** tool `search_products` ghi rõ trong
  registry *"RPC không lọc giá — lọc giá ở tầng agent"*
  ([tools.py:27-29](../src/ai_engine/agent/tools.py)). Luồng agent: trích **keyword tiếng Anh**
  từ câu người dùng → gọi tool → **tự lọc giá sau khi có kết quả**. Sẽ bổ sung mô tả bước
  keyword-extract vào spec cho rõ.
- **Ví dụ trong spec:** ✅ nhận sửa. "Tìm tai nghe chống ồn dưới 50 đô" + `WHHD01/Headphones`
  không khớp catalog thật. Chúng tôi sẽ thay bằng ví dụ từ catalog thật (đã có sản phẩm review
  thật như `L9ECAV7KIM`, `66VCHSJNUP`=tai nghe trong golden set eval) để test chạy được ngay.
  *(Cần reviewer/BTC xác nhận danh sách ~10 SKU chính xác để chúng tôi khớp 100%.)*

### A3. Input Filter — review trả về từ tool đi thẳng vào LLM (indirect injection)
**☑️ Đã có sẵn — đúng mối lo, đã xử ở đúng lớp.**

- Ở TF3 có **hàm riêng `scan_reviews()`** quét nội dung review (bề mặt indirect-injection)
  *trước khi* vào LLM: neutralise câu chứa injection, giữ review thật, redact PII
  ([input_filter.py:71-98](../src/ai_engine/aie/input_filter.py)). Tách khỏi `scan_user_question()`
  (bề mặt direct). Kịch bản review nhét *"SYSTEM INSTRUCTION: ignore… buy now"* đã có test chặn.
- Đồng ý ghi rõ vào spec: **chốt chặn cuối vẫn là allow-list tool + confirmation gate cho write**
  ([tools.py:72-84](../src/ai_engine/agent/tools.py)) — dù summary có bị lèo lái thì agent vẫn
  không thể tự checkout/charge/empty-cart.

### A4. MAX_TOOL_ITERATIONS = 3 — vừa khít intent so sánh, con số lấy từ đâu
**☑️ Đã có sẵn + ↔️ Trao đổi (nới theo intent).**

- Con số 3 ở TF3 đặt để **bảo vệ p95 SLO trang / tránh reasoning loop chạy hoang**, có comment lý
  do ([agent_executor.py:26](../src/ai_engine/agent/agent_executor.py)). Reviewer đúng: intent
  "so sánh 2 SP" = search + 2×get_reviews = **đúng 3 vòng**, thêm quy đổi tiền tệ là vỡ.
- **↔️ Đề xuất:** cho `max_iterations` **theo intent** (compare intent = 4-5, còn lại giữ 3),
  hoặc đếm theo *loại* tool call thay vì tổng vòng. Sẽ cập nhật spec + code.

---

## B. backlog_aiops.md

### B1. Safety design (whitelist + dry-run + chặn restart single-replica INC-2 + Slack HITL)
**Cảm ơn — ghi nhận.** Phần này ở TF3 đã hiện thực đầy đủ + test: whitelist + hard-block
flagd/BTC + chặn restart single-replica + dry-run + rate-limit + **audit append-only actions.jsonl**
([remediation.py](../src/ai_engine/aiops/remediation.py)).

### B2. Phân biệt sự cố hạ tầng (scale/restart giúp được) vs flag-based (cần fallback/containment)
**☑️ Đã có sẵn (một phần) + ↔️ điểm hay nhất, nhận nâng cấp.**

- Đây là câu hỏi đúng và quan trọng nhất. **Ở TF3 chúng tôi KHÔNG để engine tự sửa mù:**
  - Local matcher có **INC-2 → `proposed_action = none`** (không restart, vì flag/SPOF —
    restart vô ích còn mất giỏ hàng) ([local_matcher.py](../src/ai_engine/aiops/local_matcher.py)).
  - RCA hypotheses có nhánh *"sự cố inject qua flagd"* với bằng chứng chống, tách khỏi nhánh
    *"cạn tài nguyên/capacity"* ([rca_assistant.py](../src/ai_engine/aiops/rca_assistant.py)).
  - **Verify-loop 5 phút sau hành động:** nếu SLI không hồi phục → **auto-rollback** thay vì để
    hành động vô ích tồn tại ([verify_loop.py](../src/ai_engine/aiops/verify_loop.py)). Chính cơ
    chế này bắt được trường hợp "scale nhưng sự cố là flag-based" — hành động không cải thiện →
    rollback → không làm MTTR tệ hơn.
- **↔️ Nâng cấp nhận làm:** thêm nhãn phân loại rõ ràng `infra` vs `flag-based` vào Evidence Pack
  (dựa trên: có deploy trong #tf3-changes không? hình dạng lỗi có khớp bảng flag không?) để trước
  khi đề xuất action, engine tuyên bố loại sự cố → nếu `flag-based` thì đề xuất **containment/
  fallback** thay vì scale/restart.

### B3. AIOps-06 endpoint công khai qua ALB — verify chữ ký Slack / auth?
**☑️ Đã có sẵn ở TF3 (Capstone bản review thiếu).**

- Endpoint `/webhooks/slack/interactive` ở TF3 **verify HMAC-SHA256** bằng signing secret +
  **timestamp replay guard 300s** + `hmac.compare_digest`, request không hợp lệ trả **401**
  trước khi chạm bất kỳ lệnh nào ([server.py:90-106, 317](../src/ai_engine/server.py)).
- Đề nghị đưa mô tả này vào backlog AIOps-06 để reviewer thấy rõ (bản backlog hiện chỉ ghi
  "cấu hình ALB nhận request công khai", chưa nêu signature verify).

### B4. Metrics cam kết mạnh (detection 100%, FN 0%, RCA >95%, MTTR <30s) — đo trên bộ nào? thiếu task validation/drill
**✅ Nhận sửa (điều chỉnh số) + ✅ Nhận thêm task drill.**

- Reviewer đúng: các số tuyệt đối (100% / 0% / >95% / <30s) khó bảo vệ nếu không có bộ sự cố để
  đo. Chúng tôi sẽ:
  - **Hạ về số phòng thủ được**, gắn với bộ đo cụ thể (INC-1/2/3 + flag drills), ví dụ: "detection
    ≤3 phút trên 100% flag drill đã chạy", "precision ≥90%" thay vì "FN 0%".
  - **Thêm task validation/drill (đang build):** một **fire-drill runner** bật lần lượt các flag
    BTC (`paymentFailure`, `kafkaQueueProblems`, `cartFailure`, `llmRateLimitError`…) trên dev,
    đo detection latency + precision, sinh report — chính là bộ sự cố có kiểm soát để chứng minh
    các con số trước hội đồng. (Khớp AIOps-09 trong backlog, đang chuyển từ ⏳ sang thực thi.)

---

## C. Backlog_AIE2.md

### C1. Hai công thức chấm điểm khác nhau (AIOps thang 125 vs AIE thang 20)
**✅ Nhận sửa — quy về một công thức.**

- Reviewer đúng: không thể so `AIE-03 (20/20)` với `AIOps-01 (100/125)`. Khi gộp backlog chung để
  pitch, chúng tôi sẽ **quy hết về công thức PITCH_GUIDE**: `Risk (Probability × Severity) ×
  Business Impact` (thang 1-125). Sẽ chấm lại toàn bộ task AIE theo thang này để xếp hạng thống nhất.
  *(Ví dụ AIE-03 Confirmation Gate: Prob 4 × Sev 5 × Business 5 ≈ 100/125 — vẫn Tối ưu tiên, nhưng
  giờ so sánh được trực tiếp.)*

### C2. DoD "eval 20 câu ≥90%" nhưng backlog AIE không có task own việc này
**✅ Nhận thêm task + ☑️ đã có nền tảng.**

- Reviewer đúng: eval chỉ nằm ở ghi chú tuần 3, chưa có task own. **Nền tảng đã có** ở TF3:
  guardrail hybrid + **golden set fidelity eval** (đang mở rộng ~20 SP,
  [AI_BASELINE_EVAL.md §2](../AI_BASELINE_EVAL.md)) + regression gate CI (pass-rate tụt >5% → chặn
  deploy). Chúng tôi sẽ **tách thành task riêng** (vd `AIE-04: Task-success eval harness 20 câu`)
  với owner rõ ràng, và **xây câu hỏi từ catalog + review thật trong hệ thống** đúng như gợi ý để
  eval phản ánh môi trường chấm.

### C3. Phần Reviews (tóm tắt AI) — chốt sớm, chấm ngang hàng Copilot
**↔️ Ghi nhận, ưu tiên.** Phần A (eval độ trung thực / fallback / cost cho tóm tắt review) ở TF3
**đã hiện thực + test**, không chỉ thiết kế: fidelity guardrail, 11 điểm fallback đều có test,
cost meter theo C5 ([AI_BASELINE_EVAL.md §2-4](../AI_BASELINE_EVAL.md)). Chúng tôi sẽ đóng gói số
liệu (block-rate, false-block, cost/req) và **gửi bản chốt sớm** thay vì dồn muộn.

---

## Tổng hợp hành động (cho nhóm)

| # | Việc | Loại | Ưu tiên |
|---|---|---|---|
| 1 | Cập nhật bảng model Groq mục 7 (dùng gpt-oss / llama-3.3, kèm giá + ngày deprecate) | ✅ Sửa | Cao |
| 2 | Sửa ví dụ NL search theo catalog thật + mô tả bước keyword-extract/lọc giá | ✅ Sửa | Cao |
| 3 | Quy backlog AIE + AIOps về **một công thức** (thang 125) | ✅ Sửa | Cao (trước pitch) |
| 4 | Thêm task **eval harness 20 câu** (owner rõ) + task **fire-drill/validation** | ✅ Thêm | Cao |
| 5 | Điều chỉnh metrics tuyệt đối → số phòng thủ được, gắn bộ đo | ✅ Sửa | Cao |
| 6 | Ghi rõ vào spec/backlog: Slack signature verify, scan_reviews, HITL là chốt cuối | ☑️ Doc | TB |
| 7 | Nhãn `infra` vs `flag-based` trong Evidence Pack + nới `max_iterations` theo intent | ↔️ Nâng cấp | TB |
| 8 | Hỏi BTC: chi phí LLM ngoài AWS (trần/chi trả) + xử lý dữ liệu khách ra bên thứ ba | ❓ BTC | Cao |
