import unittest
import numpy as np
import pandas as pd
import os
import sys

# Ensure aiops-engine is in sys.path
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

from drift_detector import DataDriftDetector


class TestDataDriftDetector(unittest.TestCase):
    def setUp(self):
        self.detector = DataDriftDetector(num_bins=10, window_size=10, step_size=2)
        np.random.seed(42)
        
        # Thiết lập Baseline mẫu chuẩn (Normal baseline)
        self.baseline_latency = np.random.normal(loc=0.05, scale=0.01, size=500)
        self.baseline_rps = np.random.normal(loc=150.0, scale=10.0, size=500)
        self.baseline_cpu = np.random.normal(loc=0.15, scale=0.02, size=500)
        self.baseline_conf = np.random.normal(loc=0.95, scale=0.02, size=500)
        self.baseline_centroid = np.random.normal(loc=0.10, scale=0.05, size=128)

        self.detector.set_baseline("latency_p90", self.baseline_latency)
        self.detector.set_baseline("rps", self.baseline_rps)
        self.detector.set_baseline("cpu_usage", self.baseline_cpu)
        self.detector.set_baseline("cpu_per_rps", self.baseline_cpu / (self.baseline_rps + 1e-5))
        self.detector.set_baseline("llm_confidence_score", self.baseline_conf)
        self.detector.set_embedding_centroid(self.baseline_centroid)

    def test_sliding_window_pinpoints_drift_timestamp(self):
        """
        [DIRECTIVE #27 - Test 1]
        Kiểm tra Sliding Window Scanner chỉ ra CHÍNH XÁC timestamp và row_index bắt đầu xuất hiện Drift.
        - Rows 0..19: Normal
        - Rows 20..39: Latency Drift vọt cao
        """
        timestamps = [f"2026-07-28T20:{i:02d}:00Z" for i in range(40)]
        latencies = list(np.random.normal(loc=0.05, scale=0.01, size=20)) + list(np.random.normal(loc=0.45, scale=0.05, size=20))
        rps_vals = list(np.random.normal(loc=150.0, scale=10.0, size=40))

        df = pd.DataFrame({
            "timestamp": timestamps,
            "latency_p90": latencies,
            "rps": rps_vals
        })

        res = self.detector.detect_sliding_window_drift(df, psi_threshold=0.25)

        self.assertTrue(res["drift_detected"], "Sliding window scanner MUST detect latency drift")
        drifted_names = [m["metric"] for m in res["drifted_metrics"]]
        self.assertIn("latency_p90", drifted_names, "latency_p90 MUST be identified in drifted_metrics")
        
        drift_info = next(m for m in res["drifted_metrics"] if m["metric"] == "latency_p90")
        self.assertIsNotNone(drift_info["first_drift_timestamp"])
        self.assertGreaterEqual(drift_info["first_drift_row_index"], 10, "Drift start index should pinpoint window around row 15..20")

    def test_peak_hour_traffic_normalization_no_false_alarm(self):
        """
        [DIRECTIVE #27 - Test 2]
        Kiểm tra biến động lưu lượng giao thông giờ cao điểm (Peak-hour RPS) KHÔNG gây báo giả (No False Positive).
        """
        # RPS tăng gấp đôi do giờ cao điểm hợp lệ, nhưng CPU/RPS tỷ lệ thuận bình thường
        peak_rps = np.random.normal(loc=300.0, scale=15.0, size=50)
        peak_cpu = np.random.normal(loc=0.30, scale=0.03, size=50)
        peak_lat = np.random.normal(loc=0.05, scale=0.01, size=50)

        df_peak = pd.DataFrame({
            "timestamp": [f"2026-07-28T21:{i:02d}:00Z" for i in range(50)],
            "rps": peak_rps,
            "cpu_usage": peak_cpu,
            "latency_p90": peak_lat
        })

        res = self.detector.detect_sliding_window_drift(df_peak, psi_threshold=0.25)
        self.assertFalse(res["drift_detected"], "Peak hour valid traffic shift MUST NOT trigger false drift alarm")

    def test_ai_output_quality_drift(self):
        """
        [DIRECTIVE #27 - Test 3]
        Kiểm tra phát hiện suy giảm chất lượng AI Output (Confidence Score Drift).
        """
        # LLM confidence score trôi từ 0.95 xuống 0.40 (Model Quality Drift)
        degraded_conf = np.random.normal(loc=0.40, scale=0.05, size=50).tolist()
        ai_stream = {
            "llm_confidence_score": degraded_conf
        }

        res = self.detector.detect_ai_quality_drift(ai_stream)
        self.assertTrue(res["ai_quality_drift_detected"], "LLM confidence score drop MUST trigger AI Quality Drift Alert")
        self.assertEqual(len(res["drifted_ai_metrics"]), 1)
        self.assertEqual(res["drifted_ai_metrics"][0]["ai_surface_metric"], "llm_confidence_score")

    def test_text_embedding_cosine_drift(self):
        """
        [DIRECTIVE #27 - Test 4]
        Kiểm tra phát hiện trôi phân phối Vector Embedding đầu vào (Query/Review Shift).
        """
        # Vector embedding đầu vào hoàn toàn mới lệch hướng so với Centroid baseline
        shifted_embeddings = [np.random.normal(loc=-0.80, scale=0.05, size=128).tolist() for _ in range(20)]

        res = self.detector.detect_embedding_drift(shifted_embeddings, threshold_distance=0.35)
        self.assertTrue(res["embedding_drift_detected"], "Shifted text embeddings MUST trigger Embedding Drift Alert")
        self.assertGreaterEqual(res["mean_cosine_distance"], 0.35)

    def test_persistent_baseline_store(self):
        """
        [DIRECTIVE #27 - Test 5]
        Kiểm tra Baseline được lưu ra file JSON và phục hồi thành công qua container restarts.
        """
        self.assertTrue(os.path.exists(self.detector.store_file), "Baseline store file MUST exist on disk")
        
        # Load lại bằng instance mới
        new_detector = DataDriftDetector()
        self.assertIn("latency_p90", new_detector.baselines)
        self.assertIsNotNone(new_detector.embedding_centroid)


if __name__ == "__main__":
    unittest.main()
