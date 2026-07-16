"""Audit report + invariant CLI — C6.9 (weekly report) + C6.10 (audit-check).

Two entry points, one module:

  python -m ai_engine.aiops.audit_report check   [--incidents DIR]
      Runs the machine-checkable C6 invariants over every actions.jsonl. Exit 0 = all pass,
      exit 1 = a violation (so CI / CDO's audit-check.sh fails loudly). This is the
      "truy được về người" proof the judges demand.

  python -m ai_engine.aiops.audit_report report  [--incidents DIR] [--out FILE]
      Emits the weekly Ops-Review markdown: proposed / approved / rejected / failed counts,
      invariant pass/fail, and the most-rejected action (a signal to tune the catalog).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone

from ..common.schemas import ApprovalDecision, RemediationRecord
from .audit_log import AuditLog
from .remediation import audit_invariants_ok


def _latest_per_action(records: list[RemediationRecord]) -> list[RemediationRecord]:
    """actions.jsonl carries one line PER state transition. For counting, collapse to the
    latest line per action_id (its final observed state)."""
    latest: dict[str, RemediationRecord] = {}
    for r in records:
        latest[r.action_id] = r  # file order is chronological → last write wins
    return list(latest.values())


def run_check(incidents_dir: str | None) -> int:
    records = AuditLog(incidents_dir).read_all()
    ok, violations = audit_invariants_ok(records)
    if ok:
        print(f"AUDIT OK — {len(_latest_per_action(records))} action(s), 0 violations")
        return 0
    print(f"AUDIT FAILED — {len(violations)} violation(s):", file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


def build_report(incidents_dir: str | None) -> str:
    records = AuditLog(incidents_dir).read_all()
    actions = _latest_per_action(records)
    ok, violations = audit_invariants_ok(records)

    proposed = len(actions)
    approved = sum(1 for r in actions if r.approval.decision == ApprovalDecision.APPROVED)
    rejected = sum(1 for r in actions if r.approval.decision == ApprovalDecision.REJECTED)
    executed = [r for r in actions if r.execution and r.execution.result]
    failed = sum(1 for r in executed if r.execution.result in ("failed", "timeout"))

    reject_by_action = Counter(
        r.action.value for r in actions if r.approval.decision == ApprovalDecision.REJECTED
    )
    top_rejected = reject_by_action.most_common(1)
    top_rejected_str = f"{top_rejected[0][0]} ({top_rejected[0][1]}×)" if top_rejected else "—"

    have_rollback = all((r.execution and (r.execution.rollback_plan or "").strip())
                        for r in executed) if executed else True
    have_approval = all(r.approval.decision == ApprovalDecision.APPROVED and r.approval.by
                        for r in executed) if executed else True

    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    lines = [
        f"# Remediation Audit Report — {year}-W{week:02d}",
        f"> Sinh tự động {now.isoformat()} (C6.9). Trụ Auditability xác nhận trong Ops Review.",
        "",
        "## Tổng hợp action",
        f"- Đề xuất (proposed): **{proposed}**",
        f"- Được duyệt (approved): **{approved}**",
        f"- Bị từ chối (rejected): **{rejected}**",
        f"- Đã thực thi (executed): **{len(executed)}** — trong đó thất bại/timeout: **{failed}**",
        "",
        "## Invariant check (C6 §2)",
        f"- 100% executed có approval của con người: **{'PASS' if have_approval else 'FAIL'}**",
        f"- 100% executed có rollback_plan: **{'PASS' if have_rollback else 'FAIL'}**",
        f"- Tổng invariant: **{'PASS ✅' if ok else 'FAIL ❌'}**",
    ]
    if violations:
        lines += ["", "### Vi phạm:"] + [f"- {v}" for v in violations]
    lines += [
        "",
        "## Tín hiệu điều chỉnh catalog",
        f"- Action bị từ chối nhiều nhất: **{top_rejected_str}** "
        f"(nhiều = xem lại catalog hoặc engine).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="audit_report")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="run C6 invariants; exit 1 on violation")
    c.add_argument("--incidents", default=None)
    r = sub.add_parser("report", help="emit weekly markdown report")
    r.add_argument("--incidents", default=None)
    r.add_argument("--out", default=None)
    args = p.parse_args(argv)

    if args.cmd == "check":
        return run_check(args.incidents)
    md = build_report(args.incidents)
    if args.out:
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
