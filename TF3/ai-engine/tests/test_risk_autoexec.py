"""G1+G2: Risk Assessment (Low/Medium/High) + nhánh auto-execute Low-risk.

Đối chiếu sơ đồ closed-loop: Dry-run + Blast Radius → Risk Assessment →
Low=Execute(auto) / Medium=Human Approval / High=Reject. Vẫn giữ dry-run + verify + rollback.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_engine.aiops.action_policy import (
    ActionProposal,
    RiskDecision,
    RiskLevel,
    assess_risk,
)
from ai_engine.aiops.audit_log import AuditLog
from ai_engine.aiops.remediation import AUTO_APPROVER, RemediationEngine, RemediationRefused
from ai_engine.common.schemas import ActionType, ApprovalDecision


def _proposal(action=ActionType.SCALE, target="deployment/recommendation"):
    return ActionProposal(
        action=action, target=target, parameters={"replicas": 3, "replicas_from": 1},
        rationale="test", risk_note="rn", rollback_plan="scale back",
    )


# ── Risk Assessment ──
def test_low_risk_idempotent_narrow_nontier1_confident():
    r = assess_risk(_proposal(), blast_radius=["recommendation"], dry_run_ok=True, confidence=1.0)
    assert r.level is RiskLevel.LOW and r.decision is RiskDecision.EXECUTE


def test_dry_run_fail_is_high_reject():
    r = assess_risk(_proposal(), blast_radius=["recommendation"], dry_run_ok=False, confidence=1.0)
    assert r.level is RiskLevel.HIGH and r.decision is RiskDecision.REJECT
    assert "dry-run" in r.reasons[0]


def test_wide_blast_is_high_reject():
    r = assess_risk(_proposal(),
                    blast_radius=["a", "b", "c", "d", "e"], dry_run_ok=True, confidence=1.0)
    assert r.level is RiskLevel.HIGH and r.decision is RiskDecision.REJECT


def test_tier1_service_forces_medium_approval():
    # checkout = tier-1 → dù scale idempotent vẫn phải có người duyệt vòng đầu
    r = assess_risk(_proposal(target="deployment/checkout"),
                    blast_radius=["checkout"], dry_run_ok=True, confidence=1.0)
    assert r.level is RiskLevel.MEDIUM and r.decision is RiskDecision.APPROVAL


def test_non_idempotent_action_is_medium():
    r = assess_risk(_proposal(action=ActionType.RESTART, target="deployment/recommendation"),
                    blast_radius=["recommendation"], dry_run_ok=True, confidence=1.0)
    assert r.level is RiskLevel.MEDIUM


def test_low_confidence_forces_medium():
    r = assess_risk(_proposal(), blast_radius=["recommendation"], dry_run_ok=True, confidence=0.7)
    assert r.level is RiskLevel.MEDIUM
    assert any("confidence" in x for x in r.reasons)


def test_medium_blast_forces_medium():
    r = assess_risk(_proposal(), blast_radius=["recommendation", "ad"],
                    dry_run_ok=True, confidence=1.0)
    assert r.level is RiskLevel.MEDIUM


# ── auto_execute (nhánh Low) ──
def _engine(calls=None):
    calls = calls if calls is not None else []
    def executor(record, dry_run):
        calls.append((record.action_id, dry_run))
        return "ok" if dry_run else "p99 back to baseline"
    audit = AuditLog(tempfile.mkdtemp(prefix="tf3-risk-test-"))
    return RemediationEngine(executor=executor, audit=audit), calls


def _rec(eng):
    return eng.propose(
        incident_id="INC-x", action=ActionType.SCALE, target="deployment/recommendation",
        parameters={"replicas_from": 1, "replicas_to": 3}, rationale="lag",
        risk_note="rn", rollback_plan="scale to 1",
    )


def test_auto_execute_runs_dry_run_then_real_without_human():
    eng, calls = _engine()
    rec = _rec(eng)
    eng.auto_execute(rec)
    assert calls == [(rec.action_id, True), (rec.action_id, False)]  # dry-run THEN real
    assert rec.execution.result == "success"
    assert rec.approval.decision is ApprovalDecision.APPROVED
    assert rec.approval.by == AUTO_APPROVER  # ghi rõ auto, không giả danh người


def test_auto_execute_still_hits_safety_gate_via_propose():
    # flagd target không bao giờ tới được auto_execute — propose đã raise trước
    eng, _ = _engine()
    with pytest.raises(RemediationRefused, match="flagd"):
        eng.propose(incident_id="INC-x", action=ActionType.TOGGLE_TF_FLAG,
                    target="flagd/paymentFailure", parameters={}, rationale="r",
                    risk_note="rn", rollback_plan="rb")


def test_auto_execute_respects_rate_limit():
    eng, _ = _engine()
    for _ in range(3):
        eng.auto_execute(_rec(eng))
    with pytest.raises(RemediationRefused, match="rate limit"):
        eng.auto_execute(_rec(eng))


def test_auto_execute_audit_invariants_ok():
    # Auto action vẫn phải: có approval (AUTO_APPROVER), có rollback_plan → audit sạch
    from ai_engine.aiops.remediation import audit_invariants_ok
    eng, _ = _engine()
    rec = _rec(eng)
    eng.auto_execute(rec)
    ok, violations = audit_invariants_ok([rec])
    assert ok, violations
