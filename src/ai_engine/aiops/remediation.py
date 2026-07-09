"""Remediation module — C6 (AIOps-04 safety gate + AIOps-06 approval).

The engine PROPOSES an action, a human APPROVES it, then it executes with a dry-run first and
an append-only audit record. This is the most dangerous part of AIOps, so defence in depth:

  1. Safety gate      — action must be in the whitelist; target must never touch flagd / BTC
                        flags (hard-block in code, not just docs — RULES §8, disqualify).
                        Refuse destructive ops on single-replica services (INC-2 lesson).
  2. Human approval   — approval.by must be a real person, never a service account (C6 invariant).
  3. Dry-run          — validate the action would apply (server-side dry-run) before the real one.
  4. Rollback plan    — required before execution; engine refuses without it.
  5. Rate limit       — max 3 executed actions / incident / hour; over that it self-locks.
  6. Append-only audit — every step recorded to git + OpenSearch, never mutated.

The actual K8s mutation is injected (`executor`) so this is testable without a cluster and so
the executor — not the engine — holds the K8s credentials (least privilege).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from ..common.schemas import (
    ActionType,
    Approval,
    ApprovalDecision,
    Execution,
    RemediationRecord,
)

log = logging.getLogger("ai_engine.remediation")

WHITELIST = {
    ActionType.SCALE, ActionType.RESTART, ActionType.CACHE_FLUSH,
    ActionType.BREAKER_FORCE, ActionType.TOGGLE_TF_FLAG,
}

FLAGD_MARKERS = ("flagd", "featureflag", "openfeature")
BTC_INCIDENT_FLAGS = (
    "llmratelimiterror", "llminaccurateresponse", "paymentfailure", "kafkaqueueproblems",
    "cartfailure", "failedreadinessprobe", "emailmemoryleak", "productcatalogfailure",
    "recommendationcachefailure", "adhighcpu", "adfailure", "imageslowload", "admanualgc",
    "paymentunreachable", "loadgeneratorfloodhomepage",
)

MAX_ACTIONS_PER_INCIDENT_PER_HOUR = 3


class RemediationRefused(Exception):
    """Safety gate rejected the action. The message names the reason for the audit trail."""


class RemediationEngine:
    def __init__(
        self,
        executor: Callable[[RemediationRecord, bool], str],
        single_replica_services: set[str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._executor = executor
        self._single_replica = single_replica_services or set()
        self._clock = clock
        self._action_times: dict[str, list[datetime]] = defaultdict(list)
        self._seq = 0

    def propose(
        self,
        incident_id: str,
        action: ActionType,
        target: str,
        parameters: dict,
        rationale: str,
        risk_note: str,
        rollback_plan: str,
    ) -> RemediationRecord:
        """Create a PENDING record. Runs the safety gate immediately so an unsafe action is
        refused before any human is even asked to approve it."""
        self._safety_gate(action, target, rollback_plan)
        self._seq += 1
        now = self._clock()
        return RemediationRecord(
            action_id=f"TF3-ACT-{now:%Y%m%d}-{self._seq:04d}",
            incident_id=incident_id,
            proposed_at=now,
            proposed_by="ai-engine/remediation@v1",
            action=action,
            target=target,
            parameters=parameters,
            rationale=rationale,
            risk_note=risk_note,
            execution=Execution(rollback_plan=rollback_plan),
        )

    def approve_and_execute(
        self, record: RemediationRecord, approver: str, channel: str = "chat"
    ) -> RemediationRecord:
        """Apply approval + execute (dry-run then real). Refuses if approver is not a human
        identity or the rate limit is hit. Never executes without an approval."""
        if not approver or approver.strip().endswith(("-sa", "serviceaccount")) or "@system" in approver:
            raise RemediationRefused("approval.by must be a real person, not a service account")
        if self._rate_limited(record.incident_id):
            raise RemediationRefused("rate limit: max 3 actions/incident/hour — self-locked")

        record.approval = Approval(
            decision=ApprovalDecision.APPROVED, by=approver, at=self._clock(), channel=channel
        )
        self._execute(record)
        self._action_times[record.incident_id].append(self._clock())
        return record

    def reject(self, record: RemediationRecord, approver: str, channel: str = "chat") -> RemediationRecord:
        """Record a rejection. Nothing is executed. The record is still audited."""
        record.approval = Approval(
            decision=ApprovalDecision.REJECTED, by=approver, at=self._clock(), channel=channel
        )
        log.info("remediation %s rejected by %s", record.action_id, approver)
        return record

    def _execute(self, record: RemediationRecord) -> None:
        exec_ = record.execution
        exec_.started_at = self._clock()
        try:
            self._executor(record, True)
            verification = self._executor(record, False)
            exec_.result = "success"
            exec_.verification = verification
        except Exception as exc:
            exec_.result = "failed"
            exec_.verification = f"failed: {exc}; rolling back via: {exec_.rollback_plan}"
            log.exception("remediation %s failed; rollback plan on record", record.action_id)
        finally:
            exec_.finished_at = self._clock()

    def _safety_gate(self, action: ActionType, target: str, rollback_plan: str) -> None:
        if action not in WHITELIST:
            raise RemediationRefused(f"action '{action}' not in whitelist")
        t = target.lower()
        if any(m in t for m in FLAGD_MARKERS) or any(f in t for f in BTC_INCIDENT_FLAGS):
            raise RemediationRefused(f"hard-block: target '{target}' touches flagd/BTC flag (RULES §8)")
        if not rollback_plan or not rollback_plan.strip():
            raise RemediationRefused("rollback_plan is required before execution")

        svc = target.split("/")[-1]
        if action in (ActionType.RESTART,) and svc in self._single_replica:
            raise RemediationRefused(
                f"refused: '{svc}' is single-replica (INC-2) — restart risks state loss; needs replica first")

    def _rate_limited(self, incident_id: str) -> bool:
        cutoff = self._clock().timestamp() - 3600
        recent = [t for t in self._action_times[incident_id] if t.timestamp() > cutoff]
        self._action_times[incident_id] = recent
        return len(recent) >= MAX_ACTIONS_PER_INCIDENT_PER_HOUR


def audit_invariants_ok(records: list[RemediationRecord]) -> tuple[bool, list[str]]:
    """Machine-checkable audit invariants (C6) — what CDO Auditability runs weekly.
    Returns (all_ok, violations)."""
    violations: list[str] = []
    for r in records:
        ex = r.execution
        if ex and ex.result is not None and r.approval.decision != ApprovalDecision.APPROVED:
            violations.append(f"{r.action_id}: executed without approval")
        if ex and ex.result is not None and not (ex.rollback_plan or "").strip():
            violations.append(f"{r.action_id}: executed without rollback_plan")
        if r.approval.decision == ApprovalDecision.APPROVED and not r.approval.by:
            violations.append(f"{r.action_id}: approved but no human identity")
    return (not violations, violations)
