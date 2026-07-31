"""
Model Update v3: GỘP 7 service thành 1 tập train duy nhất, thêm one-hot "service" để model
phân biệt, rồi train 1 IsolationForest (Old-style) + 1 EIF (v2-style) trên tập gộp — để so
sánh trực tiếp: liệu 1 model gộp có tốt hơn/kém hơn 7 model riêng không, và EIF có tốt hơn
IF khi cùng dùng kiến trúc gộp không.

QUAN TRỌNG — feature engineering vẫn tính RIÊNG theo từng service TRƯỚC KHI gộp:
  feature_engineering() dùng rolling window (rolling_median_1h, rps_delta, memory_growth,
  kafka_lag_growth...) — các phép tính này BẮT BUỘC phải chạy trên chuỗi thời gian của
  ĐÚNG 1 service. Nếu gộp dữ liệu thô rồi mới tính rolling, các phép rolling sẽ tính lẫn
  lộn qua ranh giới giữa các service (vô nghĩa). Vì vậy quy trình đúng là:
    for service in SERVICES:
        feat = feature_engineering(load(service))   # <- tính riêng, đúng ngữ cảnh time-series
        feat[f"svc_{service}"] = 1                  # <- gắn one-hot SAU KHI đã tính xong feature
    merged = concat(tất cả feat)                     # <- chỉ gộp SAU KHI feature đã tính xong
"""
import os
import sys
import joblib
import pandas as pd
import numpy as np

engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

from train_anomaly_model_local import SERVICES, feature_engineering
from config import MODEL_FEATURE_COLUMNS, IFOREST_HYPERPARAMS
from sklearn.ensemble import IsolationForest
from eif_model import ExtendedIsolationForest

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.TrainMerged")

DATA_DIR = os.path.join(engine_dir, "datametric")
MODELS_MERGED_DIR = os.path.join(engine_dir, "models_merged")
os.makedirs(MODELS_MERGED_DIR, exist_ok=True)

# Feature set MỞ RỘNG cho model gộp: 18 feature gốc (dùng chung config.MODEL_FEATURE_COLUMNS)
# + 7 cột one-hot service (KHÔNG tồn tại trong kiến trúc 7-model-riêng vì mỗi model gốc vốn
# đã bị giới hạn phạm vi 1 service ngay từ cách train, nên chưa từng cần định danh).
SERVICE_ONEHOT_COLUMNS = [f"svc_{s}" for s in SERVICES]
MERGED_FEATURE_COLUMNS = MODEL_FEATURE_COLUMNS + SERVICE_ONEHOT_COLUMNS


def build_merged_dataframe() -> pd.DataFrame:
    frames = []
    for service in SERVICES:
        path = os.path.join(DATA_DIR, f"{service}_clean_baseline.csv")
        if not os.path.exists(path):
            logger.warning(f"Missing baseline for {service}, skip.")
            continue
        df_raw = pd.read_csv(path)  # FULL FILE, không sampling
        df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])

        # Tính feature engineering RIÊNG cho service này (đúng ngữ cảnh rolling window)
        df_feat = feature_engineering(df_raw)

        # Gắn one-hot SAU KHI đã tính xong feature — không ảnh hưởng tới rolling stats
        for s in SERVICES:
            df_feat[f"svc_{s}"] = 1 if s == service else 0
        df_feat["_source_service"] = service  # giữ lại để debug/log, không đưa vào model

        frames.append(df_feat)
        logger.info(f"  + {service}: {len(df_feat)} dòng (feature engineering tính riêng)")

    merged = pd.concat(frames, ignore_index=True)
    return merged


def main():
    logger.info("=" * 90)
    logger.info(">>> MODEL UPDATE v3: GỘP 7 SERVICE THÀNH 1 TẬP TRAIN (feature engineering riêng từng service)")
    logger.info("=" * 90)

    merged_df = build_merged_dataframe()
    logger.info(f"Tổng dữ liệu gộp: {len(merged_df)} dòng, {len(MERGED_FEATURE_COLUMNS)} features "
                f"({len(MODEL_FEATURE_COLUMNS)} gốc + {len(SERVICE_ONEHOT_COLUMNS)} one-hot service)")

    X_merged = merged_df[MERGED_FEATURE_COLUMNS].values

    # --- 1 IsolationForest GỘP (train y hệt phong cách Old Engine, cùng hyperparams) ---
    logger.info("Training 1 IsolationForest GỘP (Old-style hyperparams)...")
    if_model = IsolationForest(**IFOREST_HYPERPARAMS)
    if_model.fit(X_merged)
    joblib.dump(if_model, os.path.join(MODELS_MERGED_DIR, "unified_iforest.joblib"))
    logger.info(f"  -> Saved models_merged/unified_iforest.joblib")

    # --- 1 EIF GỘP (cùng hyperparams tương ứng) ---
    logger.info("Training 1 Extended Isolation Forest (EIF) GỘP...")
    eif_model = ExtendedIsolationForest(
        n_estimators=IFOREST_HYPERPARAMS["n_estimators"],
        contamination=IFOREST_HYPERPARAMS["contamination"],
        extension_level=None,
        random_state=IFOREST_HYPERPARAMS["random_state"],
    )
    eif_model.fit(X_merged)
    joblib.dump(eif_model, os.path.join(MODELS_MERGED_DIR, "unified_eif.joblib"))
    logger.info(f"  -> Saved models_merged/unified_eif.joblib")

    # Lưu lại danh sách feature columns dùng cho model gộp (để script eval dùng đúng thứ tự)
    joblib.dump(MERGED_FEATURE_COLUMNS, os.path.join(MODELS_MERGED_DIR, "merged_feature_columns.joblib"))

    logger.info("=" * 90)
    logger.info("DONE.")
    logger.info("=" * 90)


if __name__ == "__main__":
    main()
