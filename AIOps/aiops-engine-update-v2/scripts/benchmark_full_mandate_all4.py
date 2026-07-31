"""
Đánh giá ĐẦY ĐỦ cả 4 kiến trúc trên TOÀN BỘ 9 kịch bản mandate SCN-A..SCN-I:
  - IF tách-service (models/)       - IF gộp (models_merged/unified_iforest.joblib)
  - EIF tách-service (models_v2/)   - EIF gộp (models_merged/unified_eif.joblib)
FULL dataset mỗi file, không sampling, khớp phân phối train (splice trên baseline thật).
"""
import os, sys, json, warnings
warnings.filterwarnings("ignore")

engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

import joblib, pandas as pd, numpy as np
from datetime import datetime
from train_anomaly_model_local import feature_engineering, SERVICES
from config import MODEL_FEATURE_COLUMNS
from eif_model import ExtendedIsolationForest

MODELS_V1_DIR = os.path.join(engine_dir, "models")
MODELS_V2_DIR = os.path.join(engine_dir, "models_v2")
MODELS_MERGED_DIR = os.path.join(engine_dir, "models_merged")
DATA_DIR = os.path.join(engine_dir, "datametric", "realistic_test_cases")

MANDATE_TESTCASES = {
    "SCN-A_frontend_node_drain": ("SCN-A_frontend_node_drain_fp_resistance.csv", "frontend", False),
    "SCN-B_product-reviews_ai_spam_dos": ("SCN-B_product-reviews_ai_spam_dos.csv", "product-reviews", True),
    "SCN-C_payment_slow_ram_leak": ("SCN-C_payment_slow_ram_leak.csv", "payment", True),
    "SCN-D_recommendation_http_4xx_scan": ("SCN-D_recommendation_http_4xx_scan.csv", "recommendation", True),
    "SCN-E_product-catalog_packet_loss": ("SCN-E_product-catalog_network_packet_loss.csv", "product-catalog", True),
    "SCN-F_product-catalog_ROOT": ("SCN-F_product-catalog_ROOT_CAUSE_cascading_failure.csv", "product-catalog", True),
    "SCN-F_checkout_SYMPTOM": ("SCN-F_checkout_SYMPTOM_cascading_failure.csv", "checkout", True),
    "SCN-G_frontend_thundering_herd": ("SCN-G_frontend_thundering_herd.csv", "frontend", False),
    "SCN-H_shipping_gradual_erosion": ("SCN-H_shipping_gradual_slo_erosion.csv", "shipping", True),
    "SCN-I_recommendation_cpu_steal": ("SCN-I_recommendation_cpu_steal.csv", "recommendation", True),
}


def compute_metrics(tp, fp, fn, n_total):
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
    if_models = {f.replace("_iforest.joblib", ""): joblib.load(os.path.join(MODELS_V1_DIR, f))
                 for f in os.listdir(MODELS_V1_DIR) if f.endswith("_iforest.joblib")}
    eif_models = {f.replace("_eif.joblib", ""): joblib.load(os.path.join(MODELS_V2_DIR, f))
                  for f in os.listdir(MODELS_V2_DIR) if f.endswith("_eif.joblib")}
    merged_cols = joblib.load(os.path.join(MODELS_MERGED_DIR, "merged_feature_columns.joblib"))
    if_merged = joblib.load(os.path.join(MODELS_MERGED_DIR, "unified_iforest.joblib"))
    eif_merged = joblib.load(os.path.join(MODELS_MERGED_DIR, "unified_eif.joblib"))

    engines = ["if_perservice", "if_merged", "eif_perservice", "eif_merged"]
    print("=" * 115)
    print("  4 KIẾN TRÚC — ĐỦ 9 KỊCH BẢN MANDATE SCN-A..SCN-I (FULL dataset, khớp phân phối train)")
    print("=" * 115)

    agg = {e: {"tp": 0, "fp": 0, "fn": 0} for e in engines}
    agg_n = 0
    case_results = {}

    for label, (fname, service, is_incident) in MANDATE_TESTCASES.items():
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath) or service not in if_models:
            print(f"[SKIP] {label}"); continue

        df_raw = pd.read_csv(fpath)
        df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
        df_feat = feature_engineering(df_raw)
        y_true = df_feat["label"].values
        n_total = len(y_true)

        X_ps = df_feat[MODEL_FEATURE_COLUMNS].values
        X_mg = add_service_onehot(df_feat, service)[merged_cols].values

        preds = {
            "if_perservice": if_models[service].predict(X_ps),
            "if_merged": if_merged.predict(X_mg),
            "eif_perservice": eif_models[service].predict(X_ps),
            "eif_merged": eif_merged.predict(X_mg),
        }

        row = {}
        for e in engines:
            p = preds[e]
            tp = int(np.sum((y_true == -1) & (p == -1)))
            fp = int(np.sum((y_true == 1) & (p == -1)))
            fn = int(np.sum((y_true == -1) & (p == 1)))
            row[e] = compute_metrics(tp, fp, fn, n_total)
            if is_incident:
                agg[e]["tp"] += tp; agg[e]["fp"] += fp; agg[e]["fn"] += fn
        if is_incident:
            agg_n += n_total

        case_results[label] = {"file": fname, "service": service, "n_total": n_total,
                                "n_incident_ticks": int(np.sum(y_true == -1)),
                                "is_incident_scenario": is_incident, **row}

        print(f"\n[{label}]  service={service}  n={n_total}  incident_ticks={int(np.sum(y_true==-1))}"
              f"{'  (FP-RESISTANCE)' if not is_incident else ''}")
        for e in engines:
            m = row[e]
            if is_incident:
                print(f"    {e:<16} P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1_score']:.4f} FPR={m['fpr']:.4f} (TP={m['tp']} FP={m['fp']} FN={m['fn']})")
            else:
                print(f"    {e:<16} FP={m['fp']}/{n_total} ({m['fpr']*100:.2f}%)")

    print(f"\n>>> AGGREGATE (7 kịch bản incident thật, n={agg_n}) <<<")
    print(f"    {'Engine':<16} | {'Precision':<10} | {'Recall':<10} | {'F1':<10} | {'FPR':<10}")
    print("    " + "-" * 64)
    agg_metrics = {}
    for e in engines:
        m = compute_metrics(agg[e]["tp"], agg[e]["fp"], agg[e]["fn"], agg_n)
        agg_metrics[e] = m
        print(f"    {e:<16} | {m['precision']*100:>8.2f}% | {m['recall']*100:>8.2f}% | {m['f1_score']*100:>8.2f}% | {m['fpr']*100:>8.2f}%")
    print("=" * 115 + "\n")

    output = {"timestamp": datetime.now().isoformat(), "per_case": case_results, "aggregate": agg_metrics}
    with open(os.path.join(engine_dir, "benchmark_full_mandate_all4_results.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print("Saved to benchmark_full_mandate_all4_results.json")


if __name__ == "__main__":
    main()
