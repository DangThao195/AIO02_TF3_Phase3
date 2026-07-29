import unittest
import time
import os
import sys

# Ensure aiops-engine is in sys.path
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

from rca_engine import RCAEngine


class TestCausalRCA(unittest.TestCase):
    def setUp(self):
        self.rca = RCAEngine()

    def test_first_drift_temporal_ordering(self):
        """
        [DIRECTIVE #26 - Test 1]
        Kiểm tra thuật toán Causal Inference phân biệt giữa Root Cause và Symptom dựa trên thứ tự mốc thời gian drift (t0 < t1).
        - payment: First-drift tại t0 (1000s ago) -> Root Cause
        - checkout: First-drift tại t1 (985s ago) -> Downstream Symptom
        - frontend: First-drift tại t2 (970s ago) -> Upstream Symptom
        """
        now = time.time()
        candidates = [
            {
                "service": "frontend",
                "lat": 4.5,
                "err": 0.12,
                "cpu": 0.05,
                "depth": 3,
                "is_downstream": False,
                "first_drift_ts": now - 970
            },
            {
                "service": "checkout",
                "lat": 5.8,
                "err": 0.25,
                "cpu": 0.10,
                "depth": 2,
                "is_downstream": False,
                "first_drift_ts": now - 985
            },
            {
                "service": "payment",
                "lat": 5.2,
                "err": 0.30,
                "cpu": 0.15,
                "depth": 1,
                "is_downstream": True,
                "first_drift_ts": now - 1000  # Drift xảy ra sớm nhất!
            }
        ]

        ranked = self.rca.rank_causal_candidates(candidates)
        
        self.assertTrue(len(ranked) == 3)
        # Hàng 1 (Rank #1) BẮT BUỘC phải là 'payment' vì drift sớm nhất t0 và nằm ở hạ nguồn
        self.assertEqual(ranked[0]["service"], "payment", "Root cause MUST be payment (earliest first-drift 3σ)")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"], "Payment score MUST be higher than checkout")
        self.assertGreater(ranked[1]["score"], ranked[2]["score"], "Checkout score MUST be higher than frontend")

    def test_correlation_noise_filtering(self):
        """
        [DIRECTIVE #26 - Test 2]
        Kiểm tra thuật toán loại bỏ nghi phạm biến động ngẫu nhiên do trùng hợp (Correlation vs Causation).
        - email: Có biến động độ trễ ngẫu nhiên (nhiễu) nhưng KHÔNG phải là target hạ nguồn và drift trễ.
        - product-reviews: Lọt vào lỗi thực tế ở hạ nguồn và drift sớm.
        """
        now = time.time()
        candidates = [
            {
                "service": "email",
                "lat": 6.0,  # Độ trễ vọt cao do nhiễu trùng hợp
                "err": 0.0,
                "cpu": 0.02,
                "depth": 3,
                "is_downstream": False,
                "first_drift_ts": now - 500  # Drift trễ hơn
            },
            {
                "service": "product-reviews",
                "lat": 4.8,
                "err": 0.40,
                "cpu": 0.20,
                "depth": 1,
                "is_downstream": True,
                "first_drift_ts": now - 1000  # Drift sớm nhất!
            }
        ]

        ranked = self.rca.rank_causal_candidates(candidates)
        
        self.assertEqual(ranked[0]["service"], "product-reviews", "Spurious noise on 'email' MUST be filtered out in favor of true causal root 'product-reviews'")

    def test_unseen_cascading_failure_ranking(self):
        """
        [DIRECTIVE #26 - Test 3]
        Kiểm tra khả năng chịu đựng kịch bản lạ ngoài bộ đã biết (Zero-Shot / Unseen Cascading Failure).
        Dịch vụ lạ 'custom-recommendation-db' có drift sớm nhất và downstream multiplier.
        """
        now = time.time()
        candidates = [
            {
                "service": "custom-recommendation-db",
                "lat": 8.0,
                "err": 0.90,
                "cpu": 0.85,
                "depth": 0,
                "is_downstream": True,
                "first_drift_ts": now - 1200
            },
            {
                "service": "recommendation",
                "lat": 6.5,
                "err": 0.50,
                "cpu": 0.30,
                "depth": 1,
                "is_downstream": False,
                "first_drift_ts": now - 1100
            }
        ]

        ranked = self.rca.rank_causal_candidates(candidates)
        self.assertEqual(ranked[0]["service"], "custom-recommendation-db")
        self.assertIn("First-drift bonus", ranked[0]["reason"])


if __name__ == "__main__":
    unittest.main()
