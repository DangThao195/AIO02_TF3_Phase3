from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ModelTrace:
    trace_id: str
    request_id: str
    parent_span_id: str | None
    surface: str
    layer: str
    model: str
    model_version: str
    session_id: str
    user_id: str
    timestamp: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    outcome: str
    error: str | None = None
    tool_calls: list | None = None
    prompt_preview: str | None = None
    response_preview: str | None = None
    prompt_masked: bool = True
    response_masked: bool = True
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
