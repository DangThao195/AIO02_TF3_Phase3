import unittest
import os
import sys

# Prevent any boto3 / S3 network calls during testing
os.environ["AWS_ACCESS_KEY_ID"] = ""
os.environ["AWS_SECRET_ACCESS_KEY"] = ""

import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Ensure sys.path includes aiops-engine update root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anomaly_detector import AnomalyDetector
from enhanced_detector import EnhancedAnomalyDetector
from alert_correlator import AlertCorrelator

class TestEnhancedDetector(unittest.TestCase):
    """
    Unit test suite for EnhancedAnomalyDetector featuring:
    - 3-Sigma First-Drift Noise Filtering
    - Topology Downstream Symptom Penalty
    """

    @patch.object(AnomalyDetector, '_load_models_from_s3', return_value=None)
    @patch.object(AlertCorrelator, '_try_load_from_s3', return_value=None)
    def setUp(self, mock_s3_topology, mock_s3_models):
        self.old_detector = AnomalyDetector()
        self.enhanced_detector = EnhancedAnomalyDetector()
        self.enhanced_detector.load_local_models()
        
    def _create_sample_telemetry_df(self, spike_ticks=0, is_sustained=False):
        """Helper to construct 12-tick (1 hour) telemetry DataFrame."""
        start_time = datetime(2026, 7, 28, 12, 0, 0)
        timestamps = [start_time + timedelta(minutes=5 * i) for i in range(12)]
        
        # Base healthy baseline
        rps = [100.0 + np.random.normal(0, 2) for _ in range(12)]
        cpu = [0.25 + np.random.normal(0, 0.01) for _ in range(12)]
        mem = [0.40 + np.random.normal(0, 0.01) for _ in range(12)]
        latency = [0.05 + np.random.normal(0, 0.005) for _ in range(12)]
        error = [0.001 for _ in range(12)]
        client_error = [0.001 for _ in range(12)]
        kafka_lag = [0.0 for _ in range(12)]
        
        if spike_ticks == 1:
            # 1-tick transient spike at tick 11 (last tick)
            latency[11] = 2.5 # Huge spike 50x baseline
            error[11] = 0.30
        elif spike_ticks >= 2 and is_sustained:
            # Sustained anomaly at ticks 10 and 11
            latency[10] = 2.2
            error[10] = 0.25
            latency[11] = 2.5
            error[11] = 0.30
            
        df = pd.DataFrame({
            "timestamp": timestamps,
            "service": ["frontend"] * 12,
            "rps": rps,
            "cpu_usage": cpu,
            "memory_usage": mem,
            "latency_p90": latency,
            "error_rate": error,
            "client_error_rate": client_error,
            "kafka_lag": kafka_lag
        })
        
        # Derived features calculation
        df["error_ratio"] = df["error_rate"] / (df["rps"] + 1e-5)
        df["client_error_ratio"] = df["client_error_rate"] / (df["rps"] + 1e-5)
        df["rolling_median_1h"] = df["latency_p90"].rolling(window=12, min_periods=1).median()
        df["latency_deviation"] = df["latency_p90"] / (df["rolling_median_1h"] + 1e-5)
        df["rps_delta"] = df["rps"] - df["rps"].shift(1).fillna(0)
        df["cpu_per_rps"] = df["cpu_usage"] / (df["rps"] + 1e-5)
        df["memory_growth"] = df["memory_usage"] - df["memory_usage"].shift(6).fillna(0)
        df["kafka_lag_growth"] = df["kafka_lag"] - df["kafka_lag"].shift(1).fillna(0)
        df["hour_of_day"] = df["timestamp"].dt.hour
        df["day_of_week"] = df["timestamp"].dt.weekday
        df["is_business_hours"] = 1
        df["rolling_median_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).median()
        df["is_high_traffic_period"] = 0
        return df

    def test_case_1_transient_1tick_spike_suppression(self):
        """Case 1: 1-tick transient spike noise should be suppressed by 3-Sigma First-Drift."""
        df_transient = self._create_sample_telemetry_df(spike_ticks=1, is_sustained=False)
        drift_info = self.enhanced_detector.apply_three_sigma_first_drift("frontend", df_transient)
        
        self.assertTrue(drift_info["is_transient_spike"])
        self.assertFalse(drift_info["is_drift_valid"])
        self.assertEqual(drift_info["drift_consecutive_ticks"], 1)

    def test_case_2_sustained_anomaly_first_drift_extraction(self):
        """Case 2: Sustained anomaly (>= 2 ticks) must be detected with first_drift_timestamp."""
        df_sustained = self._create_sample_telemetry_df(spike_ticks=2, is_sustained=True)
        drift_info = self.enhanced_detector.apply_three_sigma_first_drift("frontend", df_sustained)
        
        self.assertFalse(drift_info["is_transient_spike"])
        self.assertTrue(drift_info["is_drift_valid"])
        self.assertGreaterEqual(drift_info["drift_consecutive_ticks"], 2)
        self.assertIsNotNone(drift_info["first_drift_timestamp"])

    def test_case_3_topology_downstream_symptom_penalty(self):
        """Case 3: Downstream service anomaly score should be penalized if upstream is broken."""
        active_anomalies = {
            "checkout": {"prediction": -1, "score": -0.45}
        }
        
        # Inject custom edge frontend -> checkout in nx_graph for test determinism
        self.enhanced_detector.correlator.nx_graph.add_edge("frontend", "checkout")
        
        raw_score = -0.30
        penalized_score = self.enhanced_detector.apply_topology_downstream_penalty("frontend", raw_score, active_anomalies)
        
        # Score should be demoted towards zero (penalized)
        self.assertGreater(penalized_score, raw_score) # -0.15 > -0.30
        self.assertEqual(penalized_score, -0.15)

    @patch.object(AnomalyDetector, 'check_infra_z_score', return_value=0.5)
    def test_case_4_zscore_fallback(self, mock_z):
        """Case 4: Graceful Z-Score fallback when service has no model loaded."""
        res = self.enhanced_detector.check_service_anomaly_enhanced("unknown_service_xyz")
        self.assertIn("prediction", res)
        self.assertTrue(res.get("fallback", True))
        self.assertEqual(res.get("prediction"), 1)

if __name__ == "__main__":
    unittest.main()
