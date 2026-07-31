"""
Model Update v2: huấn luyện Extended Isolation Forest (EIF) thay cho Isolation Forest
trục-song song (sklearn), trên CÙNG 100% dữ liệu *_clean_baseline.csv, CÙNG feature set
(config.MODEL_FEATURE_COLUMNS), CÙNG contamination — chỉ khác THUẬT TOÁN cô lập
(random hyperplane đa chiều thay vì axis-aligned từng chiều).

Lưu model vào models_v2/ (KHÔNG đụng tới models/ của IF gốc) để giữ Old Engine (v1) nguyên vẹn
làm baseline so sánh.
"""
import os
import sys
import joblib
import pandas as pd

engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

from train_anomaly_model_local import SERVICES, feature_engineering
from config import MODEL_FEATURE_COLUMNS, IFOREST_HYPERPARAMS
from eif_model import ExtendedIsolationForest

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.TrainEIF_v2")


def main():
    logger.info("=" * 90)
    logger.info(">>> MODEL UPDATE v2: RETRAIN EXTENDED ISOLATION FOREST (EIF) — FULL DATASET, NO SAMPLING")
    logger.info("=" * 90)

    data_dir = os.path.join(engine_dir, "datametric")
    models_v2_dir = os.path.join(engine_dir, "models_v2")
    os.makedirs(models_v2_dir, exist_ok=True)

    for service in SERVICES:
        clean_file = os.path.join(data_dir, f"{service}_clean_baseline.csv")
        if not os.path.exists(clean_file):
            logger.warning(f"Missing baseline for {service}, skip.")
            continue

        df_raw = pd.read_csv(clean_file)  # FULL FILE, không sampling
        df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
        df_feat = feature_engineering(df_raw)
        X_train = df_feat[MODEL_FEATURE_COLUMNS].values

        model = ExtendedIsolationForest(
            n_estimators=IFOREST_HYPERPARAMS["n_estimators"],
            contamination=IFOREST_HYPERPARAMS["contamination"],
            extension_level=None,  # full extension: siêu phẳng ngẫu nhiên toàn chiều
            random_state=IFOREST_HYPERPARAMS["random_state"],
        )
        model.fit(X_train)

        out_path = os.path.join(models_v2_dir, f"{service}_eif.joblib")
        joblib.dump(model, out_path)
        logger.info(f"✅ Trained EIF for '{service}' -> {out_path} (n={len(X_train)} samples, FULL dataset)")

    logger.info("=" * 90)
    logger.info("DONE. EIF models (v2) saved to models_v2/")
    logger.info("=" * 90)


if __name__ == "__main__":
    main()
