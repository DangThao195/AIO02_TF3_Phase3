import os
import sys
import json
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from anomaly_detector import AnomalyDetector

detector = AnomalyDetector()

scenarios = [
  {
    "scenario_name": "checkout_incident",
    "service": "checkout",
    "data": [
      {"timestamp": "2026-07-17T12:00:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:05:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:10:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:15:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:20:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:25:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:30:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:35:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:40:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:45:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:50:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:55:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T13:00:00Z", "rps": 0.25, "cpu_usage": 0.018, "memory_usage": 0.188, "latency_p90": 0.95, "error_rate": 0.08, "client_error_rate": 0.0, "kafka_lag": 45.0, "label": -1},
      {"timestamp": "2026-07-17T13:05:00Z", "rps": 0.25, "cpu_usage": 0.022, "memory_usage": 0.188, "latency_p90": 1.20, "error_rate": 0.12, "client_error_rate": 0.0, "kafka_lag": 85.0, "label": -1},
      {"timestamp": "2026-07-17T13:10:00Z", "rps": 0.25, "cpu_usage": 0.020, "memory_usage": 0.188, "latency_p90": 1.10, "error_rate": 0.10, "client_error_rate": 0.0, "kafka_lag": 120.0, "label": -1}
    ]
  },
  {
    "scenario_name": "masking_incident",
    "service": "checkout",
    "data": [
      {"timestamp": "2026-07-17T12:00:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:05:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:10:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:15:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:20:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:25:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:30:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:35:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:40:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:45:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:50:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:55:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T13:00:00Z", "rps": 1.80, "cpu_usage": 0.028, "memory_usage": 0.210, "latency_p90": 0.12, "error_rate": 0.072, "client_error_rate": 0.0, "kafka_lag": 18.0, "label": -1},
      {"timestamp": "2026-07-17T13:05:00Z", "rps": 1.75, "cpu_usage": 0.025, "memory_usage": 0.212, "latency_p90": 0.10, "error_rate": 0.070, "client_error_rate": 0.0, "kafka_lag": 22.0, "label": -1},
      {"timestamp": "2026-07-17T13:10:00Z", "rps": 1.82, "cpu_usage": 0.027, "memory_usage": 0.215, "latency_p90": 0.11, "error_rate": 0.068, "client_error_rate": 0.0, "kafka_lag": 28.0, "label": -1}
    ]
  },
  {
    "scenario_name": "high_load_healthy",
    "service": "checkout",
    "data": [
      {"timestamp": "2026-07-17T12:00:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:05:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:10:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:15:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:20:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:25:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:30:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:35:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:40:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:45:00Z", "rps": 0.24, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:50:00Z", "rps": 0.26, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T12:55:00Z", "rps": 0.25, "cpu_usage": 0.003, "memory_usage": 0.188, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T13:00:00Z", "rps": 1.50, "cpu_usage": 0.022, "memory_usage": 0.192, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T13:05:00Z", "rps": 1.45, "cpu_usage": 0.020, "memory_usage": 0.190, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
      {"timestamp": "2026-07-17T13:10:00Z", "rps": 1.52, "cpu_usage": 0.023, "memory_usage": 0.194, "latency_p90": 0.0, "error_rate": 0.0, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1}
    ]
  }
]

model = detector.models.get("checkout")
if not model:
    print("Error: checkout model not loaded!")
    sys.exit(1)

for s in scenarios:
    name = s["scenario_name"]
    df = pd.DataFrame(s["data"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Feature engineering
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
    df["is_business_hours"] = ((df["hour_of_day"] >= 8) & (df["hour_of_day"] <= 18) & (df["day_of_week"] < 5)).astype(int)
    
    df["rolling_median_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).median()
    df["is_high_traffic_period"] = ((df["rps"] > 100) & (df["rps"] > 1.5 * df["rolling_median_rps_1h"])).astype(int)
    df = df.fillna(0)
    
    feature_cols = [
        "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
        "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
        "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
    ]
    
    # Run raw Isolation Forest without SRE Guardrail
    raw_preds = []
    scores = []
    for idx, row in df.iterrows():
        X_t = row[feature_cols].values.reshape(1, -1)
        pred = int(model.predict(X_t)[0])
        score = float(model.decision_function(X_t)[0])
        raw_preds.append(pred)
        scores.append(score)
        
    print(f"\n--- Scenario: {name} ---")
    for i in range(12, 15):
        row = df.iloc[i]
        print(f"Row {i} (RPS={row['rps']}, Latency={row['latency_p90']}, Error={row['error_rate']}) -> Raw IF Predict: {raw_preds[i]}, Score: {scores[i]:.4f}")
