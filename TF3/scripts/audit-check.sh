#!/usr/bin/env bash
# C6.10 — CDO Auditability runs this weekly to prove "mọi hành động truy được về người".
#
# It runs the machine-checkable C6 invariants over every TF3/incidents/*/actions.jsonl:
#   1. no execution without a human approval  2. every executed action has a rollback_plan
#   3. approved actions carry a real human identity
# Exit 0 = all invariants hold. Exit 1 = a violation (fail the Ops Review gate).
#
# Usage:  ./scripts/audit-check.sh [--report]
#   (no args)  -> invariant check only, prints PASS/FAIL
#   --report   -> also print the weekly markdown summary (C6.9)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$HERE/../ai-engine"          # TF3/ai-engine (has src/ai_engine)
INCIDENTS="$HERE/../incidents"        # TF3/incidents

# Prefer the engine's venv/python if present, else system python3.
PY="${PYTHON:-python3}"
export PYTHONPATH="$ENGINE/src:${PYTHONPATH:-}"

echo "== TF3 Remediation Audit Check =="
echo "incidents dir: $INCIDENTS"
echo

"$PY" -m ai_engine.aiops.audit_report check --incidents "$INCIDENTS"
rc=$?

if [[ "${1:-}" == "--report" ]]; then
  echo
  "$PY" -m ai_engine.aiops.audit_report report --incidents "$INCIDENTS"
fi

exit $rc
