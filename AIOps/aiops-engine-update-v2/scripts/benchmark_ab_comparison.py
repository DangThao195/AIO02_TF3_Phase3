"""
Empirical A/B Benchmark: Old Detector (AnomalyDetector / Isolation Forest thuần)
vs Enhanced Detector (EnhancedAnomalyDetector / 3-Sigma First-Drift + Topology Penalty).

NGUYÊN TẮC CÔNG BẰNG (bắt buộc, không thương lượng):
  1. CÙNG MỘT MODEL: cả 2 Engine dùng chung model Isolation Forest vừa retrain
     bằng scripts/train_enhanced_models.py trên FULL *_clean_baseline.csv.
     Enhanced Engine không có model riêng — nó chỉ áp thêm 2 lớp cổng hậu kiểm
     lên đúng phán quyết của model đó.
  2. FULL DATASET — KHÔNG SAMPLING: mọi phép đánh giá chạy trên 100% số dòng của
     từng file dữ liệu (clean_baseline, anomalies, synthetic scenario). Không
     dùng np.linspace(...) để chọn vài điểm đại diện như bản cũ.
  3. CÙNG TIÊU CHÍ ĐÁNH GIÁ VỚI OLD MODEL: công thức Precision/Recall/F1/FPR và
     cách xử lý đặc biệt cho kịch bản chỉ có nhãn Normal (SCN-A/SCN-G, tức các
     kịch bản kiểm tra khả năng kháng báo động giả — FP-resistance scenarios)
     được lấy y hệt từ train_anomaly_model_local.py::train_and_evaluate(), để
     kết quả so sánh có cùng mức độ/ý nghĩa thống kê với báo cáo gốc của Old Engine.
  4. Enhanced Engine chỉ có thể SUY GIẢM báo động (suppress/demote) của Old Engine,
     không bao giờ tự tạo báo động mới -> mọi TP mà Old Engine bắt được, Enhanced
     Engine hoặc giữ nguyên hoặc (nếu bị lọc nhầm) chuyển thành FN — đo được rõ ràng
     trong bảng kết quả (tick bị suppress được gắn nhãn 'suppressed_by').
"""
import os
import sys
import json
import logging
import warnings

warnings.filterwarnings("ignore")

engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(engine_dir)

from unittest.mock import patch
from anomaly_detector import AnomalyDetector
from alert_correlator import AlertCorrelator

# Không gọi mạng ra S3 khi benchmark cục bộ
patch.object(AnomalyDetector, "_load_models_from_s3", return_value=None).start()

import pandas as pd
import numpy as np
from datetime import datetime

from enhanced_detector import EnhancedAnomalyDetector
from train_anomaly_model_local import SERVICES, generate_synthetic_data, feature_engineering
from config import MODEL_FEATURE_COLUMNS, BENCHMARK_RANDOM_SEED

FEATURE_COLS = MODEL_FEATURE_COLUMNS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.ABBenchmark")

# Kịch bản test sự cố thật (khớp với if_evaluation_report.md / train_and_evaluate())
SERVICE_ANOMALY_MAP = {
    "frontend": ["SCN-A", "SCN-G"],          # FP-resistance scenarios (Node Drain / Thundering Herd)
    "checkout": ["SCN-F"],                    # Cascading Failure
    "payment": ["SCN-C"],                     # Slow RAM Leak
    "product-catalog": ["SCN-E"],             # Network Packet Loss
    "product-reviews": ["SCN-B"],             # AI Spam DoS
    "shipping": ["SCN-H"],                    # Gradual SLO Erosion
    "recommendation": ["SCN-D", "SCN-I"],     # HTTP 4xx Scan / CPU Steal
}
FP_RESISTANCE_SCENARIOS = {"SCN-A", "SCN-G"}


