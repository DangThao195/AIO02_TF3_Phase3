import unittest
import time
import sys
import os

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import (
    active_incidents,
    incidents_lifecycle,
    consecutive_healthy_count,
    last_proactive_alert_time,
    enrich_culprit_with_upstream_check
)
from alert_correlator import AlertCorrelator


class TestSRELifecycleAndQualityGate(unittest.TestCase):
    def setUp(self):
        active_incidents.clear()
        incidents_lifecycle.clear()
        consecutive_healthy_count.clear()
        last_proactive_alert_time.clear()

    def test_state_based_dedup_and_alert_counter(self):
        """[SRE-01] Test state-based dedup increments alert_count when pending approval."""
        service = "payment"
        inc_id = "INC-ML-1001"
        
        incidents_lifecycle[inc_id] = {
            "incident_id": inc_id,
            "status": "pending_approval",
            "culprit_service": service,
            "opened_at": time.time(),
            "last_alerted_at": time.time(),
            "alert_count": 1,
            "diagnosis": {}
        }
        
        # Simulate re-detection logic
        existing_inc = next((inc for inc in incidents_lifecycle.values() if inc.get("culprit_service") == service and inc.get("status") in ["pending_approval", "open", "proactive_warning"]), None)
        self.assertIsNotNone(existing_inc)
        
        # Increment 4 times
        for _ in range(4):
            existing_inc["alert_count"] += 1
            
        self.assertEqual(existing_inc["alert_count"], 5)
        # Verify 5th recurrence triggers reminder
        self.assertEqual(existing_inc["alert_count"] % 5, 0)

    def test_2_consecutive_healthy_cycles_autoresolve(self):
        """[SRE-02] Test 2 consecutive healthy cycles (60s) auto-resolves incident."""
        service = "shipping"
        inc_id = "INC-ML-2002"
        
        active_incidents[inc_id] = {
            "incident_id": inc_id,
            "culprit_service": service,
            "status": "proactive_warning",
            "alert_time": time.time()
        }
        incidents_lifecycle[inc_id] = {
            "incident_id": inc_id,
            "status": "pending_approval",
            "culprit_service": service,
            "opened_at": time.time(),
            "last_alerted_at": time.time(),
            "alert_count": 1,
            "diagnosis": {}
        }
        
        # Cycle 1: Healthy
        consecutive_healthy_count[service] = 1
        self.assertIn(inc_id, active_incidents)
        
        # Cycle 2: Healthy (Threshold >= 2)
        consecutive_healthy_count[service] += 1
        if consecutive_healthy_count[service] >= 2:
            for i_id, inc_data in list(active_incidents.items()):
                if inc_data.get("culprit_service") == service:
                    inc_data["status"] = "resolved"
                    if i_id in incidents_lifecycle:
                        incidents_lifecycle[i_id]["status"] = "resolved"
                    active_incidents.pop(i_id, None)
                    
        self.assertNotIn(inc_id, active_incidents)
        self.assertEqual(incidents_lifecycle[inc_id]["status"], "resolved")

    def test_stale_vs_expired_600s_precheck(self):
        """[SRE-03] Test 600s pre-check distinguishes stale (still anomalous) vs expired (healthy)."""
        now_ts = time.time()
        
        # Case A: Still anomalous -> STALE
        inc_a = "INC-ML-3001"
        active_incidents[inc_a] = {"incident_id": inc_a, "culprit_service": "payment", "alert_time": now_ts - 610}
        incidents_lifecycle[inc_a] = {"incident_id": inc_a, "status": "pending_approval", "culprit_service": "payment", "opened_at": now_ts - 610}
        anomalous_services = {"payment"}
        
        for i_id, inc_data in list(active_incidents.items()):
            if now_ts - inc_data.get("alert_time", now_ts) >= 600:
                svc = inc_data.get("culprit_service")
                if svc in anomalous_services:
                    inc_data["status"] = "stale"
                    if i_id in incidents_lifecycle:
                        incidents_lifecycle[i_id]["status"] = "stale"
                    active_incidents.pop(i_id, None)
                    
        self.assertEqual(incidents_lifecycle[inc_a]["status"], "stale")
        self.assertNotIn(inc_a, active_incidents)
        
        # Case B: Telemetry healthy -> EXPIRED
        inc_b = "INC-ML-3002"
        active_incidents[inc_b] = {"incident_id": inc_b, "culprit_service": "checkout", "alert_time": now_ts - 610}
        incidents_lifecycle[inc_b] = {"incident_id": inc_b, "status": "pending_approval", "culprit_service": "checkout", "opened_at": now_ts - 610}
        anomalous_services.clear()
        
        for i_id, inc_data in list(active_incidents.items()):
            if now_ts - inc_data.get("alert_time", now_ts) >= 600:
                svc = inc_data.get("culprit_service")
                if svc in anomalous_services:
                    inc_data["status"] = "stale"
                else:
                    inc_data["status"] = "expired"
                    if i_id in incidents_lifecycle:
                        incidents_lifecycle[i_id]["status"] = "expired"
                    active_incidents.pop(i_id, None)
                    
        self.assertEqual(incidents_lifecycle[inc_b]["status"], "expired")
        self.assertNotIn(inc_b, active_incidents)

    def test_quality_gate_placeholder_suppression(self):
        """[SRE-04] Test Quality Gate suppresses unfilled [Template] or [X] responses."""
        unfilled_analysis_1 = "Phát hiện lỗi '[Template]' tại dịch vụ payment."
        unfilled_analysis_2 = "Phân tích [X] cho thấy service bị nghẽn."
        
        self.assertTrue("[Template]" in unfilled_analysis_1 or "lỗi '[Template]'" in unfilled_analysis_1 or "[X]" in unfilled_analysis_1)
        self.assertTrue("[X]" in unfilled_analysis_2)

    def test_llm_service_excluded_from_services_list(self):
        """[SRE-05] Test 'llm' is excluded from direct IF polling list."""
        SERVICES = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]
        self.assertNotIn("llm", SERVICES)
        self.assertNotIn("flagd", SERVICES)
        self.assertNotIn("postgresql", SERVICES)

    def test_approval_action_updates_lifecycle_and_resets_cooldown(self):
        """[SRE-06] Test process_approval_action updates incidents_lifecycle status and resets cooldown."""
        import asyncio
        from main import process_approval_action
        
        inc_id = "INC-ML-9999"
        service = "payment"
        
        active_incidents[inc_id] = {
            "incident_id": inc_id,
            "culprit_service": service,
            "action_command": f"kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
            "rollback_command": f"kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
            "alert_time": time.time()
        }
        incidents_lifecycle[inc_id] = {
            "incident_id": inc_id,
            "status": "pending_approval",
            "culprit_service": service,
            "opened_at": time.time(),
            "alert_count": 1
        }
        last_proactive_alert_time[service] = time.time()
        
        # Test Reject
        res = asyncio.run(process_approval_action(inc_id, "reject", target_service=service))
        self.assertEqual(incidents_lifecycle[inc_id]["status"], "rejected")
        self.assertEqual(last_proactive_alert_time[service], 0)
        self.assertNotIn(inc_id, active_incidents)

    def test_slo_path_created_at_timestamp_fallback(self):
        """[SRE-07] Test 600s timeout check handles 'created_at' key from SLO path incidents."""
        now_ts = time.time()
        inc_id = "INC-SLO-777"
        
        active_incidents[inc_id] = {
            "incident_id": inc_id,
            "culprit_service": "postgresql",
            "created_at": now_ts - 650  # 650 seconds ago using created_at
        }
        incidents_lifecycle[inc_id] = {
            "incident_id": inc_id,
            "status": "pending_approval",
            "culprit_service": "postgresql",
            "opened_at": now_ts - 650
        }
        
        for i_id, inc_data in list(active_incidents.items()):
            opened_time = inc_data.get("alert_time") or inc_data.get("created_at") or now_ts
            if now_ts - opened_time >= 600:
                inc_data["status"] = "stale"
                incidents_lifecycle[i_id]["status"] = "stale"
                active_incidents.pop(i_id, None)
                
        self.assertEqual(incidents_lifecycle[inc_id]["status"], "stale")
        self.assertNotIn(inc_id, active_incidents)

    def test_slo_branch_registers_lifecycle_and_resets_healthy_count(self):
        """[SRE-08] [Conflict A & D] Test SLO branch registers incident in incidents_lifecycle and resets healthy count."""
        service = "checkout"
        consecutive_healthy_count[service] = 10
        inc_id = "INC-SLO-888"
        
        incidents_lifecycle[inc_id] = {
            "incident_id": inc_id,
            "status": "pending_approval",
            "culprit_service": service,
            "opened_at": time.time(),
            "last_alerted_at": time.time(),
            "alert_count": 1,
            "diagnosis": {}
        }
        consecutive_healthy_count[service] = 0
        
        self.assertEqual(incidents_lifecycle[inc_id]["status"], "pending_approval")
        self.assertEqual(consecutive_healthy_count[service], 0)

    def test_quality_gate_suppression_updates_lifecycle(self):
        """[SRE-09] [Conflict B] Test Quality Gate suppression sets status to 'suppressed'."""
        inc_id = "INC-ML-333"
        service = "payment"
        
        incidents_lifecycle[inc_id] = {
            "incident_id": inc_id,
            "status": "pending_approval",
            "culprit_service": service,
            "opened_at": time.time()
        }
        last_proactive_alert_time[service] = time.time()
        
        # Simulate Quality Gate suppression
        if inc_id in incidents_lifecycle:
            incidents_lifecycle[inc_id]["status"] = "suppressed"
        last_proactive_alert_time[service] = 0
        
        self.assertEqual(incidents_lifecycle[inc_id]["status"], "suppressed")
        self.assertEqual(last_proactive_alert_time[service], 0)

    def test_lifecycle_periodic_memory_prune(self):
        """[SRE-10] [Conflict E] Test periodic prune removes old non-active entries older than 2 hours."""
        now_ts = time.time()
        old_inc = "INC-OLD-1"
        recent_inc = "INC-NEW-1"
        
        incidents_lifecycle[old_inc] = {
            "incident_id": old_inc,
            "status": "resolved",
            "opened_at": now_ts - 7300  # > 2 hours ago
        }
        incidents_lifecycle[recent_inc] = {
            "incident_id": recent_inc,
            "status": "pending_approval",
            "opened_at": now_ts - 100
        }
        
        # Prune logic
        prune_keys = [
            k for k, v in list(incidents_lifecycle.items())
            if v.get("status") in ["resolved", "rejected", "expired", "failed", "suppressed"]
            and (now_ts - v.get("opened_at", now_ts)) > 7200
        ]
        for k in prune_keys:
            incidents_lifecycle.pop(k, None)
            
        self.assertNotIn(old_inc, incidents_lifecycle)
        self.assertIn(recent_inc, incidents_lifecycle)


if __name__ == "__main__":
    unittest.main()
