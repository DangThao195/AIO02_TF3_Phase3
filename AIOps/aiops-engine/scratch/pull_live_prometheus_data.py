import os
import sys

# Add parent path to import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Override PROMETHEUS_URL globally to use the forwarded local port
import config
config.PROMETHEUS_URL = "http://localhost:9090"

import train_anomaly_model_eks
train_anomaly_model_eks.PROMETHEUS_URL = "http://localhost:9090"

import pandas as pd
from datetime import datetime
from train_anomaly_model_eks import fetch_metrics_from_prometheus, feature_engineering, SERVICES

# Create datametric dir if not exists
os.makedirs("datametric", exist_ok=True)

# Calculate duration days to cover back to July 14th
start_date = datetime(2026, 7, 14, 0, 0, 0)
now = datetime.now()
duration_days = (now - start_date).days + 2  # Add extra days for historical rolling window

print(f"Starting to query live data from EKS Prometheus (fetching {duration_days} days to filter from July 14)...")
for service in SERVICES:
    print(f"\n[Service: {service}] Querying telemetry metrics...")
    try:
        # Fetch actual Prometheus range data
        df_raw = fetch_metrics_from_prometheus(service, duration_days=duration_days)
        if df_raw.empty:
            print(f"  Warning: No live data returned from Prometheus for {service}.")
            continue
            
        print(f"  Live data retrieved: {len(df_raw)} records.")
        
        # Apply feature engineering to match the schema
        print("  Applying feature engineering...")
        df_processed = feature_engineering(df_raw)
        
        # Filter strictly from July 14th onwards
        df_processed = df_processed[df_processed["timestamp"] >= pd.Timestamp("2026-07-14 00:00:00")]
        
        # Add a default normal label (1)
        df_processed["label"] = 1
        
        # Save as CSV in the datametric folder, overwriting the previous files
        output_file = f"datametric/{service}_train.csv"
        df_processed.to_csv(output_file, index=False)
        print(f"  Successfully saved filtered EKS live data ({len(df_processed)} rows) to: {output_file}")
        
    except Exception as e:
        print(f"  Error pulling Prometheus data for {service}: {e}")

print("\nAll live Prometheus data pulls completed!")
