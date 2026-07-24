# ADR 0008: Runtime LLM Trace & Auditability for Product Reviews

## Status

Accepted for implementation.

## Context

Product Reviews has three independent evidence surfaces:

- runtime user flow in `product_reviews_server.py`;
- offline guardrail evaluation in `repro/run_eval_guardrail.py`;
- offline fidelity/judge evaluation in `repro/eval_fidelity.py`.

The offline eval files prove the harness and benchmark behavior, but they do
not by themselves prove which exact runtime answer was returned to a user. To
close that observability gap, the runtime needs a trace id that can be returned
to the client and later used to fetch a black-box trace record.

## Decision

Add a runtime trace layer for `AskProductAIAssistant`:

1. Extract the current OpenTelemetry trace id inside
   `get_ai_assistant_response()` and return it to the caller as gRPC trailing
   metadata `x-trace-id`.
2. Persist a black-box trace record to Redis under:

   ```text
   product_reviews:llm_trace:{trace_id}
   ```

3. Store only audit-safe metadata:

   - product id;
   - SHA-256 hash of the user question;
   - SHA-256 hash/class of the final response;
   - candidate model/provider and token/latency/cost estimate when provider
     usage is available;
   - judge model/provider and token/latency/cost estimate when judge was called;
   - cache hit status;
   - runtime guardrail/fidelity outcome;
   - fallback reason when fallback was used.

4. Do not store raw prompts, raw reviews, raw user question, raw model answer,
   credentials, or product catalog payloads in the trace record.
5. Provide an optional HTTP trace fetch endpoint:

   ```text
   GET /debug/llm-traces/{trace_id}
   ```

   The endpoint is enabled only when `PRODUCT_REVIEWS_TRACE_HTTP_PORT` and
   `PRODUCT_REVIEWS_TRACE_HTTP_TOKEN` are set. Local unauthenticated debugging
   requires an explicit opt-in via
   `PRODUCT_REVIEWS_TRACE_HTTP_ALLOW_UNAUTHENTICATED=true`.

## Implementation evidence

| Work item | Runtime evidence |
|---|---|
| AI-121: Extract OTel Trace ID and return via gRPC metadata | `product_reviews_server.py` calls `current_trace_id()` and `attach_trace_metadata(context, trace_id)` inside `get_ai_assistant_response()`; metadata key is `x-trace-id`. |
| AI-122: Write black-box trace to Redis | `guardrails/llm_trace.py` writes JSON records with key prefix `product_reviews:llm_trace:` via `write_llm_trace()`. |
| AI-123: HTTP fetch trace endpoint | `product_reviews_server.py` defines `LLMTraceHTTPHandler` and `start_llm_trace_http_server()`; route is `/debug/llm-traces/{trace_id}`. This implementation fetches persisted traces by id; it does not replay LLM calls. |
| AI-124: ADR and view summary | This ADR documents the schema, access path, and limitations. |

## Trace schema summary

Example fields:

```json
{
  "schema_version": 1,
  "trace_id": "otel-or-generated-id",
  "trace_id_source": "otel",
  "service": "product-reviews",
  "operation": "AskProductAIAssistant",
  "product_id": "L9ECAV7KIM",
  "question_sha256": "...",
  "candidate": {
    "provider": "bedrock",
    "model": "amazon.nova-lite-v1:0",
    "calls": [
      {
        "call_index": 1,
        "provider": "bedrock",
        "model": "amazon.nova-lite-v1:0",
        "input_tokens": 123,
        "output_tokens": 45,
        "total_tokens": 168,
        "latency_ms": 900.12,
        "estimated_cost_usd": 0.000018
      }
    ],
    "total_usage": {
      "call_count": 1,
      "input_tokens": 123,
      "output_tokens": 45,
      "total_tokens": 168,
      "latency_ms": 900.12,
      "estimated_cost_usd": 0.000018,
      "cost_source": "static_price_table"
    }
  },
  "judge": {
    "provider": "bedrock",
    "model": "amazon.nova-micro-v1:0",
    "status": "approved",
    "calls": [
      {
        "call_index": 1,
        "provider": "bedrock",
        "model": "amazon.nova-micro-v1:0",
        "input_tokens": 456,
        "output_tokens": 78,
        "total_tokens": 534,
        "latency_ms": 700.34,
        "estimated_cost_usd": 0.000027
      }
    ],
    "total_usage": {
      "call_count": 1,
      "input_tokens": 456,
      "output_tokens": 78,
      "total_tokens": 534,
      "latency_ms": 700.34,
      "estimated_cost_usd": 0.000027,
      "cost_source": "static_price_table"
    }
  },
  "guardrails": {
    "input_safe": true,
    "output_filtered": true,
    "runtime_fidelity_gate": "approved"
  },
  "cache": {
    "hit": false,
    "key_sha256": "...",
    "source_trace_id": null,
    "source_response_sha256": null
  },
  "outcome": "grounded_answer",
  "fallback_reason": null,
  "response_class": "grounded_answer",
  "response_sha256": "...",
  "total_latency_ms": 1750.46
}
```

