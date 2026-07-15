# TF3 — AIOps Problem Statement (Phase 3: TechX Corp Service Takeover)

> Tổng hợp từ đề bài (`phase3/README.md`, `phase3/RULES.md`) và nghiên cứu thiết kế
> tham chiếu Capstone03 (`AIOPS_ARCHITECTURE_AND_RUNBOOK.md`, `aiops_pipeline_design.md`,
> `AIOPS_REMEDIATION_BLUEPRINT.md`). Chi tiết kiến trúc: [AI-ENGINE-ARCHITECTURE.md](AI-ENGINE-ARCHITECTURE.md) ·
> Danh mục sự cố: [AIOPS-INCIDENT-CATALOG.md](AIOPS-INCIDENT-CATALOG.md) · Backlog: [ai-engine/BACKLOG-aiops.md](ai-engine/BACKLOG-aiops.md) ·
> Kinh nghiệm & tham số vận hành: [AIOPS-EXPERIENCE-PLAYBOOK.md](AIOPS-EXPERIENCE-PLAYBOOK.md)

## 1. Bài toán (từ đề bài)

Tiếp quản một sản phẩm e-commerce AI **đang chạy thật, không hoàn hảo** trên Kubernetes/EKS
(namespace `techx-tf3`): ~25 microservices, Kafka, PostgreSQL, Valkey, tính năng AI review-summary,
observability đầy đủ (Prometheus / Jaeger / OpenSearch). Vận hành như kỹ sư thật: tự đánh giá,
ưu tiên, giữ SLA/SLO trong ngân sách, sống sót qua các sự cố do BTC bơm vào, và bảo vệ mọi quyết định
(ADR, postmortem, Ops Review, Service Health Readout).

**Trụ AI (AIO group) có 2 hướng:**
- **AIOps — dùng AI để vận hành hệ thống:** phát hiện bất thường đa tín hiệu (latency, error rate,
  saturation, queue lag, cost) + vòng tự động hoá khép kín
  **Detect → Safety-check (dry-run / blast-radius) → Act → Verify qua telemetry → Rollback/Escalate**.
  Mở rộng: RCA liên dịch vụ, dự báo capacity/cost, phát hiện drift.
- **AIE — AI trong sản phẩm:** làm cứng review-summary (faithfulness eval, fallback, guardrails
  chống prompt-injection/PII, tối ưu cost/latency) + trợ lý agentic tool-calling có RAG grounding.

**Ràng buộc cứng (điều kiện loại):** sự cố được bơm qua flagd/OpenFeature — **không được** tắt,
trỏ lại, hay refactor bỏ đường đọc flag / cơ chế bơm sự cố. Điểm yếu cấu hình thật thì sửa tận gốc;
sự cố bơm vào thì phải *sống sót*, không phải *tắt đi*.

## 2. Lời giải của TF3 — ánh xạ năng lực

Kiến trúc 2 tầng phát hiện (học từ tham chiếu, đã hiện thực trong `ai-engine/src/ai_engine/aiops/`):

| Vòng khép kín | Module TF3 | Ghi chú |
|---|---|---|
| Detect (critical) | `detector_burnrate.py` | SLO multi-window burn-rate → kích hoạt pipeline RCA |
| Detect (warning) | `detector_latency.py`, `detector_anomaly.py` | Rolling z-score + IsolationForest → chỉ cảnh báo Slack |
| Correlate / RCA | `correlator.py`, `local_matcher.py`, `rca_assistant.py` | Gom alert liên dịch vụ; đối chiếu Jaeger trace + log; LLM chẩn đoán |
| Grounding (RAG) | **Bedrock KB — `terraform/`** | INCIDENT_HISTORY.md (8 sự cố INC-1..8) embed bằng Titan v2, vector index OpenSearch Serverless; `rca_assistant` retrieve để so khớp triệu chứng với playbook lịch sử |
| Safety-check / Act | `action_policy.py`, `approval.py`, `remediation.py` | Allow-list hành động, blast-radius, nút approve trên Slack (`slack_client.py`) |
| Verify / Rollback | `verify_loop.py` | Xác nhận qua telemetry sau hành động; rollback/escalate nếu không hồi phục |
| Audit | `audit_log.py`, `audit_report.py`, `alert_emitter.py` | Bằng chứng cho Ops Review / Readout |

**Tri thức lịch sử làm nền cho chẩn đoán:** 8 sự cố trong `phase3/onboarding/INCIDENT_HISTORY.md`
cho LLM biết cả *hành động đúng* (scale product-catalog/accounting, rollout restart recommendation,
force-close-breaker) lẫn *hành động cấm* (không restart valkey-cart INC-2, không restart currency INC-8)
— đây chính là dữ liệu safety-check quan trọng nhất của vòng remediation.

**AIE giữ nguyên AI Gateway Pattern:** mọi chính sách LLM (cache → circuit breaker → timeout →
guardrail → fallback, cost metering) nằm tập trung trong `ai-engine/src/ai_engine/aie/gateway.py`;
microservice (`product-reviews`) chỉ trỏ `LLM_BASE_URL` vào gateway. Không port kiểu monolith của
tham chiếu (cache inline theo product_id, retry tự chế, fallback copy-paste, guardrail trộn vào handler).

## 3. Tiêu chí thành công

1. Sống sót qua các sự cố bơm INC-4/INC-7-class (429, breaker kẹt) bằng fallback/containment — flagd path còn nguyên.
2. MTTD/MTTR đo được qua audit log; mỗi hành động remediation có evidence + approval trail.
3. LLM Diagnostic trích dẫn đúng playbook lịch sử (KB retrieval) thay vì suy đoán tự do.
4. Chi phí AI hiển thị qua cost showback (`cost_meter.py` / `cost_report.py`), trong ngân sách `onboarding/BUDGET.md`.