def compute_metrics(tp: int, fp: int, fn: int, is_fp_resistance_scenario: bool, n_total: int) -> dict:
    """
    Công thức Precision/Recall/F1/FPR — SAO CHÉP NGUYÊN VẸN từ
    train_anomaly_model_local.py::train_and_evaluate() để đảm bảo Old Engine và
    Enhanced Engine được chấm điểm theo đúng cùng một tiêu chí đã công bố trong
    if_evaluation_report.md.
    """
    if is_fp_resistance_scenario:
        # Không có nhãn Anomaly thật -> FPR là chỉ số duy nhất có ý nghĩa,
        # Precision/F1 được suy ra theo quy ước gốc của Old Engine.
        fpr = fp / n_total if n_total > 0 else 0.0
        precision = 1.0 - fpr
        recall = 1.0
        f1 = 1.0 - fpr
    else:
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        fpr = fp / n_total if n_total > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1_score": f1, "fpr": fpr, "tp": tp, "fp": fp, "fn": fn}


def evaluate_scenario_full(old_detector, enhanced_detector, service, model, anomaly_type):
    """
    Đánh giá FULL dataset (không sampling) cho một kịch bản sự cố cụ thể của một service.
    Sinh tập test 3 ngày y hệt kích thước tập validation gốc của train_and_evaluate(),
    rồi chấm điểm TỪNG TICK MỘT bằng EnhancedAnomalyDetector.evaluate_series().
    """
    df_val_raw = generate_synthetic_data(service, duration_days=3, is_anomaly_set=True, anomaly_type=anomaly_type)
    df_val = feature_engineering(df_val_raw)
    y_true = df_val["label"].values  # 1: Normal, -1: Anomaly

    result = enhanced_detector.evaluate_series(service, df_val, model, active_anomalies_by_tick=None)
    old_pred = result["old_prediction"]
    enh_pred = result["enhanced_prediction"]

    is_fp_scn = anomaly_type in FP_RESISTANCE_SCENARIOS

    old_tp = int(np.sum((y_true == -1) & (old_pred == -1)))
    old_fp = int(np.sum((y_true == 1) & (old_pred == -1)))
    old_fn = int(np.sum((y_true == -1) & (old_pred == 1)))

    enh_tp = int(np.sum((y_true == -1) & (enh_pred == -1)))
    enh_fp = int(np.sum((y_true == 1) & (enh_pred == -1)))
    enh_fn = int(np.sum((y_true == -1) & (enh_pred == 1)))

    n_total = len(y_true)
    old_metrics = compute_metrics(old_tp, old_fp, old_fn, is_fp_scn, n_total)
    enh_metrics = compute_metrics(enh_tp, enh_fp, enh_fn, is_fp_scn, n_total)

    # Đếm số TP thật của Old Engine bị Enhanced Engine "nuốt" oan (chuyển từ đúng -> sai)
    tp_lost_to_suppression = int(np.sum((y_true == -1) & (old_pred == -1) & (enh_pred == 1)))

    return {
        "n_total": n_total,
        "old": old_metrics,
        "enhanced": enh_metrics,
        "tp_lost_to_suppression": tp_lost_to_suppression,
    }


def evaluate_clean_baseline_full(enhanced_detector, service, model, df_baseline_features):
    """
    Đo Specificity/FPR trên TOÀN BỘ file *_clean_baseline.csv (100% dòng, không sampling).
    Toàn bộ nhãn ở đây là Normal (1) -> mọi prediction == -1 là False Positive thật.
    """
    result = enhanced_detector.evaluate_series(service, df_baseline_features, model, active_anomalies_by_tick=None)
    old_pred = result["old_prediction"]
    enh_pred = result["enhanced_prediction"]

    n_total = len(old_pred)
    old_fp = int(np.sum(old_pred == -1))
    enh_fp = int(np.sum(enh_pred == -1))

    return {"n_total": n_total, "old_fp": old_fp, "enh_fp": enh_fp}


