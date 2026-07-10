"""Tests for the C1–C6 gap closures: local matcher, audit log, verify loop, cost report,
resolved events, evidence-pack writer. One file, grouped by contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_engine.aie.cost_report import CostReporter, CostSnapshot, FeatureSpend
from ai_engine.aiops.audit_log import AuditLog
from ai_engine.aiops.audit_report import build_report, run_check
from ai_engine.aiops.local_matcher import match_incident_locally
from ai_engine.aiops.remediation import RemediationEngine, EXECUTION_TIMEOUT_S
from ai_engine.aiops.verify_loop import VerifyLoop
from ai_engine.common.config import CostConfig
from ai_engine.common.schemas import ActionType, ApprovalDecision


# ---------------- C4.6 local matcher ----------------

def test_local_matcher_inc2_never_restarts():
    d = match_incident_locally(culprit_service="cart", log_templates=[{"template": "valkey OOM"}])
    assert d.matched_incident == "INC-2"
    assert d.proposed_action == "none"       # HARD: never auto-restart single-replica cart
    assert d.action_command == ""

def test_local_matcher_inc1_scale():
    d = match_incident_locally(culprit_service="product-catalog",
                               log_templates=[{"template": "remaining connection slots"}])
    assert d.matched_incident == "INC-1"
    assert d.proposed_action == "scale"

def test_local_matcher_unknown_is_conservative():
    d = match_incident_locally(culprit_service="totally-new-svc", log_templates=[])
    assert d.matched_incident == "None"
    assert d.proposed_action == "none"

def test_local_matcher_by_log_only():
    d = match_incident_locally(culprit_service="unknown", log_templates=[{"message": "deadline exceeded grpc"}])
    assert d.matched_incident == "INC-3"


# ---------------- C6.8 append-only audit log ----------------

def _engine(tmp_path, calls=None):
    calls = calls if calls is not None else []
    def executor(record, mode):
        calls.append((record.action_id, mode))
        if mode == "rollback":
            return "rolled back"
        return "verified ok" if mode is False else "dry-run ok"
    eng = RemediationEngine(executor=executor, audit=AuditLog(tmp_path))
    return eng, calls

def test_audit_log_appends_lifecycle(tmp_path):
    eng, _ = _engine(tmp_path)
    rec = eng.propose(incident_id="TF3-20260710-0001", action=ActionType.SCALE,
                      target="deployment/checkout", parameters={"replicas": 4},
                      rationale="burn high", risk_note="cost", rollback_plan="scale to 2")
    eng.approve_and_execute(rec, approver="alice")
    records = AuditLog(tmp_path).read_incident("TF3-20260710-0001")
    # proposed + executed = 2 lines, same action_id, append-only
    assert len(records) == 2
    assert {r.action_id for r in records} == {rec.action_id}
    assert records[-1].approval.decision == ApprovalDecision.APPROVED

def test_audit_log_reject_persisted(tmp_path):
    eng, _ = _engine(tmp_path)
    rec = eng.propose(incident_id="TF3-20260710-0002", action=ActionType.RESTART,
                      target="deployment/frontend", parameters={}, rationale="r",
                      risk_note="n", rollback_plan="rollout undo")
    eng.reject(rec, approver="bob")
    records = AuditLog(tmp_path).read_incident("TF3-20260710-0002")
    assert records[-1].approval.decision == ApprovalDecision.REJECTED


# ---------------- C6.10 invariant check + report ----------------

def test_audit_check_passes_on_clean_run(tmp_path):
    eng, _ = _engine(tmp_path)
    rec = eng.propose(incident_id="TF3-20260710-0003", action=ActionType.SCALE,
                      target="deployment/checkout", parameters={"replicas": 3},
                      rationale="r", risk_note="n", rollback_plan="scale to 2")
    eng.approve_and_execute(rec, approver="carol")
    assert run_check(str(tmp_path)) == 0
    md = build_report(str(tmp_path))
    assert "PASS" in md and "approved" in md.lower()


# ---------------- C6.6/6.11 verify loop + auto-rollback ----------------

class _FakeProm:
    def __init__(self, values):
        self._values = list(values)
    async def scalar(self, query, default=None):
        return self._values.pop(0) if self._values else default

@pytest.mark.asyncio
async def test_verify_loop_recovers():
    prom = _FakeProm([0.05, 0.005])  # second poll healthy
    async def nosleep(_): pass
    vl = VerifyLoop(prom, window_s=60, poll_s=30, sleep=nosleep)
    res = await vl.verify(recovery_query="q", threshold=0.01)
    assert res.recovered is True

@pytest.mark.asyncio
async def test_verify_loop_no_recovery_triggers_rollback_semantics():
    prom = _FakeProm([0.5, 0.4, 0.3])  # never below threshold
    async def nosleep(_): pass
    vl = VerifyLoop(prom, window_s=60, poll_s=30, sleep=nosleep)
    res = await vl.verify(recovery_query="q", threshold=0.01)
    assert res.recovered is False

def test_execute_failure_auto_rolls_back(tmp_path):
    calls = []
    def executor(record, mode):
        calls.append(mode)
        if mode is False:
            raise RuntimeError("apply blew up")
        if mode == "rollback":
            return "rolled back ok"
        return "dry-run ok"
    escalations = []
    eng = RemediationEngine(executor=executor, audit=AuditLog(tmp_path),
                            escalate=lambda r, why: escalations.append(why))
    rec = eng.propose(incident_id="TF3-20260710-0004", action=ActionType.SCALE,
                      target="deployment/checkout", parameters={"replicas": 4},
                      rationale="r", risk_note="n", rollback_plan="scale to 2")
    eng.approve_and_execute(rec, approver="dave")
    assert rec.execution.result == "failed"
    assert "rollback" in [c for c in calls if c == "rollback"][0]  # rollback was attempted
    assert "ROLLED BACK" in rec.execution.verification
    assert escalations == []  # rollback succeeded → no escalation

def test_rollback_failure_escalates(tmp_path):
    def executor(record, mode):
        if mode is False:
            raise RuntimeError("apply blew up")
        if mode == "rollback":
            raise RuntimeError("rollback ALSO blew up")
        return "dry-run ok"
    escalations = []
    eng = RemediationEngine(executor=executor, audit=AuditLog(tmp_path),
                            escalate=lambda r, why: escalations.append(why))
    rec = eng.propose(incident_id="TF3-20260710-0005", action=ActionType.SCALE,
                      target="deployment/checkout", parameters={"replicas": 4},
                      rationale="r", risk_note="n", rollback_plan="scale to 2")
    eng.approve_and_execute(rec, approver="erin")
    assert "ROLLBACK FAILED" in rec.execution.verification
    assert len(escalations) == 1  # C6.11: human paged


# ---------------- C5.5/5.6 budget alerts ----------------

def test_cost_budget_warning_at_80pct():
    cfg = CostConfig(weekly_budget_usd=10.0)
    reporter = CostReporter(prom=None, cfg=cfg)
    snap = CostSnapshot(total_usd=8.5, per_feature=[FeatureSpend("review-summary", usd=8.5)])
    alerts = reporter.evaluate_budget(snap)
    assert len(alerts) == 1
    assert alerts[0].severity.value == "warning"
    assert alerts[0].source_layer.value == "cost"

def test_cost_budget_critical_at_100pct():
    cfg = CostConfig(weekly_budget_usd=10.0)
    reporter = CostReporter(prom=None, cfg=cfg)
    snap = CostSnapshot(total_usd=11.0, per_feature=[])
    alerts = reporter.evaluate_budget(snap)
    assert alerts[0].severity.value == "critical"
    assert "guardrail" in alerts[0].suggested_action.lower()

def test_cost_budget_no_alert_under_threshold():
    cfg = CostConfig(weekly_budget_usd=10.0)
    reporter = CostReporter(prom=None, cfg=cfg)
    snap = CostSnapshot(total_usd=1.0, per_feature=[])
    assert reporter.evaluate_budget(snap) == []

def test_cost_report_markdown_format():
    cfg = CostConfig(weekly_budget_usd=10.0)
    reporter = CostReporter(prom=None, cfg=cfg)
    snap = CostSnapshot(total_usd=2.0, cache_hit_ratio=0.5,
                        per_feature=[FeatureSpend("review-summary", tokens_in=1000, tokens_out=200, usd=2.0)])
    md = reporter.render_markdown(snap)
    assert "AI Cost Report" in md and "review-summary" in md and "trần $10.00" in md
