import os, sys, json, numpy as np
os.environ["AIOPS_SIMULATION_MODE"] = "true"
sys.path.insert(0, "aiops-engine")

from anomaly_detector import AnomalyDetector
from train_anomaly_model_local import feature_engineering
import pandas as pd

detector = AnomalyDetector()
detector._load_models_from_s3()

with open("aiops-engine/datametric/labeled_scenarios.json", "r") as f:
    scenarios = json.load(f)["scenarios"]

feature_cols = [
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
    "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
]

print("=================== PURE ML (ISOLATION FOREST ONLY) EVALUATION ===================")
for sc in scenarios:
    name = sc["scenario_name"]
    service = sc["service"]
    raw_data = sc["data"]
    
    df_raw = pd.DataFrame(raw_data)
    df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
    df_features = feature_engineering(df_raw)
    
    model = detector.models.get(service)
    predictions = []
    
    for idx, row in df_features.iterrows():
        X_t = row[feature_cols].values.reshape(1, -1)
        if model:
            pred = int(model.predict(X_t)[0])
        else:
            pred = 1
        predictions.append(pred)
        
    df_features["pred"] = predictions
    
    warmup = 12
    eval_df = df_features.iloc[warmup:] if len(df_features) > warmup else df_features
    
    tp = int(((eval_df["pred"] == -1) & (eval_df["label"] == -1)).sum())
    fp = int(((eval_df["pred"] == -1) & (eval_df["label"] == 1)).sum())
    fn = int(((eval_df["pred"] == 1) & (eval_df["label"] == -1)).sum())
    tn = int(((eval_df["pred"] == 1) & (eval_df["label"] == 1)).sum())
    
    precision = float(tp) / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = float(tp) / (tp + fn) if (tp + fn) > 0 else 1.0
    
    print(f"\nScenario: [{name}] (Service: {service})")
    print(f"  - Pure ML Precision: {precision * 100:.1f}%")
    print(f"  - Pure ML Recall:    {recall * 100:.1f}%")
    print(f"  - True Positives (TP):  {tp}")
    print(f"  - False Positives (FP): {fp}")
    print(f"  - False Negatives (FN): {fn}")
    print(f"  - True Negatives (TN):  {tn}")
