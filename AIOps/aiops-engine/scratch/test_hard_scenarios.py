import os
import sys
import numpy as np
import pandas as pd
import random
from datetime import datetime, timedelta
import joblib

# Thêm thư mục aiops-engine vào sys.path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from train_anomaly_model_local import feature_engineering

# Thiết lập seed
np.random.seed(100)
random.seed(100)

def generate_hard_test_data(service: str, duration_days: int = 5) -> pd.DataFrame:
    """
    Sinh dữ liệu test 'Khó' (Stress Test) chứa các biến động nhiễu mạnh nhưng là BÌNH THƯỜNG
    để thách thức mô hình máy học, nhằm xem mô hình có bị báo động giả (False Positive) hay không.
    Các nhiễu mô phỏng gồm:
      - Sự kiện Flash Sale (RPS x5, CPU & Latency tăng cao nhưng lỗi thấp => NORMAL)
      - Nhiễu mạng tạm thời (Latency vọt cao 1-2 mẫu rồi tự hết => NORMAL)
      - Tác vụ nền nặng (CPU vọt lên 95% nhưng không lỗi, không trễ => NORMAL)
      - Và 1 đoạn lỗi thực tế INC-3 ở cuối để đo khả năng bắt lỗi thật.
    """
    start_time = datetime(2026, 7, 1, 0, 0, 0)
    total_samples = duration_days * 288
    
    timestamps = [start_time + timedelta(minutes=5 * i) for i in range(total_samples)]
    
    rps_list = []
    cpu_list = []
    mem_list = []
    latency_list = []
    error_list = []
    labels = []  # 1: Normal, -1: Anomaly
    
    for i, t in enumerate(timestamps):
        hour = t.hour
        day_of_week = t.weekday()
        is_weekend = 1 if day_of_week >= 5 else 0
        is_biz_hours = 1 if (8 <= hour <= 18) and not is_weekend else 0
        
        # Baseline RPS bình thường
        if is_weekend:
            base_rps = random.uniform(10, 60)
        elif is_biz_hours:
            base_rps = random.uniform(80, 150)
        else:
            base_rps = random.uniform(5, 30)
            
        rps = max(2.0, base_rps + np.random.normal(0, base_rps * 0.1))
        cpu = min(0.95, max(0.02, (0.1 + (rps / 200.0) * 0.4) + np.random.normal(0, 0.05)))
        mem = min(0.95, max(0.1, (0.3 + (rps / 200.0) * 0.1) + np.random.normal(0, 0.02)))
        latency = max(0.01, (0.04 + (rps / 200.0) * 0.08) + np.random.normal(0, 0.01))
        error_rate = max(0.0, np.random.normal(0.001, 0.0005))
        
        current_label = 1 # Mặc định là bình thường
        
        # ----------------------------------------------------
        # THỬ THÁCH 1: Flash Sale (Mẫu 200 đến 250)
        # RPS tăng x5, CPU & Latency tăng cao nhưng là NORMAL (không lỗi)
        # ----------------------------------------------------
        if 200 <= i <= 250:
            rps = base_rps * 5.0
            cpu = random.uniform(0.85, 0.92)  # CPU cực cao
            latency = random.uniform(0.35, 0.50) # Trễ tăng do xếp hàng
            error_rate = max(0.0, np.random.normal(0.001, 0.0003)) # Vẫn xử lý tốt (Error rất thấp)
            
        # ----------------------------------------------------
        # THỬ THÁCH 2: Nhiễu mạng gRPC tạm thời (Mẫu 500 đến 502)
        # Latency tăng vọt lên 1.2s trong 3 mẫu, sau đó tự phục hồi => NORMAL
        # ----------------------------------------------------
        elif 500 <= i <= 502:
            latency = random.uniform(1.2, 1.5)
            
        # ----------------------------------------------------
        # THỬ THÁCH 3: Tác vụ nén file backup nền (Mẫu 800 đến 815)
        # CPU nhảy vọt lên 95%, nhưng RPS thấp, Latency thấp => NORMAL
        # ----------------------------------------------------
        elif 800 <= i <= 815:
            cpu = random.uniform(0.92, 0.97)
            
        # ----------------------------------------------------
        # THỬ THÁCH 4: LỖI THỰC TẾ (LỖI THẬT) (Mẫu 1100 đến 1136 - 3 giờ)
        # Error rate tăng vọt lên 45% (INC-3 Bad Deployment) => ANOMALY
        # ----------------------------------------------------
        elif 1100 <= i <= 1136:
            error_rate = random.uniform(0.40, 0.65)
            current_label = -1
            
        rps_list.append(rps)
        cpu_list.append(cpu)
        mem_list.append(mem)
        latency_list.append(latency)
        error_list.append(error_rate)
        labels.append(current_label)
        
    df = pd.DataFrame({
        "timestamp": timestamps,
        "service": [service] * total_samples,
        "rps": rps_list,
        "cpu_usage": cpu_list,
        "memory_usage": mem_list,
        "latency_p90": latency_list,
        "error_rate": error_list,
        "label": labels
    })
    return df

