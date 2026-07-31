import unittest
import os
import sys

# Ensure aiops-engine is in sys.path
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

from rca_engine import RCAEngine
from llm_diagnostician import LLMDiagnostician
from main import enrich_culprit_with_upstream_check


class TestBugfixesAndZeroShot(unittest.TestCase):
    def setUp(self):
        self.rca = RCAEngine()
        self.diagnostician = LLMDiagnostician()

    def test_bug1_get_span_depth_exact_hops(self):
        """
        [TEST BUGFIX 1]
        Kiểm tra hàm locate_culprit_service và thuật toán get_span_depth tính chính xác số Hops từ Root down to Leaf.
        Chuỗi trace: frontend (root, depth=0) -> checkout (depth=1) -> payment (leaf error, depth=2).
        """
        mock_trace_data = {
            "data": [
                {
                    "traceID": "trace-bug1-test",
                    "spans": [
                        {
                            "spanID": "span_root",
                            "processID": "p_frontend",
                            "tags": []
                        },
                        {
                            "spanID": "span_child",
                            "processID": "p_checkout",
                            "references": [{"refType": "CHILD_OF", "spanID": "span_root"}],
                            "tags": []
                        },
                        {
                            "spanID": "span_leaf_error",
                            "processID": "p_payment",
                            "references": [{"refType": "CHILD_OF", "spanID": "span_child"}],
                            "tags": [{"key": "error", "value": True}]
                        }
                    ],
                    "processes": {
                        "p_frontend": {"serviceName": "frontend"},
                        "p_checkout": {"serviceName": "checkout"},
                        "p_payment": {"serviceName": "payment"}
                    }
                }
            ]
        }

        culprit = self.rca.locate_culprit_service(mock_trace_data)
        
        # Culprit BẮT BUỘC phải là 'payment' ở độ sâu 2 (Leaf error node)
        self.assertEqual(culprit, "payment", "Culprit localized MUST be payment at the leaf error node")

    def test_bug2_candidates_data_initialization_live_mode(self):
        """
        [TEST BUGFIX 2]
        Kiểm tra hàm enrich_root_cause_upstream() khởi tạo biến candidates_data = [] mà không bị NameError.
        """
        try:
            # Gọi hàm enrich_culprit_with_upstream_check với trigger_service='checkout'
            res = enrich_culprit_with_upstream_check("checkout", lookback_minutes=5)
            self.assertIsNotNone(res)
            self.assertIn(res, ["checkout", "payment", "recommendation", "product-catalog", "frontend", "shipping", "email"])
        except NameError as ne:
            self.fail(f"enrich_culprit_with_upstream_check raised NameError: {ne}. candidates_data was not initialized!")

    def test_zero_shot_unseen_incident_fallback(self):
        """
        [TEST ZERO-SHOT ENHANCEMENT]
        Kiểm tra tầng LLM Fallback (match_incident_locally) khi gặp sự cố hoàn toàn mới (Unseen Novel Failure).
        """
        evidence_pack = {
            "culprit_service": "custom_payment_v2",
            "trace_id": "trace-novel-9999",
            "log_templates": [
                {"template": "gRPC connection reset by peer in custom_payment_v2"}
            ]
        }

        res = self.diagnostician.match_incident_locally(evidence_pack)

        # 1. matched_incident phải ghi nhận kịch bản lạ
        self.assertEqual(res["matched_incident"], "None (Zero-Shot Unseen Incident)")

        # 2. confidence_score phải đạt 0.85 (không được là 0.0 hay báo lỗi LLM)
        self.assertEqual(res["confidence_score"], 0.85)

        # 3. Phép phân tích 'analysis' phải chứa đủ 4 đầu mục SRE tiêu chuẩn
        self.assertIn("* **Hiện tượng**", res["analysis"])
        self.assertIn("* **Nguyên nhân**", res["analysis"])
        self.assertIn("* **Bằng chứng**", res["analysis"])
        self.assertIn("* **Vùng ảnh hưởng (Blast Radius)**", res["analysis"])

        # 4. Lệnh khắc phục phải nhắm đúng culprit 'custom_payment_v2'
        self.assertIn("custom_payment_v2", res["action_command"])


if __name__ == "__main__":
    unittest.main()