def evaluate_real_anomalies_full(enhanced_detector, service, model, df_baseline_features, df_anomalies_features):
    """
    Đánh giá trên dữ liệu SỰ CỐ THẬT (*_anomalies.csv) ghép với TOÀN BỘ clean baseline
    của cùng service (không sampling ở cả 2 phía), để có cả TP (trên anomalies) và
    TN/FP (trên baseline) trong cùng một phép đo Precision/Recall/F1/FPR.
    """
    df_combined = pd.concat([df_baseline_features, df_anomalies_features], ignore_index=True)
    y_true = df_combined["label"].values

    result = enhanced_detector.evaluate_series(service, df_combined, model, active_anomalies_by_tick=None)
    old_pred = result["old_prediction"]
    enh_pred = result["enhanced_prediction"]

    old_tp = int(np.sum((y_true == -1) & (old_pred == -1)))
    old_fp = int(np.sum((y_true == 1) & (old_pred == -1)))
    old_fn = int(np.sum((y_true == -1) & (old_pred == 1)))

    enh_tp = int(np.sum((y_true == -1) & (enh_pred == -1)))
    enh_fp = int(np.sum((y_true == 1) & (enh_pred == -1)))
    enh_fn = int(np.sum((y_true == -1) & (enh_pred == 1)))

    n_total = len(y_true)
    old_metrics = compute_metrics(old_tp, old_fp, old_fn, False, n_total)
    enh_metrics = compute_metrics(enh_tp, enh_fp, enh_fn, False, n_total)
    return {"n_total": n_total, "old": old_metrics, "enhanced": enh_metrics}


def evaluate_transient_spike_suppression_full(old_detector, enhanced_detector, n_cases=50):
    """
    Full-population test (không sampling: chạy đủ n_cases lần, seed cố định để tái lập)
    đo khả năng kháng nhiễu spike 1-tick của cả 2 Engine trên service 'frontend'.
    """
    old_false_alarms = 0
    enh_false_alarms = 0

    base_df_raw = generate_synthetic_data("frontend", duration_days=1, is_anomaly_set=False)

    rng = np.random.default_rng(BENCHMARK_RANDOM_SEED)
    for case_idx in range(n_cases):
        df_spike = base_df_raw.iloc[:12].copy()
        # Mỗi case dịch chuyển baseline một chút để không lặp lại y hệt case trước,
        # đồng thời vẫn hoàn toàn tái lập được nhờ rng seeded.
        jitter = rng.normal(0, 0.02)
        df_spike["latency_p90"] = df_spike["latency_p90"] + abs(jitter)
        df_spike.iat[11, df_spike.columns.get_loc("latency_p90")] = 4.5 + jitter
        df_spike.iat[11, df_spike.columns.get_loc("error_rate")] = 0.35

        df_feat_spike = feature_engineering(df_spike)
        X_tick = df_feat_spike[FEATURE_COLS].iloc[[-1]]

        if "frontend" not in old_detector.models:
            continue
        old_p = int(old_detector.models["frontend"].predict(X_tick)[0])
        if old_p == -1:
            old_false_alarms += 1

        gated = enhanced_detector.apply_enhanced_gates(
            service="frontend",
            base_prediction=old_p,
            base_score=float(old_detector.models["frontend"].decision_function(X_tick)[0]),
            window_df=df_feat_spike,
            active_anomalies_map=None,
        )
        if gated["prediction"] == -1:
            enh_false_alarms += 1

    return {"n_cases": n_cases, "old_false_alarms": old_false_alarms, "enh_false_alarms": enh_false_alarms}


def evaluate_downstream_cascade_suppression_full(enhanced_detector, n_cases=50):
    """
    Full-population test đo tỷ lệ triệt tiêu triệu chứng hạ nguồn khi service phụ thuộc
    (checkout) đang Anomaly thật, dùng ĐÚNG topology graph load từ services.json (không
    tự chế cạnh giả trong test) — service 'frontend' phụ thuộc 'checkout' theo services.json.
    """
    assert "checkout" in enhanced_detector.get_dependency_services("frontend"), \
        "services.json topology không khớp giả định benchmark: frontend phải phụ thuộc checkout"

    active_anomalies_map = {"checkout": {"prediction": -1, "score": -0.45}}
    suppressed_or_demoted = 0
    for _ in range(n_cases):
        gated = enhanced_detector.apply_enhanced_gates(
            service="frontend",
            base_prediction=-1,
            base_score=-0.35,
            window_df=pd.DataFrame(),  # không cần 3-Sigma ở đây, chỉ test Gate 2
            active_anomalies_map=active_anomalies_map,
        )
        if gated["score"] > -0.35:
            suppressed_or_demoted += 1

    return {"n_cases": n_cases, "suppressed_or_demoted": suppressed_or_demoted}


