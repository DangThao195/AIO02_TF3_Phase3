import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("AIOpsEngine.AuditLogger")

AUDIT_LOG_FILE = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")

class AuditLogger:
    def __init__(self, log_file: str = AUDIT_LOG_FILE):
        self.log_file = log_file

    def log_remediation_event(
        self,
        incident_id: str,
        trigger: str,
        culprit_service: str,
        proposed_action: str,
        action_command: str,
        blast_radius_percent: float,
        risk_level: str,
        dry_run_passed: bool,
        executed: bool,
        verification_passed: bool,
        rollback_executed: bool,
        rollback_command: str = "",
        rollback_passed: bool = False,
        status: str = "UNKNOWN",
        message: str = ""
    ) -> dict:
        """
        Ghi vết sự kiện remediation khép kín dưới dạng JSON Lines (C3/C6 Compliance).
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incident_id": incident_id,
            "trigger": trigger,
            "culprit_service": culprit_service,
            "proposed_action": proposed_action,
            "action_command": action_command,
            "blast_radius_percent": round(blast_radius_percent, 2),
            "risk_level": risk_level,
            "dry_run_passed": dry_run_passed,
            "executed": executed,
            "verification_passed": verification_passed,
            "rollback_executed": rollback_executed,
            "rollback_command": rollback_command,
            "rollback_passed": rollback_passed,
            "status": status,
            "message": message
        }

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.info(f"[AuditLogger] Event logged for incident {incident_id} (Status: {status})")
        except Exception as e:
            logger.error(f"[AuditLogger] Failed to write audit log: {e}")

        return record

    def get_audit_logs(self, limit: int = 50) -> list[dict]:
        """
        Đọc danh sách các bản ghi audit log gần đây nhất.
        """
        if not os.path.exists(self.log_file):
            return []

        logs = []
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            logs.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            return logs[-limit:]
        except Exception as e:
            logger.error(f"[AuditLogger] Failed to read audit logs: {e}")
            return []

audit_logger = AuditLogger()
