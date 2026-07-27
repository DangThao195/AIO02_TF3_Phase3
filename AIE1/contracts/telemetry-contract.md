# AIE1 Telemetry Contract

Owner: AIO02 / AIE1
System: TechX Corp `product-reviews`
Scope: Metrics, traces, logs, and runtime signals emitted by the AIE1 product-review service and its fidelity-evaluation flow.
Mandate alignment: `mandates/MANDATE-06-ai-trust-safety.md`

## 1. Purpose

This document defines the telemetry that AIE1 actually emits or relies on today.
It replaces the copied AIE2 shopping-copilot telemetry contract.

AIE1 does not currently expose the copied `copilot_*` metric family.
The current AIE1 telemetry is centered on:
- gRPC `product-reviews` service behavior
- review counters
- AI assistant request counters
- runtime evaluator logs
- OpenTelemetry traces/log export
- offline evaluation artifacts
- attack-block-rate evaluation artifacts

## 2. Metrics currently implemented

Metrics are initialized in:
- `techx-corp-platform/src/product-reviews/metrics.py`

### 2.1 `app_product_review_counter`

| Field | Value |
|---|---|
| Name | `app_product_review_counter` |
| Type | Counter |
| Unit | `reviews` |
| Labels observed in code | `product.id` |
| Purpose | Count the number of returned product reviews |

Emission point:
- `get_product_reviews(request_product_id)`

Meaning:
- Every time `GetProductReviews` returns review rows, the service increments this counter by the number of reviews returned.

### 2.2 `app_ai_assistant_counter`

| Field | Value |
|---|---|
| Name | `app_ai_assistant_counter` |
| Type | Counter |
| Unit | `summaries` |
| Labels observed in code | `product.id` |
| Purpose | Count AI assistant requests/responses |

Emission points:
- Bedrock runtime path in `get_ai_assistant_response(...)`
- OpenAI-compatible path in `get_ai_assistant_response(...)`

Meaning:
- Tracks responses that successfully complete the runtime path and reach the final return path.
- It does not count total inbound requests.
- Requests blocked at input guardrails, requests that fail after retry, and summaries rejected by the runtime evaluator are not included in this counter.

## 3. Important runtime logs that act as operational telemetry

Although not every fidelity signal is currently a Prometheus metric, AIE1 emits operationally useful logs.
These logs are important because the runtime factuality gate currently surfaces its verdict primarily through logs plus response behavior.

### 3.1 Runtime evaluator approval log

Example:
```text
Summary approved by evaluator for product_id:L9ECAV7KIM judge_provider=bedrock judge_model=amazon.nova-micro-v1:0 unsupported=0 contradicted=0
```

Meaning:
- The final summary passed the runtime factuality gate.
- The user received the summary.

### 3.2 Runtime evaluator rejection log

Example:
```text
Summary rejected by evaluator for product_id:L9ECAV7KIM judge_provider=bedrock judge_model=amazon.nova-micro-v1:0 unsupported=4 contradicted=0 reason=...
```

Meaning:
- The final summary was rejected after `output_filter`.
- The user did not receive the incorrect summary.
- The service returned the factuality fallback message instead.

### 3.3 Feature-flag override log

Example:
```text
Using env override for feature flag llmInaccurateResponse: True
```

Meaning:
- Runtime is using a local test override rather than depending only on flagd.
- This matters for interpreting local trace logs.
- This signal must not appear in a mandate-compliant staging or production run unless the team is explicitly performing local-only negative-control validation.

### 3.4 Inaccurate fixture log

Example:
```text
Using inaccurate summary fixture for product_id: L9ECAV7KIM
```

Meaning on the validated Bedrock path:
- Runtime is in deterministic negative-control mode for local factuality validation.

Provider-specific note:
- Bedrock path: emits this log when the fixed inaccurate fixture is used.
- OpenAI-compatible path: the negative-control path is prompt-based rather than fixture-based, so the same deterministic fixture log should not be assumed there.

## 4. Trace model

AIE1 configures OpenTelemetry and exports traces/logs through OTLP.

Relevant runtime components in `product_reviews_server.py`:
- tracer usage around:
  - `get_product_reviews`
  - `get_average_product_review_score`
  - `get_ai_assistant_response`

### 4.1 Important spans / traced operations

| Runtime operation | Meaning |
|---|---|
| `get_product_reviews` | Fetch raw reviews from Postgres for business request path |
| `get_average_product_review_score` | Fetch aggregate review score from Postgres |
| `get_ai_assistant_response` | Parent span for AI summary request path |

### 4.2 Attributes currently attached in runtime

Observed examples in code:
- `app.product.id`
- `app.product.question`
- `app.product_reviews.count`
- `app.product_reviews.average_score`

These attributes are enough to correlate:
- which product was queried
- which question was asked
- how many reviews were returned
- what average score was computed

## 5. Telemetry relevant to runtime fidelity evaluation

