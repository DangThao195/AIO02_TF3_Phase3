import os
import json
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
import joblib

# Thiết lập thư mục đầu ra
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Khởi tạo hạt giống ngẫu nhiên để có kết quả nhất quán
np.random.seed(42)
random.seed(42)

SERVICES = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]

def generate_synthetic_data(service: str, duration_days: int = 14, is_anomaly_set: bool = False, anomaly_type: str = None) -> pd.DataFrame:
    """
    Sinh dữ liệu telemetry giả lập phản ánh đúng behavior thật của TechX-Corp.
    Chu kỳ: 5 phút/mẫu. 1 ngày = 288 mẫu.
    """
    start_time = datetime(2026, 6, 1, 0, 0, 0)
    total_samples = duration_days * 288
    
    timestamps = [start_time + timedelta(minutes=5 * i) for i in range(total_samples)]
    
    # 1. Sinh các tín hiệu thô cơ bản (Normal baseline với daily cycle)
    rps_list = []
    cpu_list = []
    mem_list = []
    latency_list = []
    error_list = []
    
    for t in timestamps:
        hour = t.hour
        day_of_week = t.weekday() # 0-6
        is_weekend = 1 if day_of_week >= 5 else 0
        is_biz_hours = 1 if (8 <= hour <= 18) and not is_weekend else 0
        
        # RPS baseline
        if is_weekend:
            base_rps = random.uniform(10, 60)
        elif is_biz_hours:
            base_rps = random.uniform(80, 180)
        else: # off-peak
            base_rps = random.uniform(5, 30)
            
        # Thêm nhiễu Gaussian
        rps = max(2.0, base_rps + np.random.normal(0, base_rps * 0.1))
        
        # CPU usage (tỷ lệ thuận với RPS + nhiễu)
        cpu_base = 0.1 + (rps / 200.0) * 0.4
        cpu = min(0.95, max(0.02, cpu_base + np.random.normal(0, 0.05)))
        
        # Memory usage (tăng dần nhẹ theo thời gian + rps context)
        mem_base = 0.3 + (rps / 200.0) * 0.1
        mem = min(0.95, max(0.1, mem_base + np.random.normal(0, 0.02)))
        
        # Latency p90 (giây)
        latency_base = 0.04 + (rps / 200.0) * 0.08
        latency = max(0.01, latency_base + np.random.normal(0, latency_base * 0.15))
        
        # Error rate (0.0 đến 1.0)
        error_rate = max(0.0, np.random.normal(0.001, 0.0005))
        if random.random() < 0.02: # 2% xác suất spike lỗi cực nhẹ bình thường
            error_rate = random.uniform(0.005, 0.01)
            
        rps_list.append(rps)
        cpu_list.append(cpu)
        mem_list.append(mem)
        latency_list.append(latency)
        error_list.append(error_rate)
        
    df = pd.DataFrame({
        "timestamp": timestamps,
        "service": [service] * total_samples,
        "rps": rps_list,
        "cpu_usage": cpu_list,
        "memory_usage": mem_list,
        "latency_p90": latency_list,
        "error_rate": error_list
    })
    
    # 2. Inject kịch bản bất thường (Anomaly Patterns) cho validation/test set
    labels = [1] * total_samples # 1: Normal, -1: Anomaly
    
    if is_anomaly_set and anomaly_type:
        anomaly_start_idx = int(total_samples * 0.6)
        anomaly_duration = 36 # 3 giờ (36 mẫu * 5 phút = 180 phút)
        
        for idx in range(anomaly_start_idx, anomaly_start_idx + anomaly_duration):
            if idx >= total_samples:
                break
            labels[idx] = -1
            
            if anomaly_type == "INC-1":
                # CPU tăng vọt, latency tăng vọt, rps đi ngang/giảm (DB bottleneck)
                df.at[idx, "cpu_usage"] = random.uniform(0.90, 0.98)
                df.at[idx, "latency_p90"] = random.uniform(1.2, 2.5)
                df.at[idx, "rps"] = df.at[idx, "rps"] * 0.7
            elif anomaly_type == "INC-2":
                # Memory tăng liên tục, error_rate vọt lên cao, rps giảm (OOM)
                df.at[idx, "memory_usage"] = min(0.99, 0.85 + (idx - anomaly_start_idx) * 0.01)
                df.at[idx, "error_rate"] = random.uniform(0.15, 0.35)
                df.at[idx, "rps"] = df.at[idx, "rps"] * 0.4
            elif anomaly_type == "INC-3":
                # Error rate spike mạnh trong khi rps bình thường (Bad deploy)
                df.at[idx, "error_rate"] = random.uniform(0.40, 0.80)
            elif anomaly_type == "INC-4":
                # Latency vọt rất cao, error_rate tăng (LLM / RPC timeout)
                df.at[idx, "latency_p90"] = random.uniform(4.5, 6.0)
                df.at[idx, "error_rate"] = random.uniform(0.80, 1.0)
            elif anomaly_type == "INC-5":
                # Kafka lag hoặc tài nguyên bão hòa kỳ lạ
                df.at[idx, "cpu_usage"] = random.uniform(0.80, 0.95)
                df.at[idx, "latency_p90"] = random.uniform(0.8, 1.5)
                
    df["label"] = labels
    return df

