# AIE1 Integration Handover

Owner: AIO02 / AIE1
System: TechX Corp `product-reviews`
Scope: Runtime and deployment handover for the AIE1 product-review AI service.
Mandate alignment: `mandates/MANDATE-06-ai-trust-safety.md`

## 1. Purpose

This document defines what AIE1 provides and what the integration/deployment side must supply for `product-reviews` to run correctly.

This file replaces the copied AIE2 shopping-copilot deployment contract.
AIE1 does not require cart, recommendation, currency, shipping, or Bedrock Knowledge Base dependencies.

## 2. What AIE1 provides

| Artifact | Value / Description |
|---|---|
| Service | `product-reviews` |
| Protocol | `gRPC` |
| Business RPCs | `GetProductReviews`, `GetAverageProductReviewScore`, `AskProductAIAssistant` |
| Runtime file | `techx-corp-platform/src/product-reviews/product_reviews_server.py` |
| Candidate model path | Bedrock direct via `boto3` |
| Runtime judge path | Bedrock direct via `boto3` |
| Offline fidelity evaluator | `repro/eval_fidelity.py` |
| Offline attack evaluator | `repro/eval_attack_block_rate.py` |
| Local runtime trace report | `docs/AIE1_LOCAL_RUNTIME_TRACE.md` |

## 3. Runtime dependencies that must exist

AIE1 runtime depends on these systems:

1. Postgres
- Source of truth for product reviews
- Used by:
  - `GetProductReviews`
  - `GetAverageProductReviewScore`
  - `AskProductAIAssistant`
  - `repro/eval_fidelity.py`
  - `repro/eval_attack_block_rate.py`

2. `product-catalog` gRPC service
- Used to fetch product metadata for AI answers
- Called from `fetch_product_info(product_id)`

3. `flagd`
- Used for feature flags such as:
  - `llmInaccurateResponse`
  - `llmRateLimitError`
- Local override is also supported through env vars:
  - `FORCE_FLAG_LLMINACCURATERESPONSE`
  - `FORCE_FLAG_LLMRATELIMITERROR`

4. OpenTelemetry collector
- Used for traces/log export

5. AWS Bedrock access
- Required for:
  - candidate generation model
  - runtime factuality judge
  - offline Bedrock judge path

6. Local OpenAI-compatible mock endpoint variables
- `LLM_HOST` and `LLM_PORT` are still mandatory at process start because `product_reviews_server.py` unconditionally builds `llm_mock_url` from them before branching on `LLM_PROVIDER`.
- In the validated Bedrock host-run they were set to the local mock container values even though the Bedrock candidate path did not use that endpoint for generation.

## 4. Environment variables required by AIE1 runtime

### 4.1 Core runtime

```env
OTEL_SERVICE_NAME=product-reviews
PRODUCT_REVIEWS_PORT=8085
DB_CONNECTION_STRING=host=<db-host> user=<db-user> password=<db-password> dbname=<db-name> port=<db-port>
PRODUCT_CATALOG_ADDR=<catalog-host>:3550
FLAGD_HOST=<flagd-host>
FLAGD_PORT=<flagd-port>
LLM_HOST=<llm-host>
LLM_PORT=<llm-port>
OTEL_EXPORTER_OTLP_ENDPOINT=http://<otel-collector-host>:4317
```

### 4.2 Candidate model configuration

```env
LLM_PROVIDER=bedrock
LLM_MODEL=amazon.nova-lite-v1:0
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<aws-access-key-id>
AWS_SECRET_ACCESS_KEY=<aws-secret-access-key>
```

### 4.3 Runtime judge configuration

```env
JUDGE_PROVIDER=bedrock
JUDGE_MODEL=amazon.nova-micro-v1:0
JUDGE_REGION=us-east-1
JUDGE_TIMEOUT_SECONDS=3.0
```

### 4.4 Optional local validation overrides

```env
FORCE_FLAG_LLMINACCURATERESPONSE=true|false
FORCE_FLAG_LLMRATELIMITERROR=true|false
```

