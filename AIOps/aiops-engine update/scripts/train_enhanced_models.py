import os
import sys
import logging
import joblib
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest

# Ensure path resolution
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

from train_anomaly_model_local import SERVICES, feature_engineering

FEATURE_COLS = [
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
    "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.TrainEnhanced")

def main():
    logger.info("======================================================================")
    logger.info(">>> START RETRAINING ISOLATION FOREST MODELS ON CLEAN BASELINE DATA")
    logger.info("======================================================================")
    
    data_dir = os.path.join(engine_dir, "datametric")
    models_dir = os.path.join(engine_dir, "models")
    os.makedirs(models_dir, exist_ok=True)
    
    trained_count = 0
    
    for service in SERVICES:
        # Ưu tiên tập clean_baseline nếu có, nếu không thì dùng tập train thô
        clean_file = os.path.join(data_dir, f"{service}_clean_baseline.csv")
        fallback_file = os.path.join(data_dir, f"{service}_train.csv")
        
        target_file = clean_file if os.path.exists(clean_file) else fallback_file
        if not os.path.exists(target_file):
            logger.error(f"No baseline dataset found for {service}. Skipping.")
            continue
            
        logger.info(f"Training model for '{service}' using dataset: {target_file}...")
        df_raw = pd.read_csv(target_file)
        
        # Ensure timestamp datetime type
        if "timestamp" in df_raw.columns:
            df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
            
        # Feature Engineering
        df_features = feature_engineering(df_raw)
        X_train = df_features[FEATURE_COLS]
        
        # Train IsolationForest model
        model = IsolationForest(
            n_estimators=200,
            contamination=0.03,
            max_features=0.8,
            random_state=42,
            n_jobs=-1
        )
        model.fit(X_train)
        
        # Save model joblib
        model_path = os.path.join(models_dir, f"{service}_iforest.joblib")
        joblib.dump(model, model_path)
        trained_count += 1
        logger.info(f"✅ Successfully trained and saved model to: {model_path} (Training samples: {len(X_train)})")
        
    logger.info("======================================================================")
    logger.info(f"RETRAINING COMPLETE: Trained {trained_count}/{len(SERVICES)} service models.")
    logger.info("======================================================================")

if __name__ == "__main__":
    main()