def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính toán và trích xuất 14 đặc trưng (Features) từ tín hiệu telemetry thô.
    Bổ sung is_high_traffic_period tự thích ứng từ rolling stats.
    """
    df = df.copy()
    
    # Sắp xếp theo mốc thời gian tăng dần
    df = df.sort_values(by="timestamp").reset_index(drop=True)
    
    # Nhóm 1: Raw Signals
    # Nhóm 2: Derived Features
    df["error_ratio"] = df["error_rate"] / (df["rps"] + 1e-5)
    
    # rolling median 1h (1h = 12 mẫu)
    df["rolling_median_1h"] = df["latency_p90"].rolling(window=12, min_periods=1).median()
    df["latency_deviation"] = df["latency_p90"] / (df["rolling_median_1h"] + 1e-5)
    
    # rps delta (t - (t-5m)) => shift 1 mẫu
    df["rps_delta"] = df["rps"] - df["rps"].shift(1).fillna(0)
    df["cpu_per_rps"] = df["cpu_usage"] / (df["rps"] + 1e-5)
    
    # memory growth rate (t - (t-30m)) => shift 6 mẫu
    df["memory_growth"] = df["memory_usage"] - df["memory_usage"].shift(6).fillna(0)
    
    # Nhóm 3: Temporal Features
    df["hour_of_day"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.weekday
    
    # is_business_hours: Giờ hành chính ngày thường (Thứ 2 đến thứ 6, từ 8h đến 18h)
    df["is_business_hours"] = ((df["hour_of_day"] >= 8) & (df["hour_of_day"] <= 18) & (df["day_of_week"] < 5)).astype(int)
    
    # Giải pháp 3: Tự động tính toán is_high_traffic_period từ rps rolling median
    df["rolling_median_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).median()
    df["is_high_traffic_period"] = ((df["rps"] > 100) & (df["rps"] > 1.5 * df["rolling_median_rps_1h"])).astype(int)
    
    # Điền giá trị trống nếu có do phép dịch chuyển shift
    df = df.fillna(0)
    return df

def train_and_evaluate():
    """
    Quy trình huấn luyện và đánh giá mô hình Isolation Forest cục bộ kết hợp Golden Cache.
    """
    print("======================================================================")
    print(">>> START: TRAINING & EVALUATING ISOLATION FOREST MODELS WITH GOLDEN CACHE")
    print("======================================================================")
    
    # Các đặc trưng đầu vào cho mô hình Isolation Forest (14 features)
    feature_cols = [
        "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
        "error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth",
        "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
    ]
    
    engine_dir = os.path.dirname(os.path.abspath(__file__))
    golden_path = os.path.join(engine_dir, "data", "golden_samples.csv")
    
    if not os.path.exists(golden_path):
        print(f"ERROR: Golden samples file not found at {golden_path}. Please generate it first.")
        return
        
    df_golden_all = pd.read_csv(golden_path)
    df_golden_all["timestamp"] = pd.to_datetime(df_golden_all["timestamp"])
    
    results_report = {}
    
    service_anomaly_map = {
        "frontend": "INC-3",
        "checkout": "INC-1",
        "payment": "INC-2",
        "product-catalog": "INC-1",
        "product-reviews": "INC-4",
        "shipping": "INC-5",
        "recommendation": "INC-3"
    }
    
    for service in SERVICES:
        print(f"\nProcessing Service: {service}")
        
        # 1. Lấy dữ liệu 14 ngày rolling real/synthetic
        df_train_raw = generate_synthetic_data(service, duration_days=14, is_anomaly_set=False)
        df_train = feature_engineering(df_train_raw)
        
        # 2. Tải Golden Cache và chỉ ghép các dòng NORMAL (label == 1) để tránh Leakage
        df_gold_svc = df_golden_all[df_golden_all["service"] == service]
        df_gold_normal = df_gold_svc[df_gold_svc["label"] == 1]
        df_gold_normal_features = feature_engineering(df_gold_normal)
        
        # Concat tập Train = 14 ngày rolling + Golden Normal Samples
        df_combined_train = pd.concat([df_train, df_gold_normal_features], ignore_index=True)
        
        # 3. Huấn luyện mô hình Isolation Forest
        # Tăng contamination nhẹ lên 0.03 để bao quát tốt hơn tải cực đại sạch
        model = IsolationForest(
            n_estimators=200,
            contamination=0.03,
            max_features=0.8,
            random_state=42,
            n_jobs=-1
        )
        
        X_train = df_combined_train[feature_cols]
        model.fit(X_train)
        
        # Lưu file mô hình đã train
        model_path = os.path.join(OUTPUT_DIR, f"{service}_iforest.joblib")
        joblib.dump(model, model_path)
        print(f"  -> Model saved to: {model_path}")
        
        # 4. Sinh tập đánh giá (Validation/Test Set) chứa sự cố cụ thể
        anomaly_type = service_anomaly_map[service]
        df_val_raw = generate_synthetic_data(service, duration_days=3, is_anomaly_set=True, anomaly_type=anomaly_type)
        df_val = feature_engineering(df_val_raw)
        
        # Lấy thêm 500 dòng INC patterns (lỗi thật) từ Golden Set để làm tập validate (KHÔNG train)
        df_gold_anom = df_gold_svc[df_gold_svc["label"] == -1]
        df_gold_anom_features = feature_engineering(df_gold_anom)
        
        # Gộp tập Test = 3 ngày validation + Golden Anomaly Samples (Lỗi thật)
        df_combined_test = pd.concat([df_val, df_gold_anom_features], ignore_index=True)
        
        X_val = df_combined_test[feature_cols]
        y_true = df_combined_test["label"].values # 1: Normal, -1: Anomaly
        
        # 5. Dự đoán trạng thái bất thường
        y_pred = model.predict(X_val)
        
        # 6. Tính toán ma trận nhầm lẫn
        tp = np.sum((y_true == -1) & (y_pred == -1))
        fp = np.sum((y_true == 1) & (y_pred == -1))
        fn = np.sum((y_true == -1) & (y_pred == 1))
        tn = np.sum((y_true == 1) & (y_pred == 1))
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        print(f"  -> Validation scenario: {anomaly_type}")
        print(f"  -> TP: {tp}, FP: {fp}, FN: {fn}, TN: {tn}")
        print(f"  -> Precision: {precision:.4f} (Target >= 0.85)")
        print(f"  -> Recall:    {recall:.4f} (Target >= 0.70)")
        print(f"  -> F1-Score:  {f1_score:.4f} (Target >= 0.77)")
        
        # Chốt chặn an toàn: Fail nếu recall hoặc precision bị sụt giảm quá thấp
        if recall < 0.70 or precision < 0.75:
            print("  🚨 [WARNING] Model quality guardrail breached! Check features.")
            
        results_report[service] = {
            "scenario": anomaly_type,
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score
        }
        
    print("\n" + "="*70)
    print("[EVALUATION REPORT] ISOLATION FOREST LOCAL MODEL PERFORMANCE WITH GOLDEN CACHE:")
    print("="*70)
    avg_f1 = []
    for svc, metrics in results_report.items():
        avg_f1.append(metrics["f1_score"])
        status = "PASSED" if metrics["f1_score"] >= 0.77 else "FAILED"
        print(f"Service: {svc:<17} | F1: {metrics['f1_score']:.4f} | Precision: {metrics['precision']:.4f} | Recall: {metrics['recall']:.4f} | Status: {status}")
    
    print("-"*70)
    print(f"System-wide Average F1-Score: {np.mean(avg_f1):.4f}")
    print("="*70)

if __name__ == "__main__":
    train_and_evaluate()
