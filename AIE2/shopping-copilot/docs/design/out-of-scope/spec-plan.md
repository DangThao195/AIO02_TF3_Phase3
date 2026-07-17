# Spec Writing Roadmap — Shopping Copilot v3.2

> Based on `docs/design/agentic_design.md` | **Priority:** P0 > P1 > P2

## Phase 1 — Core Architecture (P0)

| Spec | File | Depends on | Why now |
|---|---|---|---|
| **State Design** | `docs/design/state_design.md` | — | Mọi node đều dùng ShoppingState |
| **Planner** (Intent Parser + TGB) | `docs/design/planner_design.md` | State | Layer 1 + 2 của planner-centric flow |
| **Executor** (DAG Runner + Reflection) | `docs/design/executor_design.md` | State, Planner | Core execution engine |

## Phase 2 — Response & Safety (P1)

| Spec | File | Depends on | Why now |
|---|---|---|---|
| **Response Verifier** (Template-First) | `docs/design/verifier_design.md` | State, Executor | Template-first strategy |
| **HallucinationGuard + FallbackGenerator** | `docs/design/hallucination_design.md` | State, Verifier | Output integrity |
| **Gate Layer** (5 Nova Lite gates) | `docs/design/gate_layer_design.md` | State | 5 gate types — component mới nhất |

## Phase 3 — Integration & Production (P2)

| Spec | File | Depends on | Why now |
|---|---|---|---|
| **Write + Confirm Flow** | `docs/design/confirm_design.md` | State, Executor | HMAC stateless confirm |
| **System Prompts** (TGB + Verifier) | `docs/design/prompt_design.md` | Planner, Verifier | Prompt quyết định quality |
| **Cache Strategy** (Redis 3 DB) | `docs/design/cache_design.md` | State | Production requirement |
| **Resource Limits & Guardrails** | `docs/design/resource_limits_design.md` | Executor | Production safety |
| **Observability Metrics** | `docs/design/observability_design.md` | — | Dashboards + SLO tracking |
| **API Server** | `docs/design/api_design.md` | State | FastAPI endpoints |
| **Configuration & Env** | `docs/design/config_design.md` | — | .env + secrets |
| **Tool specs** (cart, review, checkout, order...) | `docs/design/tools/*.md` | State | Mỗi tool 1 spec (search đã có) |

## Phân công gợi ý

- **AIO02 core**: Planner, Executor, Gate Layer, Prompts (kiến trúc AI)
- **AIO02 + CDO**: Cache, Observability, Resource Limits (production integration)
- **Cả team review**: State Design (nền tảng chung)

> **Nguyên tắc:** Mỗi spec ≤ 1 trang A4, tập trung vào input/output/flow, không lặp lại agentic_design.md. Chỉ detail hoá phần chưa đủ để implement.