Strict scope rule:
- These overrides exist only to support local validation, mentor demo, and negative-control runs.
- They must not be set in an environment that claims real mandate-compliance behavior, because the live requirement is to keep `flagd` integration active rather than bypass it with env forcing.
- In staging or production-like validation, `flagd` remains the source of truth for incident toggles.

## 5. Local stack values used during the validated run

The last validated host-run used:

```env
PRODUCT_REVIEWS_PORT=8085
DB_CONNECTION_STRING=host=localhost user=otelu password=otelp dbname=otel port=50319
PRODUCT_CATALOG_ADDR=localhost:50333
FLAGD_HOST=localhost
FLAGD_PORT=50326
LLM_HOST=localhost
LLM_PORT=50329
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:50318
LLM_PROVIDER=bedrock
LLM_MODEL=amazon.nova-lite-v1:0
JUDGE_PROVIDER=bedrock
JUDGE_MODEL=amazon.nova-micro-v1:0
JUDGE_REGION=us-east-1
```

## 6. Database contract

AIE1 expects review data from Postgres.
Current validated assumptions:

| Field | Expected value / behavior |
|---|---|
| DB name | `otel` in the validated local run |
| Table | `reviews.productreviews` |
| Columns used | `product_id`, `username`, `description`, `score` |
| Access mode | Read-only for runtime and evaluator |

Important note:
- Local validation showed that using the wrong DB name caused the reviews path to return an error payload instead of real rows.
- The validated local DB name is `otel`, not `demo`.

## 7. gRPC contract with `product-catalog`

AIE1 expects `product-catalog` to be reachable at `PRODUCT_CATALOG_ADDR`.

Usage:
- `fetch_product_info(product_id)` calls the catalog service
- Returned metadata is included in the Bedrock grounding prompt

If catalog is unavailable:
- AI answer quality degrades or request may fail
- This is a runtime dependency, not an optional enhancement

## 8. Reliability, trust, and safety deployment requirements

This section maps directly to the mandate requirements.

### 8.1 Real model with a fallback path
- AIE1 must run against a real LLM provider, not a mock-only configuration, in any environment considered valid for mandate compliance.
- If the candidate model or judge model fails transiently, runtime must:
  1. retry up to 3 times
  2. return a safe fallback if retries still fail
- Integration side must not remove or bypass this retry/fallback behavior.

### 8.2 Bad content must not reach the user
- Runtime evaluator after `output_filter` is part of the serving contract.
- Deploy-side integration must preserve the runtime path in which rejected summaries produce fallback instead of being shown to the user.

### 8.3 Prompt-injection and PII defenses must remain active
- Feature-flag plumbing, review sanitation path, and output filtering must remain enabled.
- Deploy-side must not disable `flagd` integration or otherwise bypass trust/safety checks.
- The only allowed exception is local-only negative-control validation through `FORCE_FLAG_*`, which must never be mistaken for a production flag strategy.

### 8.4 Evidence must remain reproducible
- The service must be deployable in a way that still allows:
  - runtime negative-control testing
  - offline fidelity evaluator runs
  - offline attack-block-rate evaluator runs
  - artifact generation from committed scripts/data
- The current committed evidence paths are:
  - fidelity: `repro/eval_fidelity.py` -> `repro/artifacts/fidelity_eval_*.json`
  - attack-block-rate: `repro/eval_attack_block_rate.py` + `repro/datasets/attack_eval_cases.json` -> `repro/artifacts/attack_eval_*.json`

## 9. Non-functional constraints from the mandate

### 9.1 SLO / latency constraint
- Guardrails and eval must not break product-page SLO.
- Runtime path therefore uses:
  - narrow factuality gate
  - short judge timeout
  - retry budget bounded to 3 attempts
- Integration side must not add blocking layers that make the page path unstable without explicit performance review.

### 9.2 Cost constraint
- The system must stay within current budget.
- Current model split reflects this constraint:
  - `nova-lite` for generation
  - `nova-micro` for factuality checking
