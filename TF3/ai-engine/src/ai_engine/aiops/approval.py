"""Approval gate rendering + callback (C6 / AIOps-06).

Turns a proposed RemediationRecord into an interactive Approve/Reject card, and parses the
callback back into a decision. Framework-agnostic: `render_slack_blockkit` is one adapter;
a plain webhook/CLI can use the same `parse_callback`. Keeping the transport out of the core
means it runs and tests with zero AWS/Slack dependency (the transport is wired at deploy time).

The card carries the RCA context on-call needs to decide: what, why, risk, rollback — so the
approver is not clicking blind.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..common.schemas import RemediationRecord


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass
class Callback:
    action_id: str
    decision: Decision
    user: str


def render_slack_blockkit(record: RemediationRecord, evidence_url: str | None = None) -> dict:
    """Slack Block Kit card with Approve/Reject buttons. `value` carries the action_id so the
    callback can be matched back to the record."""
    ex = record.execution
    fields = [
        f"*Action:* `{record.action}` → `{record.target}`",
        f"*Params:* `{record.parameters}`",
        f"*Vì sao:* {record.rationale}",
        f"*Rủi ro:* {record.risk_note}",
        f"*Rollback:* `{ex.rollback_plan if ex else '—'}`",
    ]
    if evidence_url:
        fields.append(f"*Evidence:* <{evidence_url}|xem Evidence Pack>")

    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text",
                                        "text": f"⚠ Remediation cần duyệt — {record.incident_id}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(fields)}},
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary",
                 "text": {"type": "plain_text", "text": "✅ Approve"},
                 "action_id": "approve", "value": record.action_id},
                {"type": "button", "style": "danger",
                 "text": {"type": "plain_text", "text": "❌ Reject"},
                 "action_id": "reject", "value": record.action_id},
            ]},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": "Người bấm = người chịu trách nhiệm (C6 audit). "
                                           "Engine không tự thực thi."}]},
        ]
    }


def parse_callback(payload: dict) -> Callback:
    """Parse a Slack interaction payload (or a compatible webhook body) into a Callback.

    Accepts either the Slack shape {user:{username}, actions:[{action_id,value}]} or a plain
    {user, decision, action_id}. Raises ValueError on a malformed/ambiguous payload — we never
    guess an approver identity."""

    if "decision" in payload and "action_id" in payload:
        user = payload.get("user") or ""
        if not user:
            raise ValueError("callback missing user identity")
        return Callback(action_id=payload["action_id"],
                        decision=Decision(payload["decision"]), user=user)


    actions = payload.get("actions") or []
    if not actions:
        raise ValueError("callback has no actions")
    act = actions[0]
    user = (payload.get("user") or {}).get("username") or (payload.get("user") or {}).get("id")
    if not user:
        raise ValueError("slack callback missing user identity")
    return Callback(action_id=act["value"], decision=Decision(act["action_id"]), user=user)
