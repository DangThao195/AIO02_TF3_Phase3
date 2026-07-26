import os
import sys
import json
import pytest

# Ensure aiops-engine directory is on sys.path
engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

os.environ["AIOPS_SIMULATION_MODE"] = "true"

from fastapi.testclient import TestClient
from main import app, correlator
from audit_logger import audit_logger, AUDIT_LOG_FILE



def test_calculate_blast_radius():
    """
    Test 1: Kiểm tra tính toán % Blast Radius dựa trên 7 Application Services.
    """
    # 1. Test shipping (service ít ảnh hưởng hạ nguồn)
    blast_shipping = correlator.calculate_blast_radius("shipping")
    assert blast_shipping < 60.0, f"Shipping blast radius should be < 60%, got {blast_shipping}%"

    # 2. Test product-catalog (service được nhiều service gọi)
    blast_catalog = correlator.calculate_blast_radius("product-catalog")
    assert isinstance(blast_catalog, float)

    # 3. Test non-app node (ví dụ postgresql) -> trả về 0.0
    blast_db = correlator.calculate_blast_radius("postgresql")
    assert blast_db == 0.0


def test_audit_logger_write_and_read(tmp_path):
    """
    Test 2: Kiểm tra khả năng ghi vết Audit Log tiêu chuẩn JSON Lines.
    """
    test_log_file = os.path.join(tmp_path, "test_audit.jsonl")
    from audit_logger import AuditLogger
    logger_inst = AuditLogger(log_file=test_log_file)

    rec = logger_inst.log_remediation_event(
        incident_id="INC-TEST-001",
        trigger="TestTrigger",
        culprit_service="shipping",
        proposed_action="scale",
        action_command="kubectl -n techx-tf3 scale deploy/shipping --replicas=2",
        blast_radius_percent=14.29,
        risk_level="LOW",
        dry_run_passed=True,
        executed=True,
        verification_passed=True,
        rollback_executed=False,
        status="REMEDIATION_SUCCESS",
        message="Test success"
    )

    assert rec["incident_id"] == "INC-TEST-001"
    assert rec["dry_run_passed"] is True
    assert rec["verification_passed"] is True

    logs = logger_inst.get_audit_logs()
    assert len(logs) == 1
    assert logs[0]["incident_id"] == "INC-TEST-001"


def test_remediate_replay_endpoint_success_flow():
    """
    Test 3: Test Cửa Replay /simulate/remediate_replay luồng tự dập thành công.
    """
    client = TestClient(app)
    response = client.post(
        "/simulate/remediate_replay",
        json={"scenario": "inc1", "culprit_service": "shipping", "force_verify_fail": False}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["culprit_service"] == "shipping"
    assert data["dry_run_passed"] is True
    assert data["executed"] is True
    assert data["verification_passed"] is True
    assert data["rollback_executed"] is False
    assert data["audit_record"]["status"] == "REMEDIATION_SUCCESS"


def test_remediate_replay_endpoint_auto_rollback_flow():
    """
    Test 4: Test Cửa Replay /simulate/remediate_replay nhánh Verify FAIL -> TỰ ĐỘNG ROLLBACK!
    """
    client = TestClient(app)
    response = client.post(
        "/simulate/remediate_replay",
        json={"scenario": "inc1", "culprit_service": "shipping", "force_verify_fail": True}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["culprit_service"] == "shipping"
    assert data["dry_run_passed"] is True
    assert data["executed"] is True
    assert data["verification_passed"] is False, "Verification should fail due to force_verify_fail injection"
    assert data["rollback_executed"] is True, "Auto-rollback MUST be executed when verification fails"
    assert data["rollback_passed"] is True
    assert data["audit_record"]["status"] == "ROLLED_BACK_SUCCESSFULLY"


def test_audit_logs_endpoint():
    """
    Test 5: Kiểm tra API GET /audit/logs trả về lịch sử ghi vết.
    """
    client = TestClient(app)
    response = client.get("/audit/logs")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "audit_logs" in data
    assert isinstance(data["audit_logs"], list)
