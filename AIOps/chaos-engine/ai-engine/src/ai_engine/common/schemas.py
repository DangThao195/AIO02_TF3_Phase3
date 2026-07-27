"""Contract schemas as Pydantic models — the wire format between AIO and CDO.

Mirrors the JSON in contracts/C2-anomaly-alert-event.md and C6-remediation-audit.md.
Keeping these as typed models means a schema drift breaks at validation time (loud),
not silently downstream. `schema_version` is bumped per contract versioning rules.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class SourceLayer(str, Enum):
    SLO_BURNRATE = "slo-burnrate"
    ML_ANOMALY = "ml-anomaly"
    COST = "cost"


class AlertWindows(BaseModel):
    long: str
    short: str


class AlertEvidence(BaseModel):
    promql: str | None = None
    grafana_panel: str | None = None
    trace_ids: list[str] = Field(default_factory=list)
    log_query: str | None = None


class AlertEvent(BaseModel):
    """C2 — the single event type the engine pushes to on-call.

    Answers 3 questions at a glance: what hurts, how bad, what next.
    """

    schema_version: Literal["1.0"] = "1.0"
    alert_id: str
    fingerprint: str
    status: Literal["firing", "resolved"] = "firing"
    severity: Severity
    source_layer: SourceLayer
    service: str
    sli_impacted: str
    slo_target: float | None = None
    current_value: float | None = None
    burn_rate: float | None = None
    windows: AlertWindows | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    confidence: float = 1.0
    correlated_signals: list[str] = Field(default_factory=list)
    probable_blast_radius: list[str] = Field(default_factory=list)
    evidence: AlertEvidence = Field(default_factory=AlertEvidence)
    suggested_action: str | None = None
    runbook_link: str | None = None
    requires_ack_within: str | None = None


class ActionType(str, Enum):
    SCALE = "scale"
    RESTART = "restart"
    TOGGLE_TF_FLAG = "toggle-tf-flag"
    CACHE_FLUSH = "cache-flush"
    BREAKER_FORCE = "breaker-force"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"


class Approval(BaseModel):
    decision: ApprovalDecision = ApprovalDecision.PENDING
    by: str | None = None
    at: datetime | None = None
    channel: str | None = None


class Execution(BaseModel):
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: Literal["success", "failed", "timeout"] | None = None
    verification: str | None = None
    rollback_plan: str


class RemediationRecord(BaseModel):
    """C6 — append-only audit record. Every automated action is traceable to a person."""

    schema_version: Literal["1.0"] = "1.0"
    action_id: str
    incident_id: str
    proposed_at: datetime
    proposed_by: str
    action: ActionType
    target: str
    parameters: dict = Field(default_factory=dict)
    rationale: str
    risk_note: str
    approval: Approval = Field(default_factory=Approval)
    execution: Execution | None = None
