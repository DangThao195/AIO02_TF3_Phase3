# AIE1 Product Reviews AI API Contract

Owner: AIO02 / AIE1
System: TechX Corp `product-reviews`
Scope: Service contract for the AIE1 product-review runtime that serves gRPC requests and returns review-grounded AI summaries.
Mandate alignment: `mandates/MANDATE-06-ai-trust-safety.md`

## 1. Purpose

This document defines the API surface that AIE1 exposes.
It replaces the copied AIE2 chatbot contract and reflects the actual AIE1 system now running in:
- `techx-corp-platform/src/product-reviews/product_reviews_server.py`

AIE1 is not an HTTP chatbot service.
AIE1 is a gRPC microservice named:
- `oteldemo.ProductReviewService`

## 2. Service identity

| Attribute | Value |
|---|---|
| Service name | `product-reviews` |
| Protocol | `gRPC` |
| gRPC service | `oteldemo.ProductReviewService` |
| Runtime port | `PRODUCT_REVIEWS_PORT` |
| Local host-run port used in validation | `8085` |
| Internal health service | gRPC health check (`Check`, `Watch`) |

## 3. Exposed RPC methods

The runtime currently exposes three business methods and two gRPC health methods.

### 3.1 `GetProductReviews`

Returns raw product reviews for a given product id.

**Request message**
```text
GetProductReviewsRequest {
  product_id: string
}
```

**Response message**
```text
GetProductReviewsResponse {
  product_reviews: repeated ProductReview {
    username: string
    description: string
    score: string
  }
}
```

**Behavior**
- Reads reviews from Postgres via `fetch_product_reviews_from_db(...)`
- Returns every matching row for the given `product_id`
- Does not call the LLM

**Evidence in code**
- `ProductReviewService.GetProductReviews(...)`
- `get_product_reviews(request_product_id)`
- `database.fetch_product_reviews_from_db(...)`

### 3.2 `GetAverageProductReviewScore`

Returns the average review score for a given product id.

**Request message**
```text
GetAverageProductReviewScoreRequest {
  product_id: string
}
```

**Response message**
```text
GetAverageProductReviewScoreResponse {
  average_score: double
}
```

**Behavior**
- Reads the aggregate average score from Postgres
- Does not call the LLM

**Evidence in code**
- `ProductReviewService.GetAverageProductReviewScore(...)`
- `get_average_product_review_score(request_product_id)`
- `database.fetch_avg_product_review_score_from_db(...)`

### 3.3 `AskProductAIAssistant`

Returns a brief AI-generated answer about a product, primarily used to summarize reviews.

**Request message**
```text
AskProductAIAssistantRequest {
  product_id: string
  question: string
}
```

**Response message**
```text
AskProductAIAssistantResponse {
  response: string
}
```

**Behavior**
- Applies input guardrails
- Fetches reviews and product info
- Calls the candidate model
- Applies output filtering
- Applies runtime factuality evaluation
- Returns either:
  - an approved summary, or
  - a safe fallback message

**Evidence in code**
- `ProductReviewService.AskProductAIAssistant(...)`
- `get_ai_assistant_response(request_product_id, question)`

## 4. Runtime summary flow

The runtime path for AI summary requests is:

```text
Client
-> AskProductAIAssistant(product_id, question)
-> input guardrail
-> fetch raw reviews from Postgres
-> fetch product info from product-catalog
-> normalize reviews for prompt + judge
-> candidate model call
-> output_filter
-> runtime factuality evaluator
   -> approved: return summary
   -> rejected: return fallback
```

## 5. Runtime model roles

| Role | Current provider/model | Purpose |
|---|---|---|
| Candidate model | Bedrock `amazon.nova-lite-v1:0` | Generate the product-review answer/summary |
| Runtime judge | Bedrock `amazon.nova-micro-v1:0` | Detect unsupported or contradicted claims after `output_filter` |

## 6. Trust and safety requirements mapped from Mandate #6

### 6.1 No hallucinated answer to the user
- Runtime must not return an unverified summary directly from the candidate model.
- Every normal summary response must pass through:
  1. `post_process_output(...)`
  2. `evaluate_summary_fidelity(...)`
- If the summary is rejected, runtime must return fallback instead of fabricated content.

### 6.2 No answer when the source does not support it
- If the model determines the answer is not in reviews or product info, runtime maps the result to the no-information message.
- This is the required contract behavior for questions that are outside the evidence contained in the source reviews.

### 6.3 Prompt-injection resistance
- Review text is treated as untrusted input.
- Runtime must sanitize review content before using it inside the candidate prompt.
- Unsafe review content must not become a control instruction for the model.
- The contract assumption is:
  - review text is data
  - review text is never treated as instruction authority

