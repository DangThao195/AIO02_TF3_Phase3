import sys
import os
import pandas as pd

# Thêm thư mục chứa train_anomaly_model_local.py vào sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from train_anomaly_model_local import generate_synthetic_data, SERVICES

data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(data_dir, exist_ok=True)

service_anomaly_map = {
    "frontend": ["SCN-A", "SCN-G"],
    "checkout": ["SCN-F"],
    "payment": ["SCN-C"],
    "product-catalog": ["SCN-E"],
    "product-reviews": ["SCN-B"],
    "shipping": ["SCN-H"],
    "recommendation": ["SCN-D", "SCN-I"]
}

print(f"Exporting scenario datasets to CSV in: {data_dir}...")

for service in SERVICES:
    # 1. Sinh dữ liệu Train (14 ngày baseline sạch)
    df_train = generate_synthetic_data(service, duration_days=14, is_anomaly_set=False)
    train_path = os.path.join(data_dir, f"{service}_train.csv")
    df_train.to_csv(train_path, index=False)
    print(f" - Saved {service} Train baseline -> {service}_train.csv ({len(df_train)} samples)")
    
    # 2. Sinh dữ liệu Test/Validation (3 ngày chứa kịch bản sự cố cụ thể)
    anomaly_types = service_anomaly_map[service]
    for anomaly_type in anomaly_types:
        df_test = generate_synthetic_data(service, duration_days=3, is_anomaly_set=True, anomaly_type=anomaly_type)
        if len(anomaly_types) == 1:
            test_path = os.path.join(data_dir, f"{service}_test.csv")
        else:
            test_path = os.path.join(data_dir, f"{service}_test_{anomaly_type.lower().replace('-', '_')}.csv")
        df_test.to_csv(test_path, index=False)
        print(f" - Saved {service} Test [{anomaly_type}] -> {os.path.basename(test_path)} ({len(df_test)} samples)")

print("All scenario datasets exported successfully!")