## Operational notes

To enable the HTTP trace endpoint locally:

```powershell
$env:PRODUCT_REVIEWS_TRACE_HTTP_PORT="8086"
$env:PRODUCT_REVIEWS_TRACE_HTTP_TOKEN="<internal-token>"
```

Then fetch a trace by id:

```powershell
curl.exe -H "x-trace-token: <internal-token>" http://localhost:8086/debug/llm-traces/<trace-id>
```

Redis TTL defaults to `86400` seconds and can be overridden with:

```powershell
$env:PRODUCT_REVIEWS_TRACE_TTL_SECONDS="86400"
```

## Consequences

Benefits:

- A runtime answer can be tied to a concrete trace id.
- Evidence can show whether the answer came from cache, fallback,
  deterministic logic, candidate-only path, or candidate + runtime judge path.
- Token, latency, and rough cost are captured when the model provider returns
  usage metadata. Multiple candidate/judge calls are kept as `calls` and
  aggregated in `total_usage`.
- Cache-hit traces can point back to the original `source_trace_id` that
  produced the cached answer.
- No raw user prompt/review/answer text is stored in Redis traces.

Trade-offs and accepted limitations:

- The HTTP endpoint depends on Redis availability; trace writes are fail-open
  and must not block user responses. This preserves the user-facing AI feature
  during a Redis outage, at the cost of possibly missing a trace for that
  request.
- The HTTP endpoint is intended for local/internal debugging only. It is
  disabled by default and token-protected when enabled; it should not be exposed
  directly to public traffic.
- Cost is an estimate based on known Nova Lite/Micro public pricing constants,
  not a billing-system source of truth. This is sufficient for runtime
  before/after engineering evidence, but not for AWS invoice reconciliation.
- Cache-hit traces do not have fresh candidate/judge token usage because no
  model call happens on a cache hit. Instead, they point back to the original
  approved `source_trace_id`; re-judging every cache hit would defeat the
  cache's latency/cost purpose and can introduce unnecessary judge variance.
- Raw question, review and answer text are intentionally not stored. Debugging
  exact wording requires matching hashes against a controlled test artifact or
  UI evidence, which is safer than persisting raw PII/security-sensitive text in
  Redis.
- Full runtime smoke tests should run in the service/container environment that
  includes gRPC, OpenTelemetry, OpenFeature, Redis and AWS/Bedrock
  configuration. Local unit tests should not fake these core service
  dependencies because that can hide runtime deployment issues.
- This ADR does not implement multi-turn memory/history. Multi-turn was
  explicitly removed from the current scope.

## Smoke-test evidence

Runtime smoke test executed against a rebuilt Product Reviews container:

- image: `aie1-product-reviews:trace-current`
- container: `product-reviews-trace-test-20260724`
- gRPC: `localhost:8085`
- trace HTTP: `localhost:8086`
- Redis-compatible storage: `valkey-cart`

Happy-path request:

```text
product_id=L9ECAV7KIM
question=Do reviewers say the kit removes dust and fingerprints without leaving residue?
x-trace-id=6430920be99810c6d6255d620292a695
```

Persisted trace showed:

- `trace_id_source=otel`
- `candidate.provider=bedrock`
- `candidate.model=amazon.nova-lite-v1:0`
- `candidate.total_usage.total_tokens=1290`
- `judge.provider=bedrock`
- `judge.model=amazon.nova-micro-v1:0`
- `judge.status=approved`
- `judge.total_usage.total_tokens=1970`
- `guardrails.runtime_fidelity_gate=approved`
- `response_class=grounded_answer`

Cache-hit smoke used a repeated request and produced:

- `trace_id=4e4cd351aac5c72c99844d70dc711f5b`
- `cache.hit=true`
- `cache.source_trace_id=6430920be99810c6d6255d620292a695`

Trace endpoint auth smoke:

- Fetch with `x-trace-token` returned HTTP 200 and trace JSON.
- Fetch without token returned HTTP 401.

## Smoke-test procedure

A complete runtime smoke test requires:

1. Product Reviews service running with Bedrock candidate/judge config.
2. Redis reachable from Product Reviews.
3. Trace endpoint enabled:

   ```powershell
   $env:PRODUCT_REVIEWS_TRACE_HTTP_PORT="8086"
   $env:PRODUCT_REVIEWS_TRACE_HTTP_TOKEN="<internal-token>"
   ```

4. One UI/gRPC request to `AskProductAIAssistant`.
5. Fetch by returned `x-trace-id`:

   ```powershell
   curl.exe -H "x-trace-token: <internal-token>" http://localhost:8086/debug/llm-traces/<trace-id>
   ```

The expected trace should show final `response_class`, `outcome`,
candidate/judge model metadata, optional token usage, cache status and
`runtime_fidelity_gate`.
