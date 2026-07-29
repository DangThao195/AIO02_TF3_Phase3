import os
import sys

# Thêm thư mục aiops-engine vào sys.path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from train_anomaly_model_local import generate_synthetic_data, feature_engineering

def main():
    # Tạo thư mục data/ ở root của engine
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(engine_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    services = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]
    
    service_anomaly_map = {
        "frontend": "INC-3",
        "checkout": "INC-1",
        "payment": "INC-2",
        "product-catalog": "INC-1",
        "product-reviews": "INC-4",
        "shipping": "INC-5",
        "recommendation": "INC-3"
    }
    
    print(f"Exporting generated data to: {data_dir}")
    
    for service in services:
        print(f"Generating and exporting data for: {service}...")
        
        # 1. Sinh dữ liệu training (Normal baseline)
        df_train_raw = generate_synthetic_data(service, duration_days=14, is_anomaly_set=False)
        df_train = feature_engineering(df_train_raw)
        train_csv_path = os.path.join(data_dir, f"{service}_train.csv")
        df_train.to_csv(train_csv_path, index=False)
        
        # 2. Sinh dữ liệu test/validation (Có chứa anomaly)
        anomaly_type = service_anomaly_map[service]
        df_test_raw = generate_synthetic_data(service, duration_days=3, is_anomaly_set=True, anomaly_type=anomaly_type)
        df_test = feature_engineering(df_test_raw)
        test_csv_path = os.path.join(data_dir, f"{service}_test.csv")
        df_test.to_csv(test_csv_path, index=False)
        
        print(f"  -> Saved {service}_train.csv ({len(df_train)} rows)")
        print(f"  -> Saved {service}_test.csv ({len(df_test)} rows)")
        
    print("\nSUCCESS: All data successfully exported to data/ folder!")

if __name__ == "__main__":
    main()
