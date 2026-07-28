# ADR4: MANDATE #25 - AI RESILIENCE WITH CONTROLLED DEGRADATION

**Tác giả**: Đặng Thị Ngọc Thảo  
**Ngày**: 27/07/2026  
**Hạn chót nộp**: 28/07/2026 (Thứ Ba)  
**Status**: ✅ HOÀN THÀNH - READY FOR GRADING

---

## PROBLEM STATEMENT

Hệ thống Shopping Copilot phụ thuộc vào AWS Bedrock LLM provider bên ngoài. Khi Bedrock gặp sự cố (timeout, rate-limit, 5xx, hoặc trả response hỏng), hệ thống hiện nay:

- ❌ Trả HTTP 500 error (bad UX)
- ❌ Treo (timeout)
- ❌ Thực thi tool với garbage arguments (data corruption)
- ❌ Retry vô tận (self-inflicted DDoS)
- ❌ Hallucinate prices/products (financial errors)

**Yêu cầu MANDATE #25**: Hệ thống phải **degrade có kiểm soát** - không gục, không bịa dữ liệu, luôn có đường lui an toàn.

**Tham chiếu Mandate gốc**: [MANDATE-25-ai-resilience-fallback.md](../../../../MANDATE-25-ai-resilience-fallback.md)

---

## SOLUTION OVERVIEW

Triển khai **3 guardrail layers**:

### Layer 1: Circuit Breaker
- Detect sustained failures (5+ consecutive errors)
- Prevent cascading failures (stop hammering)
- Auto-recovery (self-heal when provider recovers)

### Layer 2: Bounded Retry + Backoff
- Transient vs permanent error detection
- Exponential backoff: 1s → 2s → 4s → 8s (capped)
- Max 3 retries (4 attempts total)

### Layer 3: Schema Validation + Safe Fallback
- Validate LLM output before use
- Reject garbage arguments (never execute with bad args)
- Fallback uses keywords only (no fabrication)

---

## IMPLEMENTATION DETAILS

### 1. Circuit Breaker Pattern

**File**: `src/guardrails/circuit_breaker.py` (300 LOC)

**State Machine**:
```
CLOSED (normal)
  ↓ [5 consecutive failures]
OPEN (sustained failure - fast-fail, no execution)
  ↓ [60 second recovery timeout]
HALF_OPEN (test recovery - 1 request allowed)
  ↓ [2 successes]
CLOSED (recovered)
  ↓ [failure]
back to tracking failures
```

**Configuration**:
```python
CircuitBreakerConfig(
    failure_threshold=5,      # 5 failures trigger OPEN
    recovery_timeout=60,      # 60 seconds before HALF_OPEN
    success_threshold=2       # 2 successes to close from HALF_OPEN
)
```

**Integration in Agent**:
```python
# copilot_agent.py line 70-72
self._bedrock_breaker = CircuitBreaker(
    "bedrock",
    CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60, success_threshold=2)
)

# Line 130-135 (intent parser)
if self._bedrock_breaker.is_open:
    return repair_intent_fallback(user_message)  # Fast-fail, use fallback

# Line 360-365 (planner)
if self._bedrock_breaker.is_open:
    return []  # Empty plan, triggers abstain
```

---

### 2. Bounded Retry with Exponential Backoff

**File**: `src/guardrails/retry.py` (150 LOC - ENHANCED)

**Transient Error Detection**:
- ✓ TimeoutError
- ✓ asyncio.TimeoutError
- ✓ ConnectionError
- ✗ PermissionError (permanent - fail fast)
- ✗ ValueError (validation error - fail fast)

**Backoff Computation**:
```python
def _compute_backoff_ms(attempt: int, config: RetryConfig) -> int:
    # Exponential: 2^attempt seconds (with jitter ±10%)
    delay = config.initial_delay_ms * (2 ** (attempt - 1))
    delay = min(delay, config.max_delay_ms)  # Cap at 8s
    jitter = delay * config.jitter_factor * (random() * 2 - 1)
    return int(delay + jitter)
```

**Retry Sequence**:
```
Attempt 1: call function
  ├─ Transient error? → wait backoff_1 (1s)
  ├─ Permanent error? → fail immediately
  └─ Success? → return result

Attempt 2: retry after 1s
  ├─ Transient error? → wait backoff_2 (2s)
  └─ ...

Attempt 3: retry after 3s
  ├─ Transient error? → wait backoff_3 (4s)
  └─ ...

Attempt 4: retry after 7s
  ├─ Transient error? → wait backoff_4 (8s capped)
  └─ Max retries reached → fail

Total latency ≤ 1s + 2s + 4s + 8s = 15s (but typically 7-8s)
```

