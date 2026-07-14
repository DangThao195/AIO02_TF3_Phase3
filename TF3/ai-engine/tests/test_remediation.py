"""C6 remediation + approval tests (AIOps-04/06). The safety envelope, not K8s itself."""
from __future__ import annotations

import tempfile

import pytest

from ai_engine.aiops.approval import Decision, parse_callback, render_slack_blockkit
from ai_engine.aiops.audit_log import AuditLog
from ai_engine.aiops.remediation import (
    RemediationEngine,
    RemediationRefused,
    audit_invariants_ok,
)
from ai_engine.common.schemas import ActionType, ApprovalDecision


def _engine(calls=None, single_replica=None):
    calls = calls if calls is not None else []
    def executor(record, dry_run):
        calls.append((record.action_id, dry_run))
        return "p99 back to baseline" if not dry_run else "dry-run ok"
    # Isolate the audit sink to a temp dir so tests never write to the real TF3/incidents/.
    audit = AuditLog(tempfile.mkdtemp(prefix="tf3-audit-test-"))
    return RemediationEngine(
        executor=executor, single_replica_services=single_replica or set(), audit=audit
    ), calls


def _propose(eng, action=ActionType.SCALE, target="deployment/payment", rollback="scale to 2"):
    return eng.propose(
        incident_id="INC-1", action=action, target=target,
        parameters={"replicas_from": 2, "replicas_to": 4}, rationale="p99 x8",
        risk_note="+$0.4/h", rollback_plan=rollback,
    )


# ── safety gate ──
def test_hard_block_flagd_target():
    eng, _ = _engine()
    with pytest.raises(RemediationRefused, match="flagd"):
        _propose(eng, action=ActionType.TOGGLE_TF_FLAG, target="flagd/llmRateLimitError")


def test_hard_block_btc_incident_flag():
    eng, _ = _engine()
    with pytest.raises(RemediationRefused, match="flagd|flag"):
        _propose(eng, action=ActionType.TOGGLE_TF_FLAG, target="paymentFailure")


def test_refuse_action_without_rollback_plan():
    eng, _ = _engine()
    with pytest.raises(RemediationRefused, match="rollback"):
        _propose(eng, rollback="")


def test_refuse_restart_of_single_replica_service_inc2():
    eng, _ = _engine(single_replica={"cart"})
    with pytest.raises(RemediationRefused, match="single-replica"):
        _propose(eng, action=ActionType.RESTART, target="deployment/cart")


# ── approval + execution ──
def test_execute_requires_human_approver():
    eng, _ = _engine()
    rec = _propose(eng)
    with pytest.raises(RemediationRefused, match="real person"):
        eng.approve_and_execute(rec, approver="ai-engine-sa")


def test_dry_run_precedes_real_execution():
    eng, calls = _engine()
    rec = _propose(eng)
    eng.approve_and_execute(rec, approver="kiet")
    assert calls == [(rec.action_id, True), (rec.action_id, False)]  # dry-run THEN real
    assert rec.execution.result == "success"
    assert rec.approval.by == "kiet"


def test_reject_records_and_does_not_execute():
    eng, calls = _engine()
    rec = _propose(eng)
    eng.reject(rec, approver="bao")
    assert rec.approval.decision is ApprovalDecision.REJECTED
    assert calls == []                        # nothing executed
    assert rec.execution.result is None


def test_rate_limit_after_three_actions():
    eng, _ = _engine()
    for _ in range(3):
        eng.approve_and_execute(_propose(eng), approver="kiet")
    with pytest.raises(RemediationRefused, match="rate limit"):
        eng.approve_and_execute(_propose(eng), approver="kiet")


# ── audit invariants (what CDO runs weekly) ──
def test_audit_invariants_pass_on_clean_records():
    eng, _ = _engine()
    rec = _propose(eng)
    eng.approve_and_execute(rec, approver="kiet")
    ok, violations = audit_invariants_ok([rec])
    assert ok and violations == []


# ── approval card + callback ──
def test_slack_card_has_approve_reject_buttons():
    eng, _ = _engine()
    rec = _propose(eng)
    card = render_slack_blockkit(rec, evidence_url="http://x/evidence")
    buttons = card["blocks"][2]["elements"]
    assert {b["action_id"] for b in buttons} == {"approve", "reject"}
    assert all(b["value"] == rec.action_id for b in buttons)  # matches back to the record


def test_parse_slack_callback_extracts_user_and_decision():
    payload = {"user": {"username": "kiet"},
               "actions": [{"action_id": "approve", "value": "TF3-ACT-1"}]}
    cb = parse_callback(payload)
    assert cb.decision is Decision.APPROVE and cb.user == "kiet" and cb.action_id == "TF3-ACT-1"


def test_parse_callback_refuses_anonymous():
    with pytest.raises(ValueError, match="user"):
        parse_callback({"actions": [{"action_id": "approve", "value": "X"}]})