def run_ab_benchmark():
    logger.info("=" * 90)
    logger.info(">>> STARTING EMPIRICAL A/B BENCHMARK: OLD ENGINE vs ENHANCED ENGINE (FULL DATASET)")
    logger.info("=" * 90)

    old_detector = AnomalyDetector()
    old_detector.load_local_models()

    correlator = AlertCorrelator()  # load topology thật từ services.json
    enhanced_detector = EnhancedAnomalyDetector(correlator=correlator)
    enhanced_detector.load_local_models()

    data_dir = os.path.join(engine_dir, "datametric")

    # -------------------------------------------------------------------------
    # TEST 1: Clean Baseline — FULL FILE mỗi service (Specificity / FPR thật)
    # -------------------------------------------------------------------------
    baseline_totals = {"n_total": 0, "old_fp": 0, "enh_fp": 0}
    per_service_baseline = {}

    for service in SERVICES:
        baseline_file = os.path.join(data_dir, f"{service}_clean_baseline.csv")
        if not os.path.exists(baseline_file) or service not in old_detector.models:
            continue

        df_raw = pd.read_csv(baseline_file)
        if "timestamp" in df_raw.columns:
            df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
        df_feat = feature_engineering(df_raw)  # 100% số dòng, không cắt/sample

        model = old_detector.models[service]
        res = evaluate_clean_baseline_full(enhanced_detector, service, model, df_feat)
        per_service_baseline[service] = res
        baseline_totals["n_total"] += res["n_total"]
        baseline_totals["old_fp"] += res["old_fp"]
        baseline_totals["enh_fp"] += res["enh_fp"]

    # -------------------------------------------------------------------------
    # TEST 2: Real Incident Data (*_anomalies.csv) — FULL FILE, ghép với FULL baseline
    # -------------------------------------------------------------------------
    real_incident_results = {}
    for service in SERVICES:
        anomalies_file = os.path.join(data_dir, f"{service}_anomalies.csv")
        baseline_file = os.path.join(data_dir, f"{service}_clean_baseline.csv")
        if not os.path.exists(anomalies_file) or service not in old_detector.models:
            continue

        df_anom_raw = pd.read_csv(anomalies_file)
        df_base_raw = pd.read_csv(baseline_file)
        if "timestamp" in df_anom_raw.columns:
            df_anom_raw["timestamp"] = pd.to_datetime(df_anom_raw["timestamp"])
        if "timestamp" in df_base_raw.columns:
            df_base_raw["timestamp"] = pd.to_datetime(df_base_raw["timestamp"])

        df_anom_feat = feature_engineering(df_anom_raw)
        df_base_feat = feature_engineering(df_base_raw)

        model = old_detector.models[service]
        real_incident_results[service] = evaluate_real_anomalies_full(
            enhanced_detector, service, model, df_base_feat, df_anom_feat
        )

    # Tổng hợp (aggregate) Precision/Recall/F1/FPR trên TOÀN BỘ dữ liệu sự cố THẬT
    # (gộp mọi service có *_anomalies.csv) — đây là con số phản ánh đúng nhất chất lượng
    # thực tế của model, không bị nhiễu bởi lệch phân phối train/test như tập synthetic.
    real_old_tp = sum(r["old"]["tp"] for r in real_incident_results.values())
    real_old_fp = sum(r["old"]["fp"] for r in real_incident_results.values())
    real_old_fn = sum(r["old"]["fn"] for r in real_incident_results.values())
    real_enh_tp = sum(r["enhanced"]["tp"] for r in real_incident_results.values())
    real_enh_fp = sum(r["enhanced"]["fp"] for r in real_incident_results.values())
    real_enh_fn = sum(r["enhanced"]["fn"] for r in real_incident_results.values())
    real_n_total = sum(r["n_total"] for r in real_incident_results.values())

    real_old_agg = compute_metrics(real_old_tp, real_old_fp, real_old_fn, False, real_n_total)
    real_enh_agg = compute_metrics(real_enh_tp, real_enh_fp, real_enh_fn, False, real_n_total)

    # -------------------------------------------------------------------------
    # TEST 3: Synthetic Scenario Test Sets — FULL 3-day dataset mỗi kịch bản (không sample)
    # -------------------------------------------------------------------------
    scenario_results = {}
    old_tp_sum = old_fp_sum = old_fn_sum = 0
    enh_tp_sum = enh_fp_sum = enh_fn_sum = 0
    total_tp_lost = 0

    for service, scenarios in SERVICE_ANOMALY_MAP.items():
        if service not in old_detector.models:
            continue
        model = old_detector.models[service]
        for scn in scenarios:
            res = evaluate_scenario_full(old_detector, enhanced_detector, service, model, scn)
            scenario_results[f"{service}::{scn}"] = res

            old_tp_sum += res["old"]["tp"]
            old_fp_sum += res["old"]["fp"]
            old_fn_sum += res["old"]["fn"]
            enh_tp_sum += res["enhanced"]["tp"]
            enh_fp_sum += res["enhanced"]["fp"]
            enh_fn_sum += res["enhanced"]["fn"]
            total_tp_lost += res["tp_lost_to_suppression"]

    old_prec = old_tp_sum / (old_tp_sum + old_fp_sum) if (old_tp_sum + old_fp_sum) > 0 else 0.0
    old_rec = old_tp_sum / (old_tp_sum + old_fn_sum) if (old_tp_sum + old_fn_sum) > 0 else 0.0
    old_f1 = 2 * (old_prec * old_rec) / (old_prec + old_rec) if (old_prec + old_rec) > 0 else 0.0

    enh_prec = enh_tp_sum / (enh_tp_sum + enh_fp_sum) if (enh_tp_sum + enh_fp_sum) > 0 else 0.0
    enh_rec = enh_tp_sum / (enh_tp_sum + enh_fn_sum) if (enh_tp_sum + enh_fn_sum) > 0 else 0.0
    enh_f1 = 2 * (enh_prec * enh_rec) / (enh_prec + enh_rec) if (enh_prec + enh_rec) > 0 else 0.0

    n_scenario_ticks = sum(r["n_total"] for r in scenario_results.values())
    old_fpr = old_fp_sum / n_scenario_ticks if n_scenario_ticks > 0 else 0.0
    enh_fpr = enh_fp_sum / n_scenario_ticks if n_scenario_ticks > 0 else 0.0

    # -------------------------------------------------------------------------
    # TEST 4: Transient 1-Tick Spike Noise Suppression — full population, seeded
    # -------------------------------------------------------------------------
    spike_res = evaluate_transient_spike_suppression_full(old_detector, enhanced_detector, n_cases=50)
    spike_suppression_rate = (
        (spike_res["old_false_alarms"] - spike_res["enh_false_alarms"]) / spike_res["old_false_alarms"] * 100
        if spike_res["old_false_alarms"] > 0 else 100.0
    )

    # -------------------------------------------------------------------------
    # TEST 5: Topology Downstream Symptom Suppression — full population, real graph
    # -------------------------------------------------------------------------
    cascade_res = evaluate_downstream_cascade_suppression_full(enhanced_detector, n_cases=50)
    downstream_suppression_rate = cascade_res["suppressed_or_demoted"] / cascade_res["n_cases"] * 100

    # -------------------------------------------------------------------------
    # PRINT REPORT
    # -------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("      EMPIRICAL A/B BENCHMARK — FULL DATASET (KHÔNG SAMPLING)")
    print("      OLD ENGINE (Isolation Forest thuần) vs ENHANCED ENGINE (3-Sigma + Topology)")
    print("=" * 90)

    print(f"\n[1] CLEAN BASELINE SPECIFICITY (100% dòng mỗi service, tổng {baseline_totals['n_total']} ticks)")
    print(f"{'Metric':<42} | {'Old Engine':<18} | {'Enhanced Engine':<18}")
    print("-" * 82)
    old_spec = (baseline_totals["n_total"] - baseline_totals["old_fp"]) / baseline_totals["n_total"] * 100 if baseline_totals["n_total"] else 0
    enh_spec = (baseline_totals["n_total"] - baseline_totals["enh_fp"]) / baseline_totals["n_total"] * 100 if baseline_totals["n_total"] else 0
    print(f"{'Specificity (1 - FPR)':<42} | {old_spec:.2f}%{'':<13} | {enh_spec:.2f}%")
    print(f"{'False Positives (raw count)':<42} | {baseline_totals['old_fp']:<18} | {baseline_totals['enh_fp']:<18}")
    for svc, r in per_service_baseline.items():
        print(f"    - {svc:<20} n={r['n_total']:<6} | old_fp={r['old_fp']:<4} | enh_fp={r['enh_fp']:<4}")

    print(f"\n[2] REAL INCIDENT DATA (*_anomalies.csv, FULL FILE + FULL clean baseline)")
    print(f"    (Chỉ có dữ liệu sự cố THẬT ở: {', '.join(real_incident_results.keys())} — "
          f"các service khác không có *_anomalies.csv nên không xuất hiện ở đây)")
    for svc, r in real_incident_results.items():
        print(f"    - {svc}: n={r['n_total']}")
        print(f"        Old      -> P={r['old']['precision']:.4f} R={r['old']['recall']:.4f} F1={r['old']['f1_score']:.4f} FPR={r['old']['fpr']:.4f} (TP={r['old']['tp']} FP={r['old']['fp']} FN={r['old']['fn']})")
        print(f"        Enhanced -> P={r['enhanced']['precision']:.4f} R={r['enhanced']['recall']:.4f} F1={r['enhanced']['f1_score']:.4f} FPR={r['enhanced']['fpr']:.4f} (TP={r['enhanced']['tp']} FP={r['enhanced']['fp']} FN={r['enhanced']['fn']})")
    print(f"\n    >>> REAL-WORLD PRECISION AGGREGATE (gộp tất cả service có sự cố thật, n={real_n_total}) <<<")
    print(f"    {'Metric':<12} | {'Old Engine':<12} | {'Enhanced Engine':<12}")
    print(f"    {'Precision':<12} | {real_old_agg['precision']*100:>10.2f}% | {real_enh_agg['precision']*100:>10.2f}%")
    print(f"    {'Recall':<12} | {real_old_agg['recall']*100:>10.2f}% | {real_enh_agg['recall']*100:>10.2f}%")
    print(f"    {'F1-Score':<12} | {real_old_agg['f1_score']*100:>10.2f}% | {real_enh_agg['f1_score']*100:>10.2f}%")
    print(f"    {'FPR':<12} | {real_old_agg['fpr']*100:>10.2f}% | {real_enh_agg['fpr']*100:>10.2f}%")
    print(f"    (TP={real_old_agg['tp']}/{real_enh_agg['tp']} FP={real_old_agg['fp']}/{real_enh_agg['fp']} FN={real_old_agg['fn']}/{real_enh_agg['fn']}, Old/Enhanced)")

    print(f"\n[3] SYNTHETIC INCIDENT SCENARIOS (FULL 3-day dataset mỗi kịch bản, {n_scenario_ticks} ticks tổng)")
    print(f"{'Scenario':<28} | {'Old F1':<8} | {'Enh F1':<8} | {'TP mất do suppress':<10}")
    print("-" * 70)
    for name, r in scenario_results.items():
        print(f"{name:<28} | {r['old']['f1_score']:.4f}  | {r['enhanced']['f1_score']:.4f}  | {r['tp_lost_to_suppression']}")
    print("-" * 70)
    print(f"{'AGGREGATE (all scenarios)':<28} | {'Old':<18} | {'Enhanced':<18}")
    print(f"{'Precision':<28} | {old_prec*100:.2f}%{'':<12} | {enh_prec*100:.2f}%")
    print(f"{'Recall':<28} | {old_rec*100:.2f}%{'':<12} | {enh_rec*100:.2f}%")
    print(f"{'F1-Score':<28} | {old_f1*100:.2f}%{'':<12} | {enh_f1*100:.2f}%")
    print(f"{'FPR':<28} | {old_fpr*100:.2f}%{'':<12} | {enh_fpr*100:.2f}%")
    print(f"{'Total TP lost to suppression (Old đúng, Enhanced sai)':<55} | {total_tp_lost}")

    print(f"\n[4] TRANSIENT 1-TICK SPIKE NOISE ({spike_res['n_cases']} cases, seeded, full population)")
    print(f"    Old false alarms:      {spike_res['old_false_alarms']}/{spike_res['n_cases']}")
    print(f"    Enhanced false alarms: {spike_res['enh_false_alarms']}/{spike_res['n_cases']}")
    print(f"    Suppression rate:      {spike_suppression_rate:.1f}%")

    print(f"\n[5] TOPOLOGY DOWNSTREAM SYMPTOM SUPPRESSION ({cascade_res['n_cases']} cases, real services.json graph)")
    print(f"    frontend depends on checkout (services.json) — checkout Anomaly -> frontend score penalized")
    print(f"    Suppressed/demoted: {cascade_res['suppressed_or_demoted']}/{cascade_res['n_cases']} ({downstream_suppression_rate:.1f}%)")
    print("=" * 90 + "\n")

    # -------------------------------------------------------------------------
    # SAVE JSON
    # -------------------------------------------------------------------------
    benchmark_json = {
        "timestamp": datetime.now().isoformat(),
        "methodology": {
            "full_dataset_no_sampling": True,
            "shared_model_both_engines": True,
            "evaluation_formula_source": "train_anomaly_model_local.py::train_and_evaluate()",
            "random_seed": BENCHMARK_RANDOM_SEED,
        },
        "clean_baseline": {
            "total_ticks": baseline_totals["n_total"],
            "old_engine_fp": baseline_totals["old_fp"],
            "enhanced_engine_fp": baseline_totals["enh_fp"],
            "old_engine_specificity_pct": round(old_spec, 4),
            "enhanced_engine_specificity_pct": round(enh_spec, 4),
            "per_service": per_service_baseline,
        },
        "real_incident_data": real_incident_results,
        "real_incident_data_aggregate": {
            "n_total": real_n_total,
            "services_included": list(real_incident_results.keys()),
            "old_engine": real_old_agg,
            "enhanced_engine": real_enh_agg,
        },
        "synthetic_scenarios": {
            "per_scenario": scenario_results,
            "aggregate": {
                "old_engine": {"precision": round(old_prec, 4), "recall": round(old_rec, 4), "f1_score": round(old_f1, 4), "fpr": round(old_fpr, 4)},
                "enhanced_engine": {"precision": round(enh_prec, 4), "recall": round(enh_rec, 4), "f1_score": round(enh_f1, 4), "fpr": round(enh_fpr, 4)},
                "total_tp_lost_to_suppression": total_tp_lost,
                "total_ticks": n_scenario_ticks,
            },
        },
        "transient_spike_suppression": {
            **spike_res,
            "suppression_rate_percent": round(spike_suppression_rate, 2),
        },
        "downstream_topology_suppression": {
            **cascade_res,
            "suppression_rate_percent": round(downstream_suppression_rate, 2),
        },
    }

    benchmark_file = os.path.join(engine_dir, "benchmark_results.json")
    with open(benchmark_file, "w", encoding="utf-8") as f:
        json.dump(benchmark_json, f, indent=2, default=str)
    logger.info(f"Saved benchmark results JSON to: {benchmark_file}")

    return benchmark_json


if __name__ == "__main__":
    run_ab_benchmark()