**Configuration**:
```python
RetryConfig(
    max_retries=3,              # 4 total attempts (1 + 3 retries)
    initial_delay_ms=1000,      # Start at 1 second
    max_delay_ms=8000,          # Cap at 8 seconds
    jitter_factor=0.1           # ±10% jitter to prevent thundering herd
)
```

---

### 3. Schema Validation + Safe Fallback

**File**: `src/guardrails/schema_validator.py` (250 LOC)

**Validation Functions**:

#### A. Intent Parser Output
```python
def validate_intent_parser_output(raw_text: str) -> ValidationResult:
    # 1. Parse JSON (catch JSONDecodeError)
    # 2. Check required fields (task_type, target_entity)
    # 3. Validate enum: task_type ∈ {search, view_cart, list_products, ...}
    # 4. Validate enum: target_entity ∈ {product, category, cart, review, ...}
    return ValidationResult(is_valid=True/False, data=parsed or error)
```

**Valid task_types**: search, list_products, list_categories, lookup, rank, compare, add_to_cart, view_cart, get_reviews, get_recommendations, convert_currency, get_shipping, greeting, clarify, unknown

#### B. Planner Output
```python
def validate_planner_output(raw_text: str) -> ValidationResult:
    # 1. Parse JSON
    # 2. Must be list of tool calls
    # 3. Each tool call: {"name": (str, in whitelist), "args": (dict)}
    return ValidationResult(is_valid=True/False, data=plan or error)
```

**Whitelisted tools**: get_cart, search_product, view_review, add_to_cart, etc.

#### C. Synthesis Output
```python
def validate_synthesis_output(raw_text: str) -> ValidationResult:
    # 1. Non-empty string
    # 2. No unresolved templates like [INSERT_NAME], [TÊN_PRODUCT], etc.
    return ValidationResult(is_valid=True/False, data=text or error)
```

**Safe Fallback Repair Functions**:

```python
def repair_intent_fallback(raw_text: str) -> Dict[str, Any]:
    """Extract keywords and return safe default intent"""
    # Detect keywords: "giỏ hàng" → view_cart, "tìm" → search, etc.
    # Return: {"task_type": "search", "target_entity": "product", "product_query": raw_text[:100]}
    # NO fabrication - only use keywords from input
```

```python
def repair_plan_fallback() -> list:
    """Return empty plan (triggers abstain)"""
    return []  # No random tools injected
```

**Integration in Agent**:
```python
# Intent parser (lines 145-160)
validation = validate_intent_parser_output(text)
if not validation.is_valid:
    intent = repair_intent_fallback(text)  # Safe fallback

# Planner (lines 380-395)
validation = validate_planner_output(text)
if not validation.is_valid:
    plan = repair_plan_fallback()  # Empty plan
```

---

## TEST RESULTS

**5/5 Tests PASSED (100% Pass Rate)**

### Test 1: Circuit Breaker Opens on Sustained Failure ✅
- Scenario 1a: CLOSED → OPEN after 5 failures ✅
- Scenario 1b: Fast-fail (0.2ms) when OPEN ✅
- Scenario 1c: Auto-recovery OPEN → HALF_OPEN → CLOSED ✅

### Test 2: Retry with Bounded Backoff ✅
- Scenario 2a: Transient/permanent error detection ✅
- Scenario 2b: Backoff progression capped at 8s ✅

### Test 3: Schema Validation Prevents Garbage ✅
- Scenario 3a: Invalid task_type rejected ✅
- Scenario 3b: Valid intent accepted ✅
- Scenario 3c: Fallback repair works (keywords-only) ✅

### Test 4: Safe Degradation (No Fabrication) ✅
- Scenario 4a: Intent fallback uses keywords ✅
- Scenario 4b: Plan fallback empty (no fabricated tools) ✅
- Scenario 4c: No invented prices ✅

### Test 5: No 500 on Provider Failure ✅
- Scenario 5a: Timeout → HTTP 200 ✅
- Scenario 5b: Provider 5xx → HTTP 200 ✅
- Scenario 5c: Malformed JSON → HTTP 200 (no crash) ✅

**Test Evidence**: [`mandate25/mandate_25_test_results.json`](../../mandate25/mandate_25_test_results.json)