### 6.4 PII and unsafe review content filtering
- Review descriptions are re-checked before entering the candidate/judge context.
- If a review is considered unsafe, runtime replaces it with a placeholder rather than forwarding the original content.
- Contract goal:
  - reduce accidental propagation of sensitive or malicious content into summary output

### 6.5 No system-prompt exposure
- User-visible output must not reveal the hidden system prompt or internal tool instructions.
- This is enforced by role separation in prompt construction and by post-processing of the final answer.

### 6.6 Action scope is read-only by design
- AIE1 exposes read-only retrieval and text-generation behavior only.
- AIE1 has no tool or RPC that performs checkout, deletes a cart, modifies an order, or executes any customer-side state change.
- The mandate requirement to refuse unauthorized actions still matters conceptually, but it is not implemented here as a runtime tool-permission gate because `AskProductAIAssistant` only returns text and never executes actions.
- If a user asks this service to checkout, cancel, or delete a cart, the correct contract interpretation is:
  - the request is outside AIE1 action scope
  - no backend action can be executed through this service

## 7. Guardrails and fallback behavior

### 7.1 Input guardrail
- `check_input(question)` runs before any AI call
- Unsafe questions are blocked immediately

### 7.2 Review-content guardrail
- Review descriptions are re-checked in `normalize_reviews_for_context(...)`
- Unsafe review content is replaced with a policy-safe placeholder

### 7.3 Output filter
- `post_process_output(...)` maps:
  - `OUT_OF_SCOPE` -> safe out-of-scope message
  - `NO_INFO` -> safe no-information message
- Normal summaries pass through `filter_output(...)`

### 7.4 Runtime factuality gate
- Runs after `output_filter`
- Evaluates the final summary against raw reviews
- Judge output contains:
  - `approved`
  - `unsupported_claims`
  - `contradicted_claims`
  - `reason`

### 7.5 Retry and fallback
- Candidate and judge calls are wrapped with `@with_fallback`
- Retry policy: 3 attempts for transient errors
- If retry fails, the service returns a safe fallback string

## 8. Negative-control behavior for local validation

AIE1 supports a deterministic local inaccurate-summary test path for product `L9ECAV7KIM`.

Trigger:
- `FORCE_FLAG_LLMINACCURATERESPONSE=true`

Expected behavior on the validated Bedrock path:
- Runtime injects a fixed inaccurate summary fixture
- Runtime judge rejects the summary
- Service returns the fallback message instead of the incorrect content

Provider-specific note:
- Bedrock path: uses the fixed fixture in `INACCURATE_SUMMARY_FIXTURES["L9ECAV7KIM"]`
- OpenAI-compatible path: does not use the fixed fixture; it appends an `inaccurate_prompt` to the message stack and therefore is less deterministic as a negative-control harness

This directly supports the mandate requirement that the team must be able to demonstrate a bad output being blocked instead of shown to the user.
- Reproducible attack-block-rate evidence for this contract now exists through 
epro/eval_attack_block_rate.py, 
epro/datasets/attack_eval_cases.json, and the latest validated artifact 
epro/artifacts/attack_eval_20260715T152649Z.json.

Important scope note:
- `FORCE_FLAG_*` overrides are local validation controls only.
- They are not part of the production serving contract and must not be treated as a replacement for live `flagd` behavior in a mandate-compliant environment.

## 9. Health behavior

The service also implements gRPC health handlers:
- `Check`
- `Watch`

These are used for service liveness/readiness at the gRPC layer, not as a public business API.

## 10. Acceptance scenarios derived from the mandate

The following scenarios must be demonstrable on top of this contract:

1. Review contains an injected malicious sentence
- Expected result: the runtime does not follow the injected instruction as system authority.

2. User asks a question not supported by review evidence
- Expected result: runtime returns the no-information response or fallback, not a fabricated answer.

3. Candidate model returns a factually incorrect summary
- Expected result: runtime judge rejects the output and the service returns fallback.

4. Candidate or judge fails transiently
- Expected result: runtime retries up to 3 times and then falls back safely if still unsuccessful.

5. User asks the service to perform checkout or delete-cart behavior
- Expected result: no such action is possible through AIE1 because this service is read-only and text-only by design.

## 11. Not part of this contract

The following copied AIE2 endpoints are not part of AIE1 and must not be referenced for AIE1 integration:
- `POST /api/chat`
- `POST /api/confirm`
- `GET /api/cart`
- HTTP port `8001`
- HTTP health check `GET /chatbot`

AIE1 is a gRPC service, not a shopping-copilot HTTP service.





