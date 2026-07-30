"""
Chạy lại 4 engine (Old IF riêng, EIF riêng, IF gộp, EIF gộp) trên tập SYNTHETIC DATA cũ
(generate_synthetic_data() — SCN-A..SCN-I, traffic quy mô lớn ~200x so với thật đã biết từ
trước). Mục đích: có thêm 1 nguồn dữ liệu độc lập để đối chiếu xu hướng tương đối giữa các
engine (không kỳ vọng số tuyệt đối cao do lệch phân phối train/test đã biết).
FULL 3-ngày mỗi kịch bản, không sampling — đúng tiêu chí đã thống nhất trong đợt làm việc này.
"""
import os
import sys
import json
import warnings

warnings.filterwarnings("ignore")

engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

import joblib
import pandas as pd
import numpy as np
from datetime import datetime

from train_anomaly_model_local import generate_synthetic_data, feature_engineering, SERVICES
from config import MODEL_FEATURE_COLUMNS
from eif_model import ExtendedIsolationForest  # cần để unpickle

MODELS_V1_DIR = os.path.join(engine_dir, "models")
MODELS_V2_DIR = os.path.join(engine_dir, "models_v2")
MODELS_MERGED_DIR = os.path.join(engine_dir, "models_merged")

SERVICE_ANOMALY_MAP = {
    "frontend": ["SCN-A", "SCN-G"],
    "checkout": ["SCN-F"],
    "payment": ["SCN-C"],
    "product-catalog": ["SCN-E"],
    "product-reviews": ["SCN-B"],
    "shipping": ["SCN-H"],
    "recommendation": ["SCN-D", "SCN-I"],
}
FP_RESISTANCE_SCENARIOS = {"SCN-A", "SCN-G"}


def compute_metrics(tp, fp, fn, n_total, is_fp_resistance):
    if is_fp_resistance:
        fpr = fp / n_total if n_total > 0 else 0.0
        return {"precision": 1.0 - fpr, "recall": 1.0, "f1_score": 1.0 - fpr, "fpr": fpr, "tp": tp, "fp": fp, "fn": fn}
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    fpr = fp / n_total if n_total > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1_score": f1, "fpr": fpr, "tp": tp, "fp": fp, "fn": fn}


def add_service_onehot(df_feat, service):
    df2 = df_feat.copy()
    for s in SERVICES:
        df2[f"svc_{s}"] = 1 if s == service else 0
    return df2


def main():
    old_models = {f.replace("_iforest.joblib", ""): joblib.load(os.path.join(MODELS_V1_DIR, f))
                  for f in os.listdir(MODELS_V1_DIR) if f.endswith("_iforest.joblib")}
    eif_models = {f.replace("_eif.joblib", ""): joblib.load(os.path.join(MODELS_V2_DIR, f))
                  for f in os.listdir(MODELS_V2_DIR) if f.endswith("_eif.joblib")}
    merged_feature_cols = joblib.load(os.path.join(MODELS_MERGED_DIR, "merged_feature_columns.joblib"))
    if_merged = joblib.load(os.path.join(MODELS_MERGED_DIR, "unified_iforest.joblib"))
    eif_merged = joblib.load(os.path.join(MODELS_MERGED_DIR, "unified_eif.joblib"))

    engines = ["old_perservice", "eif_perservice", "if_merged", "eif_merged"]
    agg = {e: {"tp": 0, "fp": 0, "fn": 0} for e in engines}
    agg_n = 0
    scenario_results = {}

    print("=" * 110)
    print("  4-WAY BENCHMARK TRÊN SYNTHETIC DATA CŨ (generate_synthetic_data, SCN-A..SCN-I, FULL 3-ngày/kịch bản)")
    print("=" * 110)

    for service, scenarios in SERVICE_ANOMALY_MAP.items():
        if service not in old_models:
            continue
        for scn in scenarios:
            df_val_raw = generate_synthetic_data(service, duration_days=3, is_anomaly_set=True, anomaly_type=scn)
            df_val = feature_engineering(df_val_raw)
            y_true = df_val["label"].values
            n_total = len(y_true)
            is_fp_scn = scn in FP_RESISTANCE_SCENARIOS

            X_perservice = df_val[MODEL_FEATURE_COLUMNS].values
            df_onehot = add_service_onehot(df_val, service)
            X_merged = df_onehot[merged_feature_cols].values

            preds = {
                "old_perservice": old_models[service].predict(X_perservice),
                "eif_perservice": eif_models[service].predict(X_perservice),
                "if_merged": if_merged.predict(X_merged),
                "eif_merged": eif_merged.predict(X_merged),
            }

            row = {}
            for e in engines:
                p = preds[e]
                tp = int(np.sum((y_true == -1) & (p == -1)))
                fp = int(np.sum((y_true == 1) & (p == -1)))
                fn = int(np.sum((y_true == -1) & (p == 1)))
                row[e] = compute_metrics(tp, fp, fn, n_total, is_fp_scn)
                agg[e]["tp"] += tp; agg[e]["fp"] += fp; agg[e]["fn"] += fn
            agg_n += n_total

            scenario_results[f"{service}::{scn}"] = {"n_total": n_total, "is_fp_resistance": is_fp_scn, **row}
            print(f"\n[{service}::{scn}]  n={n_total}  {'(FP-resistance scenario)' if is_fp_scn else ''}")
            for e in engines:
                m = row[e]
                print(f"    {e:<16} P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1_score']:.4f} FPR={m['fpr']:.4f} (TP={m['tp']} FP={m['fp']} FN={m['fn']})")

    print(f"\n>>> AGGREGATE (toàn bộ 9 kịch bản, n={agg_n}, tổng hợp TP/FP/FN thô — không tách FP-resistance) <<<")
    print(f"    {'Engine':<18} | {'Precision':<10} | {'Recall':<10} | {'F1':<10} | {'FPR':<10}")
    print("    " + "-" * 66)
    agg_metrics = {}
    for e in engines:
        tp, fp, fn = agg[e]["tp"], agg[e]["fp"], agg[e]["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        fpr = fp / agg_n if agg_n > 0 else 0.0
        agg_metrics[e] = {"precision": precision, "recall": recall, "f1_score": f1, "fpr": fpr, "tp": tp, "fp": fp, "fn": fn}
        print(f"    {e:<18} | {precision*100:>8.2f}% | {recall*100:>8.2f}% | {f1*100:>8.2f}% | {fpr*100:>8.2f}%")
    print("=" * 110 + "\n")

    output = {
        "timestamp": datetime.now().isoformat(),
        "methodology": "Đánh giá 4 engine trên tập synthetic cũ (generate_synthetic_data, quy mô traffic lệch ~200x so với thật, "
                       "đã biết từ trước) — dùng để đối chiếu xu hướng tương đối, không dùng số tuyệt đối làm benchmark chính thức.",
        "per_scenario": scenario_results,
        "aggregate": agg_metrics,
    }
    with open(os.path.join(engine_dir, "benchmark_synthetic_4way_results.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print("Saved to benchmark_synthetic_4way_results.json")


if __name__ == "__main__":
    main()