---

## COMPLIANCE MATRIX

| MANDATE #25 Requirement | Implementation | Test Case | Status |
|---|---|---|---|
| #1: No 500 on provider failure | Circuit breaker + retry + fallback | Test 5 | ✅ |
| #2: Bounded retries | RetryConfig(max_retries=3, max_delay=8s) | Test 2 | ✅ |
| #3: Circuit-breaker | CircuitBreakerConfig(5→OPEN, 60s recovery) | Test 1 | ✅ |
| #4: Safe degradation | repair_*_fallback() - keywords only | Test 4 | ✅ |
| #5: Garbage output blocked | validate_*_output() schema validation | Test 3 | ✅ |

---

## CODE METRICS

| Metric | Value |
|--------|-------|
| Total LOC added | 550+ |
| Files new | 2 (circuit_breaker, schema_validator) |
| Files enhanced | 1 (retry) |
| Files modified | 2 (copilot_agent, prompt) |
| Compilation errors | 0 |
| Import resolution | 100% |
| Test pass rate | 100% (5/5) |
| Circuit breaker states | 3 (CLOSED, OPEN, HALF_OPEN) |
| Max retry attempts | 4 (1 initial + 3 retries) |
| Max backoff delay | 8000ms |

---

## DEPLOYMENT CHECKLIST

- ✅ Code compiles without errors
- ✅ All imports resolve correctly
- ✅ Agent initializes with resilience components
- ✅ Circuit breaker state machine implemented
- ✅ Retry + backoff logic working
- ✅ Schema validation catching garbage
- ✅ Fallback repair functions working
- ✅ 5/5 test cases passing
- ✅ ADR documentation complete
- ✅ Test results saved to JSON

---

## OPERATIONAL NOTES

### Monitoring Metrics to Track
```
circuit_breaker_state{service=bedrock}
  - 0: CLOSED (normal)
  - 1: OPEN (sustained failure)
  - 2: HALF_OPEN (recovery test)

retry_attempts_total{error_type=transient|permanent}
retry_backoff_duration_ms{attempt=1|2|3|4}

schema_validation_failures_total{layer=intent|planner|synthesis}
fallback_activations_total{type=heuristic|empty_plan|predefined_message}

response_status_code{status=200|500}
  - Should always be 200, never 500 on Bedrock failure
```

### Known Limitations
1. Per-pod circuit breaker (not shared across pods)
2. 60s recovery timeout may delay recovery for short outages
3. No alternative LLM (fallback is degradation, not switch to Claude/OpenAI)

### Future Improvements
1. Redis-shared circuit breaker for multi-pod coordination
2. Faster recovery for < 30s outages
3. Fallback to alternative LLM provider
4. Advanced metrics (P95/P99 latency tracking)

---

## SIGN-OFF

**Implementation Team**: AIE2 Shopping Copilot  
**Implementer**: Đặng Thị Ngọc Thảo  
**Date Completed**: 27/07/2026  
**Deadline**: 28/07/2026 (Tuesday)  
**Status**: ✅ **COMPLETE AND VERIFIED**

All 5 MANDATE #25 requirements implemented, tested, and ready for grading.

---

## REFERENCES

- **Mandate**: [`MANDATE-25-ai-resilience-fallback.md`](../../../../MANDATE-25-ai-resilience-fallback.md) (Phase3 root)
- **Test Cases**: [`mandate25/mandate_25_testcases.json`](../../mandate25/mandate_25_testcases.json)
- **Test Results**: [`mandate25/mandate_25_test_results.json`](../../mandate25/mandate_25_test_results.json)
- **Test Runner**: [`mandate25/run_mandate_25_tests.py`](../../mandate25/run_mandate_25_tests.py)
- **Mandate25 Guide**: [`mandate25/README.md`](../../mandate25/README.md)
- **Circuit Breaker Implementation**: [`src/guardrails/circuit_breaker.py`](../../src/guardrails/circuit_breaker.py)
- **Retry Logic**: [`src/guardrails/retry.py`](../../src/guardrails/retry.py)
- **Schema Validator**: [`src/guardrails/schema_validator.py`](../../src/guardrails/schema_validator.py)
- **Agent Integration**: [`src/agent/copilot_agent.py`](../../src/agent/copilot_agent.py) (lines 70-430)
- **Circuit Breaker Pattern**: Release It! (Michael Nygard)
- **Exponential Backoff**: AWS Retry Strategy Docs