def test_hard_validation():
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(engine_dir, "models")
    data_dir = os.path.join(engine_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    service = "frontend"
    model_path = os.path.join(models_dir, f"{service}_iforest.joblib")
    
    if not os.path.exists(model_path):
        print(f"ERROR: Model file {model_path} not found! Please run train_anomaly_model_local.py first.")
        return
        
    print("Loading Isolation Forest model for frontend...")
    model = joblib.load(model_path)
    
    print("\nGenerating 'HARD' test dataset (5 days)...")
    df_hard_raw = generate_hard_test_data(service, duration_days=5)
    df_hard = feature_engineering(df_hard_raw)
    
    # Lưu ra file CSV để người dùng quan sát
    hard_csv_path = os.path.join(data_dir, f"{service}_hard_test.csv")
    df_hard.to_csv(hard_csv_path, index=False)
    print(f"Saved hard test dataset to: {hard_csv_path}")
    
    feature_cols = [
        "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
        "error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth",
        "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
    ]
    
    X_test = df_hard[feature_cols]
    y_true = df_hard["label"].values
    
    # Dự đoán
    y_pred = model.predict(X_test)
    
    # Thống kê ma trận nhầm lẫn
    tp = np.sum((y_true == -1) & (y_pred == -1))
    fp = np.sum((y_true == 1) & (y_pred == -1))
    fn = np.sum((y_true == -1) & (y_pred == 1))
    tn = np.sum((y_true == 1) & (y_pred == 1))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Phân tích xem các cảnh báo giả (FP) rơi vào vùng thử thách nào
    fp_indices = np.where((y_true == 1) & (y_pred == -1))[0]
    
    flash_sale_fp = np.sum((200 <= fp_indices) & (fp_indices <= 250))
    jitter_fp = np.sum((500 <= fp_indices) & (fp_indices <= 502))
    backup_fp = np.sum((800 <= fp_indices) & (fp_indices <= 815))
    other_fp = len(fp_indices) - (flash_sale_fp + jitter_fp + backup_fp)
    
    print("\n" + "="*60)
    print("STRESS TEST REPORT - ML ANOMALY DETECTION:")
    print("="*60)
    print(f"Total Test Samples: {len(df_hard)}")
    print(f"True Positives (TP - Bat trung loi):      {tp} / 37")
    print(f"False Positives (FP - Bao dong gia):     {fp}")
    print(f"  +- Flash Sale load spikes (mau 200-250): {flash_sale_fp} FP")
    print(f"  +- Network latency jitters (mau 500-502): {jitter_fp} FP")
    print(f"  +- Heavy background task (mau 800-815):  {backup_fp} FP")
    print(f"  +- Normal random noise fluctuations:     {other_fp} FP")
    print(f"True Negatives (TN - Nhan dinh dung khoe): {tn}")
    print(f"False Negatives (FN - Lot luoi bo sot):    {fn}")
    print("-"*60)
    print(f"Precision (Do tin cay canh bao): {precision:.4f}")
    print(f"Recall (Do nhay phat hien loi): {recall:.4f}")
    print(f"F1-Score:                        {f1_score:.4f}")
    print("="*60)
    
if __name__ == "__main__":
    test_hard_validation()
