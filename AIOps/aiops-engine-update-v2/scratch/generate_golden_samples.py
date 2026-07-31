import os
import sys
import numpy as np
import pandas as pd
import random
from datetime import datetime, timedelta

# Thêm thư mục aiops-engine vào sys.path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np.random.seed(42)
random.seed(42)

SERVICES = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]

def generate_golden_samples():
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(engine_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    all_dfs = []
    
    service_anomaly_map = {
        "frontend": "INC-3",
        "checkout": "INC-1",
        "payment": "INC-2",
        "product-catalog": "INC-1",
        "product-reviews": "INC-4",
        "shipping": "INC-5",
        "recommendation": "INC-3"
    }
    
    start_time = datetime(2026, 5, 1, 0, 0, 0)
    
    for service in SERVICES:
        print(f"Generating golden samples for {service}...")
        
        # 1. 500 rows: Normal off-peak (RPS 5-30, CPU thap, Latency thap)
        off_peak_rps = np.random.uniform(5, 30, 500)
        off_peak_cpu = 0.05 + (off_peak_rps / 200.0) * 0.2 + np.random.normal(0, 0.02, 500)
        off_peak_mem = np.random.uniform(0.2, 0.4, 500)
        off_peak_lat = 0.02 + (off_peak_rps / 200.0) * 0.04 + np.random.normal(0, 0.005, 500)
        off_peak_err = np.random.uniform(0.0001, 0.001, 500)
        
        df_off = pd.DataFrame({
            "timestamp": [start_time + timedelta(minutes=5 * i) for i in range(500)],
            "service": [service] * 500,
            "rps": off_peak_rps,
            "cpu_usage": np.clip(off_peak_cpu, 0.01, 0.95),
            "memory_usage": np.clip(off_peak_mem, 0.01, 0.95),
            "latency_p90": np.clip(off_peak_lat, 0.005, 1.0),
            "error_rate": np.clip(off_peak_err, 0.0, 1.0),
            "label": [1] * 500
        })
        
        # 2. 500 rows: Normal business hours burst (RPS 80-150, CPU trung binh, Latency trung binh)
        biz_rps = np.random.uniform(80, 150, 500)
        biz_cpu = 0.15 + (biz_rps / 200.0) * 0.4 + np.random.normal(0, 0.03, 500)
        biz_mem = np.random.uniform(0.4, 0.6, 500)
        biz_lat = 0.05 + (biz_rps / 200.0) * 0.08 + np.random.normal(0, 0.01, 500)
        biz_err = np.random.uniform(0.0005, 0.002, 500)
        
        df_biz = pd.DataFrame({
            "timestamp": [start_time + timedelta(minutes=5 * (i + 500)) for i in range(500)],
            "service": [service] * 500,
            "rps": biz_rps,
            "cpu_usage": np.clip(biz_cpu, 0.01, 0.95),
            "memory_usage": np.clip(biz_mem, 0.01, 0.95),
            "latency_p90": np.clip(biz_lat, 0.005, 1.0),
            "error_rate": np.clip(biz_err, 0.0, 1.0),
            "label": [1] * 500
        })
        
        # 3. 500 rows: Borderline high load Flash Sale (RPS 400-600, CPU cao 85-92%, Latency 300-500ms, NO ERRORS)
        sale_rps = np.random.uniform(400, 600, 500)
        sale_cpu = np.random.uniform(0.85, 0.92, 500)
        sale_mem = np.random.uniform(0.70, 0.85, 500)
        sale_lat = np.random.uniform(0.30, 0.48, 500)
        sale_err = np.random.uniform(0.0001, 0.001, 500)
        
        df_sale = pd.DataFrame({
            "timestamp": [start_time + timedelta(minutes=5 * (i + 1000)) for i in range(500)],
            "service": [service] * 500,
            "rps": sale_rps,
            "cpu_usage": np.clip(sale_cpu, 0.01, 0.98),
            "memory_usage": np.clip(sale_mem, 0.01, 0.98),
            "latency_p90": np.clip(sale_lat, 0.005, 2.0),
            "error_rate": np.clip(sale_err, 0.0, 1.0),
            "label": [1] * 500
        })
        
        # 4. 500 rows: INC patterns labeled anomaly (label = -1)
        anomaly_type = service_anomaly_map[service]
        anom_rps = np.random.uniform(50, 120, 500)
        anom_cpu = np.random.uniform(0.3, 0.6, 500)
        anom_mem = np.random.uniform(0.4, 0.6, 500)
        anom_lat = np.random.uniform(0.05, 0.15, 500)
        anom_err = np.random.uniform(0.001, 0.005, 500)
        
        # Inject loi vao data
        if anomaly_type == "INC-1":
            anom_cpu = np.random.uniform(0.90, 0.98, 500)
            anom_lat = np.random.uniform(1.2, 2.5, 500)
            anom_rps = anom_rps * 0.5
        elif anomaly_type == "INC-2":
            anom_mem = np.random.uniform(0.90, 0.99, 500)
            anom_err = np.random.uniform(0.15, 0.35, 500)
            anom_rps = anom_rps * 0.4
        elif anomaly_type == "INC-3":
            anom_err = np.random.uniform(0.40, 0.80, 500)
        elif anomaly_type == "INC-4":
            anom_lat = np.random.uniform(4.5, 6.0, 500)
            anom_err = np.random.uniform(0.80, 1.0, 500)
        elif anomaly_type == "INC-5":
            anom_cpu = np.random.uniform(0.80, 0.95, 500)
            anom_lat = np.random.uniform(0.8, 1.5, 500)
            
        df_anom = pd.DataFrame({
            "timestamp": [start_time + timedelta(minutes=5 * (i + 1500)) for i in range(500)],
            "service": [service] * 500,
            "rps": anom_rps,
            "cpu_usage": np.clip(anom_cpu, 0.01, 0.98),
            "memory_usage": np.clip(anom_mem, 0.01, 0.99),
            "latency_p90": np.clip(anom_lat, 0.005, 8.0),
            "error_rate": np.clip(anom_err, 0.0, 1.0),
            "label": [-1] * 500
        })
        
        df_svc = pd.concat([df_off, df_biz, df_sale, df_anom], ignore_index=True)
        all_dfs.append(df_svc)
        
    df_all = pd.concat(all_dfs, ignore_index=True)
    golden_csv_path = os.path.join(data_dir, "golden_samples.csv")
    df_all.to_csv(golden_csv_path, index=False)
    print(f"\nSUCCESS: Generated {len(df_all)} golden samples at: {golden_csv_path}")

if __name__ == "__main__":
    generate_golden_samples()
