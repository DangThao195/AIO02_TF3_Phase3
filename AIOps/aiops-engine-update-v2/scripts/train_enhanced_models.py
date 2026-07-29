"""
Retrain script: huấn luyện lại Isolation Forest cho tất cả 7 services trên dữ liệu
sạch thực tế `*_clean_baseline.csv` — sử dụng TOÀN BỘ dataset (không sampling).

QUAN TRỌNG - Công bằng A/B:
  Đây là mô hình DUY NHẤT được cả Old Engine (AnomalyDetector) và Enhanced Engine
  (EnhancedAnomalyDetector) cùng sử dụng. Enhanced Engine không có model riêng —
  nó tái sử dụng chính xác model này rồi áp thêm 2 lớp cổng hậu kiểm (3-Sigma
  First-Drift + Topology Downstream Penalty). Vì vậy chỉ cần train MỘT LẦN ở đây;
  mọi khác biệt đo được giữa 2 Engine trong benchmark hoàn toàn đến từ 2 lớp cổng đó,
  không phải từ sai khác dữ liệu train hay hyperparameter.
"""
import os
import sys
import logging
import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

# Ensure path resolution
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

from train_anomaly_model_local import SERVICES, feature_engineering
from config import MODEL_FEATURE_COLUMNS, IFOREST_HYPERPARAMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.TrainEnhanced")


def main():
    logger.info("======================================================================")
    logger.info(">>> START RETRAINING ISOLATION FOREST MODELS ON FULL CLEAN BASELINE DATA")
    logger.info("    (KHÔNG sampling — sử dụng 100%% số dòng của từng file *_clean_baseline.csv)")
    logger.info("======================================================================")

    data_dir = os.path.join(engine_dir, "datametric")
    models_dir = os.path.join(engine_dir, "models")
    os.makedirs(models_dir, exist_ok=True)

    trained_count = 0
    manifest = {}

    for service in SERVICES:
        # Ưu tiên tập clean_baseline nếu có, nếu không thì dùng tập train thô
        clean_file = os.path.join(data_dir, f"{service}_clean_baseline.csv")
        fallback_file = os.path.join(data_dir, f"{service}_train.csv")

        target_file = clean_file if os.path.exists(clean_file) else fallback_file
        if not os.path.exists(target_file):
            logger.error(f"No baseline dataset found for {service}. Skipping.")
            continue

        used_fallback = target_file == fallback_file
        logger.info(f"Training model for '{service}' using dataset: {target_file}"
                    f"{' (fallback: clean_baseline not found)' if used_fallback else ''}...")

        df_raw = pd.read_csv(target_file)  # FULL FILE — không .sample(), không .head(), không linspace

        if "timestamp" in df_raw.columns:
            df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])

        # Feature Engineering (dùng đúng hàm feature_engineering() gốc — không có biến thể riêng
        # cho Enhanced Engine, đảm bảo input space giống hệt nhau).
        df_features = feature_engineering(df_raw)
        X_train = df_features[MODEL_FEATURE_COLUMNS]

        # Train IsolationForest model — hyperparams lấy từ config.IFOREST_HYPERPARAMS,
        # nguồn duy nhất dùng chung, tránh lệch cấu hình so với Old Engine.
        model = IsolationForest(**IFOREST_HYPERPARAMS)
        model.fit(X_train)

        model_path = os.path.join(models_dir, f"{service}_iforest.joblib")
        joblib.dump(model, model_path)
        trained_count += 1
        manifest[service] = {
            "source_file": os.path.basename(target_file),
            "training_samples": int(len(X_train)),
            "sampled": False,
        }
        logger.info(f"✅ Successfully trained and saved model to: {model_path} "
                    f"(Training samples: {len(X_train)}, FULL DATASET, no sampling)")

    logger.info("======================================================================")
    logger.info(f"RETRAINING COMPLETE: Trained {trained_count}/{len(SERVICES)} service models.")
    for svc, info in manifest.items():
        logger.info(f"  - {svc}: {info['training_samples']} samples from {info['source_file']}")
    logger.info("======================================================================")


if __name__ == "__main__":
    main()
