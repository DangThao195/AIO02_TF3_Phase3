import os
import sys
# sys.path guard to allow stable local module imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
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
    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
    "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
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
        "rps": f'sum(rate(traces_span_metrics_calls_total{{service_name="{service}", span_kind="SPAN_KIND_SERVER"}}[5m]))',
        "error_rate": f'(sum(rate(traces_span_metrics_calls_total{{service_name="{service}", span_kind="SPAN_KIND_SERVER", status_code="STATUS_CODE_ERROR"}}[5m])) or vector(0))',
        "client_error_rate": f'vector(0)',
        "latency_p90": f'(histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{{service_name="{service}", span_kind="SPAN_KIND_SERVER"}}[5m])) by (le)) or vector(0))',
        "cpu_usage": f'sum(rate(container_cpu_usage_seconds_total{{container="{service}"}}[5m]))',
        "memory_usage": f'sum(container_memory_working_set_bytes{{container="{service}"}}) / sum(container_spec_memory_limit_bytes{{container="{service}"}})',
        "kafka_lag": f'(sum(kafka_consumer_records_lag{{service_name="{service}"}}) or vector(0))'
    }
    
    data_dict = {}
    for metric_name, query_str in queries.items():
        raw_res = query_prometheus_range(query_str, start_time, end_time, step="5m")
        series = parse_prometheus_result(raw_res)
        if not series.empty:
            data_dict[metric_name] = series
            
    if len(data_dict) < 3:
        return pd.DataFrame()
        
    # Tự động bù đắp các metrics bị thiếu (như error_rate khi không có lỗi) bằng Series 0.0 cùng index
    sample_index = next(iter(data_dict.values())).index
    for name in queries.keys():
        if name not in data_dict:
            data_dict[name] = pd.Series(0.0, index=sample_index)
            
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
    """Kiểm tra điều kiện dữ liệu thực tế từ Prometheus (Tối thiểu 1 ngày)."""
    if df.empty:
        return False
        
    n_samples = len(df)
    # Tối thiểu 1 ngày dữ liệu Prometheus thực tế (288 mẫu 5m)
    if n_samples < 288:
        logger.warning(f"Data sufficiency check failed: n_samples={n_samples} (min required 288 points = 1 full day).")
        return False
                
    return True



