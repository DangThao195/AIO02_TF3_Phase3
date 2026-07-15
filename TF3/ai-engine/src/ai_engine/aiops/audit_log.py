"""Append-only audit log — C6 §1/§5 durable Remediation Records to disk.

Every remediation record is written as ONE json line to
`TF3/incidents/<incident_id>/actions.jsonl` (invariant #5: append-only — never mutated,
never deleted; a correction is a NEW record pointing at the old action_id).

Design:
  - Append mode ("a") only. There is no update/delete API on purpose.
  - One directory per incident so the pack (C3) and its actions live together and go to git.
  - Records are the same Pydantic RemediationRecord as the wire schema, dumped in JSON mode
    so datetimes serialise the same way CDO's OpenSearch mirror sees them.
  - `read_incident` / `read_all` are for the weekly audit report + audit-check.sh; they
    tolerate a partially-written trailing line (crash mid-append) by skipping bad lines.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..common.schemas import RemediationRecord

log = logging.getLogger("ai_engine.audit_log")

# Repo-relative default: .../ai-engine/src/ai_engine/aiops/audit_log.py -> parents[4] == TF3/
_DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "incidents"


class AuditLog:
    def __init__(self, root: str | Path | None = None):
        self._root = Path(root) if root else _DEFAULT_ROOT

    def _path(self, incident_id: str) -> Path:
        # incident_id is engine-generated (TF3-YYYYMMDD-NNNN); still sanitise to be safe.
        safe = "".join(c for c in incident_id if c.isalnum() or c in "-_")
        return self._root / safe / "actions.jsonl"

    def append(self, record: RemediationRecord) -> Path:
        """Append one record as a json line. Returns the file path written.

        Called at every state transition (proposed, approved/rejected, executed) so the
        trail shows the full lifecycle, not just the final state — the record_id stays the
        same, so the latest line for an action_id is its current state.
        """
        path = self._path(record.incident_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json()
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        log.info("audit: appended %s (%s) -> %s", record.action_id, record.action.value, path)
        return path

    def read_incident(self, incident_id: str) -> list[RemediationRecord]:
        path = self._path(incident_id)
        if not path.exists():
            return []
        return self._parse(path)

    def read_all(self) -> list[RemediationRecord]:
        """Every record across every incident — input to the weekly audit report."""
        records: list[RemediationRecord] = []
        if not self._root.exists():
            return records
        for path in sorted(self._root.glob("*/actions.jsonl")):
            records.extend(self._parse(path))
        return records

    def _parse(self, path: Path) -> list[RemediationRecord]:
        out: list[RemediationRecord] = []
        for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(RemediationRecord.model_validate_json(raw))
            except Exception:
                # tolerate a torn trailing line from a crash mid-append; audit must not choke
                log.warning("audit: skipping unparseable line %d in %s", i, path)
        return out