AIE1 now has a runtime factuality gate after `output_filter`.
This is a key architectural change and must be part of the telemetry contract.

### 5.1 Telemetry source of truth for runtime fidelity

Current source of truth:
1. runtime logs
2. client-visible fallback behavior
3. optional offline artifact confirmation via `repro/eval_fidelity.py`

### 5.2 Signals required by the mandate

Mandate #6 requires evidence, not verbal claims.
The following signals are the minimum evidence path for AIE1:

1. Real-model runtime response path
- Candidate model and runtime judge must both be observable in logs or trace context.

2. Rejected inaccurate output path
- Logs must show the evaluator rejecting a deliberately inaccurate summary.
- Client-visible output must show fallback instead of incorrect content.

3. No-source-answer path
- The service must visibly return the no-information behavior when the source does not support the answer.

4. Prompt-injection resistance path
- Logs, traces, or reproducible test evidence must show that hostile review text is treated as data and does not become instruction authority.
- AIE1 now has a committed reproducible path for this evidence through `repro/eval_attack_block_rate.py` and `repro/datasets/attack_eval_cases.json`.

5. Action-scope path
- If mentor asks the service to checkout or delete-cart, the evidence path is architectural plus eval-based:
  - AIE1 has no action-taking tool surface
  - the service cannot execute state-changing customer operations
  - the committed attack-block-rate dataset includes an unauthorized-action case and the artifact records that the runtime blocked it

### 5.3 Signals to monitor continuously

The most important operational questions are:
- How often does the runtime judge approve summaries?
- How often does the runtime judge reject summaries?
- Are retries/fallbacks increasing?
- Are feature-flag test paths accidentally enabled in non-test environments?
- Are block/reject rates rising in a way that indicates prompt-injection or review-quality issues?

Today, these questions are answered mostly through logs, trace inspection, and offline artifacts, not a dedicated Prometheus metric family.

## 6. Offline evaluation artifacts as audit telemetry

AIE1 also relies on offline JSON artifacts for auditability.

Example validated artifact:
- `repro/artifacts/fidelity_eval_20260714T152508Z.json`

Why this matters:
- The mandate explicitly requires eval that is reproducible from committed scripts/data.
- Offline artifacts are therefore part of the audit trail, not just temporary debug output.

Current status note:
- Reproducible fidelity evidence exists today through `repro/eval_fidelity.py` and committed artifacts.
- Reproducible attack-block-rate evidence also exists today through:
  - `repro/eval_attack_block_rate.py`
  - `repro/datasets/attack_eval_cases.json`
  - committed JSON artifacts under `repro/artifacts/`
- Example validated attack-block-rate artifact:
  - `repro/artifacts/attack_eval_20260715T152649Z.json`
- The latest validated attack-block-rate run executed grpc attack cases through the live runtime path (`grpc_case_execution_mode=grpc_runtime`) and review-injection cases through the same review guardrail used by `normalize_reviews_for_context(...)`.
- Current validated result on the strongest committed artifact: `attack_block_rate = 1.0` across `12/12` executed attack cases, `false_positive_rate = 0.0` across `4` benign control cases, and `0` skipped attack cases.

## 7. OTLP / collector dependency

AIE1 expects:
```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://<otel-collector-host>:4317
```

If this endpoint is unavailable:
- core business logic may still run
- but traces/log export are degraded or lost

This is an observability dependency, not the primary data dependency.

## 8. What AIE1 does not currently expose

The following copied AIE2 metric names are not part of the current AIE1 implementation:
- `copilot_request_latency_seconds`
- `copilot_llm_tokens_total`
- `copilot_guardrail_blocks_total`
- `copilot_tool_calls_total`

The following copied AIE2 span names are also not the active AIE1 names:
- `api_chat_request`
- `LLMInvoke`
- `Exec: search_products_v2`

These should be removed from AIE1-facing contracts unless AIE1 later implements equivalent telemetry.

## 9. Monitoring ownership boundary

| Area | AIE1 owns | Infra / platform side owns |
|---|---|---|
| Meaning of counters and runtime evaluator logs | Yes | |
| Changes to telemetry emitted by app code | Yes | |
| Offline fidelity artifact generation logic | Yes | |
| OTEL collector availability | | Yes |
| Prometheus scrape / ingest infra | | Yes |
| Jaeger / trace backend availability | | Yes |
| Pod CPU/RAM / restart alerts | | Yes |

## 10. Recommended future telemetry gaps

The current implementation works, but these additions would make the telemetry contract stronger later:
1. Dedicated counter for runtime evaluator approvals
2. Dedicated counter for runtime evaluator rejections
3. Dedicated counter for fallback invocations
4. Dedicated latency histogram for Bedrock candidate and Bedrock judge calls
5. Dedicated counter for prompt-injection review sanitization hits
6. Dedicated counter for no-information responses
7. Broader semantic attack corpus beyond the current committed attack-block-rate dataset

These are recommended improvements, not current guarantees.



