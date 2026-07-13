import unittest
import json
import os
import sys

# Thêm thư mục aiops-engine vào path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rca_engine import RCAEngine
from evidence_collector import EvidenceCollector
from llm_diagnostician import LLMDiagnostician
from remediation_handler import RemediationHandler

class TestAIOpsE2E(unittest.TestCase):
    def setUp(self):
        # Thiết lập đường dẫn tương đối tới thư mục fixtures
        self.fixtures_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
        self.rca = RCAEngine()
        self.collector = EvidenceCollector()
        self.diagnostician = LLMDiagnostician()
        self.handler = RemediationHandler()

    def test_inc1_rca_locates_postgresql(self):
        """Verify that RCA engine correctly identifies postgresql as the culprit for INC-1."""
        fixture_path = os.path.join(self.fixtures_dir, "inc1_trace_response.json")
        with open(fixture_path, "r") as f:
            trace_data = json.load(f)
            
        culprit = self.rca.locate_culprit_service(trace_data)
        self.assertEqual(culprit, "postgresql", f"Expected postgresql, got '{culprit}'")

    def test_inc2_rca_locates_cart(self):
        """Verify that RCA engine correctly identifies cart as the culprit for INC-2."""
        fixture_path = os.path.join(self.fixtures_dir, "inc2_trace_response.json")
        with open(fixture_path, "r") as f:
            trace_data = json.load(f)
            
        culprit = self.rca.locate_culprit_service(trace_data)
        self.assertEqual(culprit, "valkey-cart", f"Expected valkey-cart, got '{culprit}'")

    def test_inc3_rca_locates_fraud_detection(self):
        """Verify that RCA engine correctly identifies fraud-detection as the culprit for INC-3."""
        fixture_path = os.path.join(self.fixtures_dir, "inc3_trace_response.json")
        with open(fixture_path, "r") as f:
            trace_data = json.load(f)
            
        culprit = self.rca.locate_culprit_service(trace_data)
        self.assertEqual(culprit, "fraud-detection", f"Expected fraud-detection, got '{culprit}'")

    def test_drain3_log_clustering(self):
        """Verify that Drain3 correctly clusters logs into templates."""
        fixture_path = os.path.join(self.fixtures_dir, "inc3_logs.json")
        with open(fixture_path, "r") as f:
            raw_logs = json.load(f)
            
        templates = self.collector.cluster_logs(raw_logs)
        self.assertTrue(len(templates) > 0, "Log templates should not be empty")
        
        # NOTE: Day la gia dinh rang Drain3 se giu nguyen chu 'EventStream' vi day la 
        # tu hang so (constant) va khong chứa tham số biến động như IP/ID.
        found_eventstream = False
        for t in templates:
            if "eventstream" in t["template"].lower():
                found_eventstream = True
                break
        self.assertTrue(found_eventstream, "Failed to cluster EventStream log message")

    def test_incident_matching_inc1(self):
        """Verify local pattern matching identifies INC-1 (PostgreSQL pool exhaustion)."""
        evidence_pack = {
            "culprit_service": "postgresql",
            "log_templates": [
                {"template": "connection pool exhausted", "count": 5}
            ]
        }
        diagnosis = self.diagnostician.match_incident_locally(evidence_pack)
        self.assertEqual(diagnosis["matched_incident"], "INC-1")
        self.assertEqual(diagnosis["proposed_action"], "scale")
        self.assertIn("deploy/product-catalog", diagnosis["action_command"])


    def test_incident_matching_inc2(self):
        """Verify local pattern matching identifies INC-2 (Valkey / Cart OOM)."""
        evidence_pack = {
            "culprit_service": "cart",
            "log_templates": [
                {"template": "oom-killed: container exceeded memory limit 20mi", "count": 1}
            ]
        }
        diagnosis = self.diagnostician.match_incident_locally(evidence_pack)
        self.assertEqual(diagnosis["matched_incident"], "INC-2")
        self.assertEqual(diagnosis["proposed_action"], "none")
        self.assertEqual(diagnosis["action_command"], "")


    def test_incident_matching_inc3(self):
        """Verify local pattern matching identifies INC-3 (fraud-detection EventStream timeout)."""
        evidence_pack = {
            "culprit_service": "fraud-detection",
            "log_templates": [
                {"template": "EventStream: connection deadline exceeded in 10m", "count": 2}
            ]
        }
        diagnosis = self.diagnostician.match_incident_locally(evidence_pack)
        self.assertEqual(diagnosis["matched_incident"], "INC-3")
        self.assertEqual(diagnosis["proposed_action"], "cache-flush")
        self.assertIn("deploy/fraud-detection", diagnosis["action_command"])

    def test_validation_gate_whitelisting(self):
        """Verify that validation gate blocks non-whitelisted actions and dangerous keywords."""
        # Test whitelisted action
        self.assertTrue(self.handler.validate_action("cache-flush", "kubectl exec deploy/product-catalog -- flush"))
        
        # Test non-whitelisted action
        self.assertFalse(self.handler.validate_action("delete-pods", "kubectl delete pods --all"))
        
        # Test dangerous keyword blocking (e.g. bash injection)
        self.assertFalse(self.handler.validate_action("cache-flush", "kubectl exec deploy/product-catalog -- bash -c 'rm -rf /'"))
        self.assertFalse(self.handler.validate_action("cache-flush", "kubectl exec deploy/product-catalog -- flagd-sync"))

if __name__ == "__main__":
    unittest.main()
