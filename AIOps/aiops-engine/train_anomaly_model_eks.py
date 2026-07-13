import os
import sys
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
import joblib
import boto3
from config import PROMETHEUS_URL, S3_BUCKET_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIOpsEngine.TrainEKS")

SERVICES = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]
FEATURE_COLS = [
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
    "error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth",
    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
]

def query_prometheus_range(query: str, start_time: datetime, end_time: datetime, step: str = "5m") -> list:
    """Gọi API query_range của Prometheus để lấy dữ liệu lịch sử."""
    try:
        url = f"{PROMETHEUS_URL}/api/v1/query_range"
        params = {
            "query": query,
            "start": int(start_time.timestamp()),
            "end": int(end_time.timestamp()),
            "step": step
        }
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status") == "success":
                return res_json.get("data", {}).get("result", [])
    except Exception as e:
        logger.warning(f"Error querying Prometheus query_range: {e}")
    return []

def parse_prometheus_result(result_list: list) -> pd.Series:
    """Chuyển đổi dữ liệu từ Prometheus range query sang pandas Series có index là timestamp."""
    if not result_list:
        return pd.Series(dtype=float)
    
    values = result_list[0].get("values", [])
    timestamps = []
    data_points = []
    for ts, val in values:
        timestamps.append(datetime.fromtimestamp(float(ts)))
        data_points.append(float(val))
        
    return pd.Series(data=data_points, index=timestamps)

def fetch_metrics_from_prometheus(service: str, duration_days: int = 7) -> pd.DataFrame:
    """Thu thập đầy đủ 5 Golden Signals thực tế từ Prometheus của EKS."""
    end_time = datetime.now()
    start_time = end_time - timedelta(days=duration_days)
    
    queries = {
        "rps": f'sum(rate(http_server_duration_milliseconds_count{{service="{service}"}}[5m]))',
        "error_rate": f'sum(rate(http_server_duration_milliseconds_count{{service="{service}", http_status_code=~"5.."}}[5m]))',
        "latency_p90": f'histogram_quantile(0.90, sum(rate(http_server_duration_milliseconds_bucket{{service="{service}"}}[5m])) by (le))',
        "cpu_usage": f'sum(rate(container_cpu_usage_seconds_total{{container="{service}"}}[5m]))',
        "memory_usage": f'sum(container_memory_working_set_bytes{{container="{service}"}}) / sum(container_spec_memory_limit_bytes{{container="{service}"}})'
    }
    
    data_dict = {}
    for metric_name, query_str in queries.items():
        raw_res = query_prometheus_range(query_str, start_time, end_time, step="5m")
        series = parse_prometheus_result(raw_res)
        if not series.empty:
            data_dict[metric_name] = series
            
    if len(data_dict) < 3:
        return pd.DataFrame()
        
    df = pd.DataFrame(data_dict)
    df = df.interpolate(method="time").ffill().bfill()
    df = df.reset_index().rename(columns={"index": "timestamp"})
    df["service"] = service
    return df

def generate_fallback_synthetic_data(service: str, duration_days: int = 14) -> pd.DataFrame:
    """Sinh dữ liệu giả lập dự phòng chất lượng cao khi Prometheus không khả dụng."""
    from train_anomaly_model_local import generate_synthetic_data
    logger.info(f"Generating fallback synthetic training dataset for {service} ({duration_days} days)...")
    return generate_synthetic_data(service, duration_days=duration_days, is_anomaly_set=False)

def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """Phái sinh 14 đặc trưng máy học."""
    from train_anomaly_model_local import feature_engineering as local_fe
    return local_fe(df)

def check_data_sufficiency(df: pd.DataFrame) -> bool:
    """Kiểm tra điều kiện chất lượng dữ liệu để tránh cold start và overfitting."""
    if df.empty:
        return False
        
    n_samples = len(df)
    if n_samples < 288:
        logger.warning(f"Data sufficiency check failed: n_samples={n_samples} (min required 288).")
        return False
        
    for col in ["rps", "cpu_usage", "memory_usage", "latency_p90"]:
        if col in df.columns:
            std = df[col].std()
            if std == 0 or np.isnan(std):
                logger.warning(f"Data sufficiency check failed: feature '{col}' has zero variance.")
                return False
                
    return True

def upload_model_to_s3(local_file: str, s3_key: str):
    """Tải tệp mô hình lên AWS S3."""
    try:
        s3 = boto3.client("s3")
        s3.upload_file(local_file, S3_BUCKET_NAME, s3_key)
        logger.info(f"Successfully uploaded model {local_file} to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
    except Exception as e:
        logger.error(f"Failed to upload model to S3: {e}. Model remains saved locally.")

def main():
    logger.info("======================================================================")
    logger.info(">>> START: EKS-NATIVE AUTOMATED ANOMALY TRAINING PIPELINE")
    logger.info("======================================================================")
    
    engine_dir = os.path.dirname(os.path.abspath(__file__))
    local_model_dir = os.path.join(engine_dir, "models")
    os.makedirs(local_model_dir, exist_ok=True)
    
    golden_path = os.path.join(engine_dir, "data", "golden_samples.csv")
    df_golden = None
    if os.path.exists(golden_path):
        logger.info(f"Loaded Golden Cache samples from: {golden_path}")
        df_golden = pd.read_csv(golden_path)
        df_golden["timestamp"] = pd.to_datetime(df_golden["timestamp"])
    else:
        logger.warning(f"Golden Cache file NOT found at {golden_path}. Training without Golden anchors.")
        
    for service in SERVICES:
        logger.info(f"--- Training process for service: {service} ---")
        
        # 1. Thu thập dữ liệu rolling (Prometheus hoặc fallback)
        df_raw = fetch_metrics_from_prometheus(service, duration_days=7)
        if df_raw.empty:
            df_raw = generate_fallback_synthetic_data(service, duration_days=14)
            
        # 2. Kiểm tra chất lượng dữ liệu
        if not check_data_sufficiency(df_raw):
            logger.error(f"Data checks failed for {service}. Skipping model training.")
            continue
            
        # 3. Phái sinh đặc trưng cho tập rolling
        df_features = feature_engineering(df_raw)
        
        # 4. Gộp với mẫu Golden Cache bình thường (label == 1) nếu có
        if df_golden is not None:
            df_gold_svc = df_golden[df_golden["service"] == service]
            df_gold_normal = df_gold_svc[df_gold_svc["label"] == 1]
            df_gold_normal_features = feature_engineering(df_gold_normal)
            df_combined_train = pd.concat([df_features, df_gold_normal_features], ignore_index=True)
        else:
            df_combined_train = df_features
            
        X_train = df_combined_train[FEATURE_COLS]
        
        # 5. Huấn luyện mô hình Isolation Forest (contamination=0.03)
        logger.info(f"Training Isolation Forest model for {service}...")
        model = IsolationForest(
            n_estimators=200,
            contamination=0.03,
            max_features=0.8,
            random_state=42,
            n_jobs=-1
        )
        model.fit(X_train)
        
        # 6. Lưu trữ mô hình cục bộ
        local_path = os.path.join(local_model_dir, f"{service}_iforest.joblib")
        joblib.dump(model, local_path)
        logger.info(f"Saved local model to: {local_path}")
        
        # 7. Upload mô hình lên S3
        s3_key = f"current/{service}_iforest.joblib"
        upload_model_to_s3(local_path, s3_key)
        
    logger.info("EKS Anomaly Training Pipeline successfully completed.")

if __name__ == "__main__":
    main()
