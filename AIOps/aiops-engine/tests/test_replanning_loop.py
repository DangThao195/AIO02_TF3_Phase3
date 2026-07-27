import unittest
from unittest.mock import MagicMock, patch
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from remediation_handler import RemediationHandler

class TestReplanningLoop(unittest.TestCase):
    def setUp(self):
        os.environ["AIOPS_SIMULATION_MODE"] = "true"
        self.handler = RemediationHandler()

    @patch("remediation_handler.RemediationHandler.verify_remediation")
    @patch("llm_diagnostician.LLMDiagnostician.diagnose")
    def test_replanning_loop_success_attempt_1(self, mock_diagnose, mock_verify):
        mock_diagnose.return_value = {
            "proposed_action": "scale",
            "action_command": "kubectl -n techx-tf3 scale deploy/payment --replicas=2",
            "rollback_command": "kubectl -n techx-tf3 scale deploy/payment --replicas=1"
        }
        mock_verify.return_value = True

        result = self.handler.execute_replanning_loop("INC-TEST-1", "payment", "trace-123", max_attempts=3)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["final_action"], "scale")

    @patch("remediation_handler.RemediationHandler.verify_remediation")
    @patch("llm_diagnostician.LLMDiagnostician.diagnose")
    def test_replanning_loop_exhausted_and_rolled_back(self, mock_diagnose, mock_verify):
        mock_diagnose.return_value = {
            "proposed_action": "scale",
            "action_command": "kubectl -n techx-tf3 scale deploy/payment --replicas=2",
            "rollback_command": "kubectl -n techx-tf3 scale deploy/payment --replicas=1"
        }
        # Force verify to fail for all 3 attempts
        mock_verify.return_value = False

        result = self.handler.execute_replanning_loop("INC-TEST-FAIL", "payment", "trace-456", max_attempts=3)
        
        self.assertEqual(result["status"], "rolled_back_exhausted")
        self.assertEqual(result["attempts"], 3)
        self.assertTrue(result["escalated"])
        self.assertTrue(result["rollback_passed"])

if __name__ == "__main__":
    unittest.main()
