import os
import sys
import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anomaly_detector import AnomalyDetector
from train_anomaly_model_local import generate_synthetic_data, feature_engineering

class TestMLAnomalyDetection(unittest.TestCase):
    def setUp(self):
        self.detector = AnomalyDetector()
        
    def test_feature_engineering_columns(self):
        """Kiểm định xem feature engineering có sinh đủ 13 đặc trưng máy học không."""
        # 1. Sinh dữ liệu thô mẫu
        df_raw = generate_synthetic_data("frontend", duration_days=1, is_anomaly_set=False)
        
        # 2. Chạy feature engineering
        df_features = feature_engineering(df_raw)
        
        # 3. Các đặc trưng máy học mong đợi
        expected_features = [
            "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
            "error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth",
            "hour_of_day", "day_of_week", "is_business_hours"
        ]
        
        for col in expected_features:
            self.assertIn(col, df_features.columns, f"Missing feature column: {col}")
            
        # Kiểm tra không có giá trị NaN trong tập đặc trưng
        self.assertFalse(df_features[expected_features].isnull().any().any(), "Features contain NaN values")
        logger_name = "test"
        
    def test_anomaly_detector_simulation_mode(self):
        """Xác minh detector phản hồi chính xác nhãn trong chế độ giả lập Sandbox."""
        os.environ["AIOPS_SIMULATION_MODE"] = "true"
        
        # Mock simulation state to stable
        from config import SIMULATION_STATE
        SIMULATION_STATE["scenario"] = "stable"
        SIMULATION_STATE["remediated"] = False
        
        res = self.detector.check_service_anomaly("frontend")
        self.assertEqual(res["prediction"], 1, "Should predict normal in stable simulation mode")
        
        # Mock simulation state to anomaly scenario
        SIMULATION_STATE["scenario"] = "inc1"
        res_anom = self.detector.check_service_anomaly("frontend")
        self.assertEqual(res_anom["prediction"], -1, "Should predict anomalous in active scenario simulation mode")
        
        # Clean up
        os.environ["AIOPS_SIMULATION_MODE"] = "false"

    def test_model_inference_fallback_without_model(self):
        """Kiểm thử cơ chế fallback tự động về Z-score nếu không tìm thấy file model."""
        # Tạm thời xóa model 'recommendation' ra khỏi models nếu có để test fallback
        original_model = self.detector.models.pop("recommendation", None)
        
        # Chạy test trong chế độ offline (Prometheus down -> Z-score trả về 999.0 -> Anomaly)
        res = self.detector.check_service_anomaly("recommendation")
        self.assertTrue(res["fallback"], "Should fallback to Z-Score when model is missing")
        
        # Khôi phục lại model
        if original_model:
            self.detector.models["recommendation"] = original_model

    def test_check_infra_anomaly(self):
        """Xác minh hàm check_infra_anomaly hoạt động đúng chữ ký đầu vào."""
        # Mock vector 18 đặc trưng máy học
        features = [10.0, 0.2, 0.4, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.02, 0.0, 0.0, 12, 0, 1, 0]
        res = self.detector.check_infra_anomaly("frontend", features)
        self.assertIsInstance(res, bool, "check_infra_anomaly must return a boolean value")

if __name__ == "__main__":
    unittest.main()
