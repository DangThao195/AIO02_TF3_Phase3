# ADR 0009: Sử dụng App-level Evaluator — Không tích hợp AWS Bedrock Guardrail

> [!NOTE]
> * Trạng thái: Đã phê duyệt (Approved)
> * Tác giả: Thịnh (AIE1) và Khoa (Leader AIE1)
> * Ngày tạo: 2026-07-27
> * Ngày cập nhật: 2026-07-27
> * Dự án: AIE1 - Tối ưu & Vận hành Tầng AI (Task Force 1 — Ticket S4)

---

## 1. Bối cảnh

Audit CDO (xem `docs/reports/product-reviews-readonly-audit-2026-07-26.md`) xác nhận:

- Guardrail `shopping-copilot-guardrail` tồn tại ở `us-east-1`, nhưng Product Reviews **không cấu hình Guardrail ID** và **không có quyền `bedrock:ApplyGuardrail`**.
- IAM Inline Policy `techx-tf3/product-reviews-bedrock` hiện chỉ cấp `bedrock:InvokeModel` cho 2 model Nova Lite và Nova Micro.

Audit yêu cầu làm rõ: nếu App-level Evaluator đã đủ, hãy văn bản hóa quyết định đó và giữ nguyên IAM.

---

## 2. Quyết định

**Product Reviews sử dụng bộ lọc an toàn và fidelity evaluator tự phát triển ở tầng ứng dụng. Không tích hợp AWS Bedrock Guardrail (`shopping-copilot-guardrail`).**

IAM Inline Policy `techx-tf3/product-reviews-bedrock` được giữ nguyên tối giản, chỉ cấp `bedrock:InvokeModel`.

---

## 3. Lý do

### 3.1 App-level Evaluator đã đáp ứng đầy đủ yêu cầu Mandate #6

Hệ thống đã triển khai pipeline bảo mật 4 tầng hoàn chỉnh tại tầng ứng dụng (xem ADR 0003):

| Tầng | Thành phần | Vị trí |
|:---|:---|:---|
| 1 | User Input Guardrail — Regex 30+ patterns | `guardrails/input_filter.py` |
| 2 | Review Content Guardrail — quét từng review từ DB | `guardrails/input_filter.py` |
| 3 | Anti-Hallucination — System Prompt constraint + keyword intercept | `product_reviews_server.py` |
| 4 | Output Guardrail — PII/secret redaction | `guardrails/output_filter.py` |

Kết quả eval đo được (artifact `repro/artifacts/security_false_block_runtime_bedrock_v2_20260727.json`):
- Block Rate: **100%** (Bedrock runtime, sau khi tối ưu)
- Review Content Guard Rate: **100%**

Fidelity Evaluator (LLM-as-Judge) chạy runtime trên mọi candidate response:
- Pass Rate: **100%** (10/10 sản phẩm mentor benchmark, artifact `repro/artifacts/fidelity_eval_20260727T162702Z.json`)
- Judge-Human Agreement: **95.24%** (artifact `repro/artifacts/judge_human_agreement_20260727T140206Z.json`)

### 3.2 Bedrock Guardrail không mang lại giá trị tăng thêm đủ để justify chi phí và độ trễ

- Regex + LLM-as-Judge đã xử lý được toàn bộ attack categories trong dataset (injection, jailbreak, encoding evasion, PII, unauthorized action).
- `bedrock:ApplyGuardrail` tăng thêm ~200ms latency mỗi request — vi phạm SLO p95 khi kết hợp với candidate + judge call.
- VPC của cluster ở `ap-southeast-1`, Bedrock Guardrail endpoint ở `us-east-1` — mọi call đều qua NAT public, không thể dùng private VPC endpoint.
- Fail-open behavior của Bedrock Guardrail (ADR 0003 §3.1) đồng nghĩa với việc ngay cả khi bật, hệ thống vẫn phải có tầng Regex làm safety net.

### 3.3 Nguyên tắc Least Privilege — không cấp quyền không dùng đến

Cấp `bedrock:ApplyGuardrail` trong khi không có code path nào gọi API đó là vi phạm nguyên tắc tối thiểu quyền (Least Privilege). Giữ nguyên IAM hiện tại là đúng.

---

## 4. Phạm vi áp dụng

Quyết định này chỉ áp dụng cho service **Product Reviews** (`techx-tf3/product-reviews-bedrock`).

Các service khác (ví dụ: shopping-copilot) có thể có yêu cầu khác và được phép tích hợp `shopping-copilot-guardrail` theo nhu cầu riêng.

---

## 5. Điều kiện xem xét lại

Quyết định này cần được xem xét lại nếu:

- Block Rate của App-level Evaluator giảm xuống dưới 95% trong bộ eval định kỳ.
- Xuất hiện attack vector mới không thể xử lý bằng Regex và LLM-as-Judge.
- SLO p95 được nới rộng, cho phép bổ sung ~200ms latency từ Bedrock Guardrail.
- Cluster được migrate sang `us-east-1` và có thể dùng private VPC endpoint cho Bedrock.

---

## 6. Liên kết tham chiếu

| Tài liệu | Nội dung |
|:---|:---|
| `docs/adr/0003-AI-TRUST-SAFETY-GUARDRAILS.md` | Thiết kế chi tiết 4-tầng guardrail |
| `docs/reports/product-reviews-readonly-audit-2026-07-26.md` | Audit CDO xác nhận IAM và Guardrail status |
| `docs/tasks/JIRA_TODO_SPECIAL.md` (Ticket S4) | Yêu cầu văn bản hóa quyết định này |
| `repro/artifacts/fidelity_eval_20260727T162702Z.json` | Bằng chứng Pass Rate 100% |
| `repro/artifacts/judge_human_agreement_20260727T140206Z.json` | Bằng chứng Agreement Rate 95.24% |
