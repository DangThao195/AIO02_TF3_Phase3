"""
Guardrails Module — Export tập trung tất cả lớp bảo vệ.

Thành viên 2 (Agent) chỉ cần import:
    from guardrails import check_input, request_confirmation, with_fallback, ...
"""

# ── Lớp 2: Input Filter — chặn Prompt Injection (2 tầng: Regex + Bedrock) ──
from guardrails.input_filter import check_input, check_input_bedrock, InputFilterResult

# ── Lớp 1: Confirmation Gate — chặn Excessive-Agency ──
from guardrails.confirmation import (
    request_confirmation,
    verify_confirmation_token,
    generate_confirmation_token,
    ConfirmationResult,
    DENIED_ACTIONS,
    CONFIRM_REQUIRED_ACTIONS,
)

# ── Lớp 3: Fallback — bọc lỗi LLM/gRPC ──
from guardrails.fallback import (
    with_fallback,
    handle_exception,
    make_error_response,
    MaxIterationsExceeded,
    CopilotServiceError,
    MAX_TOOL_ITERATIONS,
)

# ── Lớp 4: Tool Validator — Allow-list + User Isolation + Parameter Bounds ──
from guardrails.tool_validator import (
    validate_tool_call,
    ToolValidationResult,
    ALLOWED_TOOLS,
)

# ── Lớp 5: Output Filter — lọc PII/nội bộ trong phản hồi LLM ──
from guardrails.output_filter import (
    filter_output,
    OutputFilterResult,
)

# ── Lớp 6: Rate Limiter — giới hạn request/token per user ──
from guardrails.rate_limiter import (
    rate_limiter,
    RateLimiter,
    RateLimitResult,
)
