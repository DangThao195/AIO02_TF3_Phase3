import os
import glob
import pandas as pd

def clean_and_filter_datasets():
    print("======================================================================")
    print(">>> CLEANING AND FILTERING REAL PROMETHEUS TELEMETRY DATA")
    print("======================================================================")
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "datametric")
    
    real_files = sorted(glob.glob(os.path.join(data_dir, "*_real_7d.csv")))
    
    # Ngưỡng lọc Healthy Baseline
    MAX_HEALTHY_ERROR_RATE = 0.05  # Max 5% error rate cho baseline
    
    summary = []
    
    for f in real_files:
        service_name = os.path.basename(f).replace("_real_7d.csv", "")
        df_raw = pd.read_csv(f)
        total_rows = len(df_raw)
        
        # 1. Lọc tập Healthy Baseline (Train Set)
        df_baseline = df_raw[df_raw["error_rate"] <= MAX_HEALTHY_ERROR_RATE].copy()
        df_baseline["label"] = 1  # 1: Normal
        
        # 2. Lọc tập Anomaly Spikes (Validation Set)
        df_anomalies = df_raw[df_raw["error_rate"] > MAX_HEALTHY_ERROR_RATE].copy()
        df_anomalies["label"] = -1 # -1: Anomaly
        
        # Save clean baseline
        baseline_file = os.path.join(data_dir, f"{service_name}_clean_baseline.csv")
        df_baseline.to_csv(baseline_file, index=False)
        
        # Save anomalies set (if any)
        anomaly_file = os.path.join(data_dir, f"{service_name}_anomalies.csv")
        if not df_anomalies.empty:
            df_anomalies.to_csv(anomaly_file, index=False)
            
        summary.append({
            "service": service_name,
            "raw_total": total_rows,
            "baseline_rows": len(df_baseline),
            "anomaly_rows": len(df_anomalies),
            "baseline_file": os.path.basename(baseline_file),
            "anomaly_file": os.path.basename(anomaly_file) if not df_anomalies.empty else "None"
        })
        
    print("\nSUMMARY FILTERING RESULTS:")
    print("---------------------------------------------------------------------------------------------------------")
    print(f"{'Service':<18} | {'Total Raw':<10} | {'Baseline (Train)':<16} | {'Anomalies (Val)':<16} | {'Clean File':<25}")
    print("---------------------------------------------------------------------------------------------------------")
    for item in summary:
        print(f"{item['service']:<18} | {item['raw_total']:<10} | {item['baseline_rows']:<16} | {item['anomaly_rows']:<16} | {item['baseline_file']:<25}")
    print("---------------------------------------------------------------------------------------------------------")

if __name__ == "__main__":
    clean_and_filter_datasets()