- Integration side must not silently replace these with larger or materially more expensive defaults without AIE review.

## 10. Runtime behavior relevant to deployment

### 10.1 Retry
- Candidate model call: retryable through `@with_fallback`
- Runtime judge call: retryable through `@with_fallback`
- Retry budget: 3 attempts for transient failures

### 10.2 Fallback
- If candidate/judge fails after retries, runtime returns a safe fallback string
- If runtime judge rejects the summary, runtime returns a factuality fallback string

### 10.3 No HTTP chatbot endpoints
AIE1 does not expose these copied AIE2 interfaces:
- `/api/chat`
- `/api/confirm`
- `/api/cart`

AIE1 integration must use gRPC, not HTTP chatbot routing.

## 11. Mentor validation scenarios that deployment must support

The deployed or local-integrated system must allow AIE1 to demonstrate these cases:

1. Malicious review injection scenario
- A review contains instruction-like hostile text.
- Expected result: runtime does not obey it as model control.

2. No-source-answer scenario
- User asks a question that the source review data does not answer.
- Expected result: runtime returns no-information or fallback, not hallucinated content.

3. Inaccurate-summary scenario
- A forced inaccurate summary is generated for a controlled product id.
- Expected result: runtime judge rejects it and fallback is returned.

4. Action-scope scenario
- Mentor asks the AI to checkout, cancel, or delete-cart.
- Expected result: no action is executed because AIE1 has no action-taking tool surface; the service is read-only and text-only by design.

These are not optional demos; they are required to show mandate compliance.

Committed evidence now exists for the attack-block-rate path as well:
- dataset: `repro/datasets/attack_eval_cases.json`
- runner: `repro/eval_attack_block_rate.py`
- validated example artifact: `repro/artifacts/attack_eval_20260715T152649Z.json`
- current validated result: `attack_block_rate = 1.0` on `12/12` executed attack cases with `false_positive_rate = 0.0` on `4` benign control cases and `0` skipped attack cases

## 12. Ownership boundary

| Responsibility | AIE1 | Integration / Deploy side |
|---|---|---|
| Product-review AI logic | Yes | |
| Runtime guardrails | Yes | |
| Runtime factuality evaluator | Yes | |
| Offline fidelity evaluator | Yes | |
| Model selection and trust/safety policy | Yes | |
| Environment wiring | | Yes |
| Database connectivity | | Yes |
| gRPC service discovery / DNS / ports | | Yes |
| OTEL endpoint wiring | | Yes |
| Feature-flag infrastructure availability | | Yes |
| Pod/container infra health | | Yes |

## 13. ADR linkage

The current AIE1 package already has these ADRs in `docs/adr/`:
- `0001-choose-bedrock-nova-lite.md`
- `0002-fallback-mechanism.md`
- `0003-ai-trust-safety-guardrails.md`
- `0004-summary-fidelity-evaluation.md`

These ADRs cover:
- candidate model choice
- fallback and reliability behavior
- trust-safety guardrails, prompt-injection resistance, PII, and action-scope constraints
- runtime fidelity-judge design for summary factuality

Attack-block-rate is no longer an open mandate-evidence gap because the repo now includes a committed evaluator, dataset, and JSON artifact path:
- `repro/eval_attack_block_rate.py`
- `repro/datasets/attack_eval_cases.json`
- `repro/artifacts/attack_eval_20260715T152649Z.json`

If the team later wants a dedicated ADR only for attack-block-rate methodology, that is a documentation hardening step rather than a current deployment blocker.

## 14. What should be removed from the copied AIE2 handover assumptions

These AIE2-specific items do not belong to AIE1 and must not remain in the final handover:
- `CART_ADDR`
- `RECO_ADDR`
- `CURRENCY_ADDR`
- `SHIPPING_ADDR`
- `BEDROCK_KB_ID`
- `BEDROCK_KB_DATA_SOURCE_ID`
- `PRODUCTS_S3_BUCKET`
- HTTP metrics port `8001`
- Shopping-copilot image assumptions



