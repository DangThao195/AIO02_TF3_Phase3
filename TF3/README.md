# TF3 — AI Engine & Bộ Contract (AIO02 ↔ CDO01/CDO02)

> **Đối tượng đọc:** thành viên TF3 (AIO02, CDO01, CDO02) và mentor.
> **Chủ sở hữu tài liệu:** AIO02 (trụ AI). Mọi thay đổi contract phải qua PR + review của consumer.

## TF3 là ai, làm gì

| Nhóm | Trụ | Vai trò trong bộ contract này |
|---|---|---|
| **AIO02** | Trụ AI (AIOps + AIE) | Xây và vận hành AI engine; producer của C2, C3, C5, C6; owner C4 |
| **CDO01** | 2 trụ core (chọn khi draft) | Consumer alert/report; provider hạ tầng observability (C1) |
| **CDO02** | 2 trụ core còn lại | Consumer alert/report; provider hạ tầng observability (C1) |
| Cả TF | Auditability (luân phiên) | Consumer C6 (audit trail mọi hành động AI) |

## AI engine gồm 2 luồng

1. **AIOps — dùng AI vận hành hệ thống:** phát hiện bất thường trên metrics/logs/traces,
   gom nhiễu thành incident, hỗ trợ tìm nguyên nhân, gợi ý khắc phục (có approval gate).
2. **AIE — AI trong sản phẩm:** giữ tính năng tóm tắt review AI (`product-reviews` → `llm`)
   **đúng, an toàn, chịu lỗi và trong ngân sách**. SLO ràng buộc: *"không được hiển thị
   tóm tắt sai lệch cho khách"* (xem `onboarding/SLO.md`).

Kiến trúc chi tiết: [AI-ENGINE-ARCHITECTURE.md](AI-ENGINE-ARCHITECTURE.md).

## Bản đồ contract

Mỗi contract định nghĩa rõ **INPUT** (AIO cần gì từ CDO / hệ thống) và **OUTPUT**
(AIO trả lại gì cho CDO), kèm schema, SLA, failure mode và tiêu chí nghiệm thu.

| # | Contract | Hướng | Tóm tắt 1 dòng |
|---|---|---|---|
| [C1](contracts/C1-telemetry-access.md) | Telemetry Access | **CDO → AIO** | AIO cần đọc Prometheus/OpenSearch/Jaeger ổn định; CDO cam kết retention + naming |
| [C2](contracts/C2-anomaly-alert-event.md) | Anomaly / Alert Event | **AIO → CDO on-call** | AI engine phát alert đã khử nhiễu, theo burn-rate SLO, schema JSON cố định |
| [C3](contracts/C3-rca-report.md) | RCA Evidence Pack | **AIO → cả TF** | Khi có incident, AIO tự động gom bằng chứng thành báo cáo RCA nháp trong 30 phút |
| [C4](contracts/C4-llm-serving.md) | LLM Serving & Guardrail | **AIE ↔ product-reviews** | Cam kết hành vi của tầng AI sản phẩm: timeout, retry, 429, guardrail, fallback |
| [C5](contracts/C5-ai-cost-report.md) | AI Cost Report | **AIO → CDO (Cost)** | Showback chi phí AI theo token/request, báo cáo tuần, cảnh báo vượt ngân sách |
| [C6](contracts/C6-remediation-audit.md) | Remediation & Audit Trail | **AIO → CDO (Auditability)** | Mọi hành động AIOps tự động đều có approval gate + audit log truy được về người |

## Nguyên tắc chung cho mọi contract

1. **Versioning:** mỗi contract có `version` (semver). Đổi schema = tăng minor;
   đổi ngữ nghĩa/phá tương thích = tăng major + báo trước ≥ 2 ngày làm việc ở standup.
2. **Ký tên:** mỗi thay đổi contract đi kèm ADR ký tên (theo RULES §7, §8).
3. **Sự cố do BTC bơm (flagd) không được tắt** — contract chỉ mô tả cách *chịu đựng*
   (fallback, retry, containment), không bao giờ mô tả cách vô hiệu hóa cơ chế flag.
4. **Không đo được = không tồn tại:** mọi cam kết SLA trong contract phải có
   metric/dashboard tương ứng trong Grafana.

## Nguồn tham khảo đã dùng khi thiết kế

- Google SRE Workbook — [Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) (multiwindow, multi-burn-rate)
- [Prometheus Alertmanager webhook schema](https://prometheus.io/docs/alerting/latest/configuration/) (nền cho schema C2)
- [SoundCloud — Alerting on SLOs like Pros](https://developers.soundcloud.com/blog/alerting-on-slos/), [Datadog — Burn rate](https://www.datadoghq.com/blog/burn-rate-is-better-error-rate/)
- [OpenAI Cookbook — How to implement LLM guardrails](https://developers.openai.com/cookbook/examples/how_to_use_guardrails)
- [Handle 429 Errors in Production LLM Applications](https://www.getmaxim.ai/articles/handle-429-errors-in-production-llm-applications/), [LLM Error Handling & Fallback Strategies](https://www.buildmvpfast.com/blog/building-with-unreliable-ai-error-handling-fallback-strategies-2026)
- FinOps Foundation — [FinOps for AI](https://www.finops.org/wg/finops-for-ai-overview/), [GenAI Cost & Usage Tracker](https://www.finops.org/wg/how-to-build-a-generative-ai-cost-and-usage-tracker/)
- [Traceloop — Track LLM token usage & cost per user](https://www.traceloop.com/blog/from-bills-to-budgets-how-to-track-llm-token-usage-and-cost-per-user)
- [Splunk — AIOps Explained](https://www.splunk.com/en_us/blog/learn/aiops.html), [BigPanda — AIOps anomaly detection](https://www.bigpanda.io/blog/aiops-anomaly-detection-incident-resolution/)
