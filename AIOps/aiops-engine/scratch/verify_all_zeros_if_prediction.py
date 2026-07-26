import joblib
import pandas as pd
import os

models_dir = "models"
feature_cols = [
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
    "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
]

print("=== TESTING ISOLATION FOREST PREDICTION ON ALL-ZERO VECTORS ([0.0]*18) ===")

for file in sorted(os.listdir(models_dir)):
    if file.endswith("_iforest.joblib"):
        svc = file.replace("_iforest.joblib", "")
        model_path = os.path.join(models_dir, file)
        model = joblib.load(model_path)
        
        # Test 1: All zeros vector
        zeros_df = pd.DataFrame([[0.0] * 18], columns=feature_cols)
        pred_zeros = int(model.predict(zeros_df)[0])
        score_zeros = float(model.score_samples(zeros_df)[0])
        
        print(f"Service: {svc:18s} | All-Zeros Vector Pred: {pred_zeros:2d} (Anomaly if -1) | Score: {score_zeros:.4f}")