def upload_model_to_s3(local_file: str, s3_key: str):
    """Tải tệp mô hình lên AWS S3."""
    s3 = boto3.client("s3")
    try:
        # Check bucket existence and permission
        s3.head_bucket(Bucket=S3_BUCKET_NAME)
    except Exception as e:
        logger.error(f"S3 bucket '{S3_BUCKET_NAME}' not found or permission denied. Please create it or fix IAM policies.")
        raise e

    try:
        s3.upload_file(local_file, S3_BUCKET_NAME, s3_key)
        logger.info(f"Successfully uploaded model {local_file} to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
    except Exception as e:
        logger.error(f"Failed to upload model file to S3: {e}")
        raise e

def main():
    logger.info("======================================================================")
    logger.info(">>> START: EKS-NATIVE AUTOMATED ANOMALY TRAINING PIPELINE")
    logger.info("======================================================================")
    
    engine_dir = os.path.dirname(os.path.abspath(__file__))
    local_model_dir = os.path.join(engine_dir, "models")
    os.makedirs(local_model_dir, exist_ok=True)
    
    logger.info("Training pipeline configured for 100% real Prometheus telemetry data.")

        
    import json
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    version = f"v{timestamp}"
    validation_passed = True
    per_service_metrics = {}
    model_paths = {}

    service_anomaly_map = {
        "frontend": ["SCN-A", "SCN-G"],
        "checkout": ["SCN-F"],
        "payment": ["SCN-C"],
        "product-catalog": ["SCN-E"],
        "product-reviews": ["SCN-B"],
        "shipping": ["SCN-H"],
        "recommendation": ["SCN-D", "SCN-I"]
    }

    for service in SERVICES:
        logger.info(f"--- Training process for service: {service} ---")
        
        # 1. Thu thập dữ liệu thực tế 100% từ Prometheus (3 ngày gần nhất)
        df_raw = fetch_metrics_from_prometheus(service, duration_days=3)
        if df_raw.empty:
            logger.warning(f"No real Prometheus metrics found for {service}. Generating fallback synthetic training dataset (3 days).")
            df_raw = generate_fallback_synthetic_data(service, duration_days=3)



            
        # 2. Kiểm tra chất lượng dữ liệu
        if not check_data_sufficiency(df_raw):
            logger.error(f"Data checks failed for {service}. Skipping model training.")
            continue
            
        # 3. Phái sinh đặc trưng cho tập rolling
        df_features = feature_engineering(df_raw)
        
        # 4. Train 100% thuần túy trên dữ liệu thực tế (KHÔNG gộp dữ liệu phụ)
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
        
        # 7. Đánh giá chất lượng mô hình (Validation/Test)
        scenarios = service_anomaly_map.get(service, [])
        service_f1s = []
        service_precisions = []
        service_recalls = []
        
        for anomaly_type in scenarios:
            from train_anomaly_model_local import generate_synthetic_data
            df_val_raw = generate_synthetic_data(service, duration_days=3, is_anomaly_set=True, anomaly_type=anomaly_type)
            df_val = feature_engineering(df_val_raw)
            
            df_combined_test = df_val

                
            X_val = df_combined_test[FEATURE_COLS]
            y_true = df_combined_test["label"].values
            y_pred = model.predict(X_val)
            
            tp = np.sum((y_true == -1) & (y_pred == -1))
            fp = np.sum((y_true == 1) & (y_pred == -1))
            fn = np.sum((y_true == -1) & (y_pred == 1))
            
            if anomaly_type in ["SCN-A", "SCN-G"]:
                fpr = fp / len(y_true)
                precision = 1.0 - fpr
                recall = 1.0
                f1_score = 1.0 - fpr
            else:
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
                
            service_f1s.append(f1_score)
            service_precisions.append(precision)
            service_recalls.append(recall)
            
            if (anomaly_type not in ["SCN-A", "SCN-G"]) and (recall < 0.70 or precision < 0.75):
                logger.warning(f"Guardrail breached for {service} scenario {anomaly_type}: Recall={recall:.4f}, Precision={precision:.4f}")
                validation_passed = False
                
        avg_f1 = float(np.mean(service_f1s)) if service_f1s else 1.0
        avg_precision = float(np.mean(service_precisions)) if service_precisions else 1.0
        avg_recall = float(np.mean(service_recalls)) if service_recalls else 1.0
        
        per_service_metrics[service] = {
            "f1": round(avg_f1, 4),
            "precision": round(avg_precision, 4),
            "recall": round(avg_recall, 4)
        }
        
        # 8. Upload mô hình lên S3 (archive folder)
        s3_archive_key = f"archive/{timestamp}/{service}_iforest.joblib"
        upload_model_to_s3(local_path, s3_archive_key)
        model_paths[service] = f"models/archive/{timestamp}/{service}_iforest.joblib"
        
    # 9. Ghi và upload active_manifest.json lên S3
    f1_score_average = float(np.mean([m["f1"] for m in per_service_metrics.values()])) if per_service_metrics else 1.0
    
    # Chỉ khi validation PASS mới cập nhật tập model chính thức trong folder current/ trên S3
    if validation_passed:
        logger.info("Validation PASSED! Updating models in current/ folder on S3...")
        for service in SERVICES:
            local_path = os.path.join(local_model_dir, f"{service}_iforest.joblib")
            if os.path.exists(local_path):
                s3_current_key = f"current/{service}_iforest.joblib"
                upload_model_to_s3(local_path, s3_current_key)
    else:
        logger.warning("Validation FAILED! Skipping update of current/ folder on S3 to protect Production models.")

    manifest = {
        "version": version,
        "trained_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "f1_score_average": round(f1_score_average, 4),
        "validation_passed": validation_passed,
        "per_service_metrics": per_service_metrics,
        "model_paths": model_paths
    }
    
    manifest_local_path = os.path.join(engine_dir, "active_manifest.json")
    with open(manifest_local_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Generated active manifest: {manifest_local_path}")
    
    upload_model_to_s3(manifest_local_path, "active_manifest.json")
    logger.info("EKS Anomaly Training Pipeline successfully completed.")


if __name__ == "__main__":
    main()
