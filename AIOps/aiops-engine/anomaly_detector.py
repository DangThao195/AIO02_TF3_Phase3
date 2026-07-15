import os
import requests
import time
import logging
import joblib
import boto3
import pandas as pd
import numpy as np
from datetime import datetime
from config import PROMETHEUS_URL, S3_BUCKET_NAME

logger = logging.getLogger("AIOpsEngine.AnomalyDetector")

class AnomalyDetector:
    def __init__(self):
        self.prometheus_url = PROMETHEUS_URL
        self.s3_bucket = S3_BUCKET_NAME
        self.models_dir = os.path.join(os.path.dirname(__file__), "models")
        os.makedirs(self.models_dir, exist_ok=True)
        self.iforest_models = {}
        self.models = self.iforest_models # Backwards compatibility
        
        # Nạp các model Isolation Forest từ S3/local cache
        self._load_models_from_s3()

    def download_models_from_s3(self):
        """Tải các model Isolation Forest từ S3 về models/ nếu có."""
        try:
            # Chỉ chạy khi có biến môi trường AWS
            if not os.getenv("AWS_ACCESS_KEY_ID"):
                logger.info("No AWS credentials found. Skipping S3 model download.")
                return

            s3 = boto3.client("s3")
            logger.info(f"Listing models in S3 bucket: {self.s3_bucket}...")
            response = s3.list_objects_v2(Bucket=self.s3_bucket, Prefix="current/")
            
            if "Contents" not in response:
                logger.info("No models found in S3 bucket.")
                return

            for obj in response["Contents"]:
                key = obj["Key"]
                if key.endswith("_iforest.joblib"):
                    filename = os.path.basename(key)
                    local_path = os.path.join(self.models_dir, filename)
                    logger.info(f"Downloading model {key} from S3 to {local_path}...")
                    s3.download_file(self.s3_bucket, key, local_path)
            logger.info("Successfully downloaded all latest models from S3.")
        except Exception as e:
            logger.warning(f"Could not download models from S3 (using local cache if available): {e}")

    def load_local_models(self):
        """Nạp các mô hình joblib hiện có vào RAM."""
        try:
            if not os.path.exists(self.models_dir):
                return
            for file in os.listdir(self.models_dir):
                if file.endswith("_iforest.joblib"):
                    service_name = file.replace("_iforest.joblib", "")
                    model_path = os.path.join(self.models_dir, file)
                    self.models[service_name] = joblib.load(model_path)
            logger.info(f"Loaded {len(self.models)} Isolation Forest models into memory: {list(self.models.keys())}")
        except Exception as e:
            logger.error(f"Error loading local models: {e}")

    def query_prometheus(self, query: str) -> dict:
        """Helper to run a PromQL query."""
        try:
            response = requests.get(f"{self.prometheus_url}/api/v1/query", params={"query": query}, timeout=10)
            if response.status_code == 200:
                return response.json()
            logger.error(f"Prometheus query failed with code {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error querying Prometheus: {str(e)}")
        return {}

    def query_prometheus_range(self, query: str, start_time: float, end_time: float, step: str = "5m") -> list:
        """Gọi API query_range của Prometheus."""
        try:
            url = f"{self.prometheus_url}/api/v1/query_range"
            params = {
                "query": query,
                "start": int(start_time),
                "end": int(end_time),
                "step": step
            }
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                if res_json.get("status") == "success":
                    return res_json.get("data", {}).get("result", [])
        except Exception as e:
            logger.warning(f"Error querying Prometheus range: {e}")
        return []

    def parse_range_result(self, result_list: list) -> pd.Series:
        if not result_list:
            return pd.Series(dtype=float)
        values = result_list[0].get("values", [])
        timestamps = [datetime.fromtimestamp(float(ts)) for ts, _ in values]
        data = [float(val) for _, val in values]
        return pd.Series(data=data, index=timestamps)

    def extract_features_realtime(self, service: str) -> pd.DataFrame:
        """Thu thập dữ liệu 1 giờ gần nhất của service để sinh 13 features."""
        end_time = time.time()
        start_time = end_time - 3600  # 1 giờ trước
        
        # PromQL
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
        for name, q in queries.items():
            raw_res = self.query_prometheus_range(q, start_time, end_time, step="5m")
            series = self.parse_range_result(raw_res)
            if not series.empty:
                data_dict[name] = series
                
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
        
        # Tính toán features y hệt training script
        df["error_ratio"] = df["error_rate"] / (df["rps"] + 1e-5)
        df["client_error_ratio"] = df["client_error_rate"] / (df["rps"] + 1e-5)
        df["rolling_median_1h"] = df["latency_p90"].rolling(window=12, min_periods=1).median()
        df["latency_deviation"] = df["latency_p90"] / (df["rolling_median_1h"] + 1e-5)
        df["rps_delta"] = df["rps"] - df["rps"].shift(1).fillna(0)
        df["cpu_per_rps"] = df["cpu_usage"] / (df["rps"] + 1e-5)
        df["memory_growth"] = df["memory_usage"] - df["memory_usage"].shift(6).fillna(0)
        df["kafka_lag_growth"] = df["kafka_lag"] - df["kafka_lag"].shift(1).fillna(0)
        
        df["hour_of_day"] = df["timestamp"].dt.hour
        df["day_of_week"] = df["timestamp"].dt.weekday
        df["is_business_hours"] = ((df["hour_of_day"] >= 8) & (df["hour_of_day"] <= 18) & (df["day_of_week"] < 5)).astype(int)
        
        df["rolling_median_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).median()
        df["is_high_traffic_period"] = ((df["rps"] > 100) & (df["rps"] > 1.5 * df["rolling_median_rps_1h"])).astype(int)
        
        df = df.fillna(0)
        return df

    def check_service_anomaly(self, service: str) -> dict:
        """
        Dự đoán trạng thái bất thường của Service sử dụng Isolation Forest.
        Trả về dictionary kết quả.
        """
        # 1. Chế độ giả lập Sandbox
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            from config import SIMULATION_STATE
            scenario = SIMULATION_STATE["scenario"]
            remediated = SIMULATION_STATE["remediated"]
            if scenario in ["inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew", "ml_proactive"] and not remediated:
                # Nếu là ml_proactive, chỉ báo lỗi cho frontend để chạy chẩn đoán sớm
                if scenario == "ml_proactive" and service != "frontend":
                    return {
                        "prediction": 1,
                        "score": 0.15,
                        "confidence": "HIGH",
                        "fallback": False
                    }
                logger.info(f"[SIMULATION] Anomaly check for {service}: anomalous (score=-0.35) due to scenario {scenario}")
                return {
                    "prediction": -1,
                    "score": -0.35,
                    "confidence": "HIGH",
                    "fallback": False
                }
            return {
                "prediction": 1,
                "score": 0.15,
                "confidence": "HIGH",
                "fallback": False
            }

        # 2. Check xem có model đã nạp không
        if service not in self.models:
            logger.warning(f"No Isolation Forest model loaded for {service}. Falling back to Z-Score.")
            # Tính Z-Score CPU để làm fallback
            cpu_z = self.check_infra_z_score(f'sum(rate(container_cpu_usage_seconds_total{{container="{service}"}}[5m]))')
            prediction = -1 if abs(cpu_z) >= 3.0 else 1
            return {
                "prediction": prediction,
                "score": -float(abs(cpu_z)) / 3.0,
                "confidence": "MEDIUM" if prediction == -1 else "HIGH",
                "fallback": True
            }

        # 3. Trích xuất đặc trưng thời gian thực
        df_features = self.extract_features_realtime(service)
        if df_features.empty or len(df_features) < 1:
            logger.warning(f"Insufficient telemetry data context for {service} features. Falling back to Z-Score.")
            cpu_z = self.check_infra_z_score(f'sum(rate(container_cpu_usage_seconds_total{{container="{service}"}}[5m]))')
            prediction = -1 if abs(cpu_z) >= 3.0 else 1
            return {
                "prediction": prediction,
                "score": -float(abs(cpu_z)) / 3.0,
                "confidence": "MEDIUM",
                "fallback": True
            }

        # Lấy vector hàng cuối cùng (thời điểm hiện tại)
        feature_cols = [
            "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
            "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
            "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
        ]
        X_t = df_features[feature_cols].iloc[-1].values.reshape(1, -1)
        
        # 4. Dự đoán bằng Isolation Forest
        model = self.models[service]
        prediction = int(model.predict(X_t)[0])  # 1 hoặc -1
        score = float(model.decision_function(X_t)[0])  # Càng âm càng bất thường
        
        # Xác định mức độ tin cậy
        if score < -0.3:
            confidence = "HIGH"
        elif score < -0.1:
            confidence = "MEDIUM"
        else:
            confidence = "borderline"
            
        logger.info(f"Anomaly check for {service} - Predict: {prediction}, AnomalyScore: {score:.4f}, Confidence: {confidence}")
        return {
            "prediction": prediction,
            "score": score,
            "confidence": confidence,
            "fallback": False
        }

    def check_slo_burn_rate(self) -> bool:
        """
        Lớp 1 - SLO Burn-rate Monitor
        Kiểm tra tốc độ tiêu thụ ngân sách lỗi (Error Budget Burn Rate) có vượt ngưỡng K=14.4
        trên cả 2 cửa sổ 5 phút và 1 giờ cho tất cả các dịch vụ (traces_span_metrics).
        """
        import os
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            from config import SIMULATION_STATE
            scenario = SIMULATION_STATE["scenario"]
            remediated = SIMULATION_STATE["remediated"]
            if scenario in ["inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew"] and not remediated:
                logger.info(f"[SIMULATION] SLO Burn Rate Check: anomalous (burn rate = 18.5) due to scenario {scenario}")
                return True
            logger.info("[SIMULATION] SLO Burn Rate Check: stable")
            return False

        # Query cho cửa sổ 5m và 1h gom tất cả dịch vụ qua Span Metrics
        query_5m = (
            "(sum(rate(traces_span_metrics_calls_total{span_kind=\"SPAN_KIND_SERVER\", status_code=\"STATUS_CODE_ERROR\"}[5m])) by (service_name) / "
            "sum(rate(traces_span_metrics_calls_total{span_kind=\"SPAN_KIND_SERVER\"}[5m])) by (service_name) * 720) or "
            "(sum(rate(traces_span_metrics_calls_total{span_kind=\"SPAN_KIND_SERVER\"}[5m])) by (service_name) * 0)"
        )
        query_1h = (
            "(sum(rate(traces_span_metrics_calls_total{span_kind=\"SPAN_KIND_SERVER\", status_code=\"STATUS_CODE_ERROR\"}[1h])) by (service_name) / "
            "sum(rate(traces_span_metrics_calls_total{span_kind=\"SPAN_KIND_SERVER\"}[1h])) by (service_name) * 720) or "
            "(sum(rate(traces_span_metrics_calls_total{span_kind=\"SPAN_KIND_SERVER\"}[1h])) by (service_name) * 0)"
        )

        res_5m = self.query_prometheus(query_5m)
        res_1h = self.query_prometheus(query_1h)

        burn_rates_5m = self.parse_multi_service_burn_rates(res_5m)
        burn_rates_1h = self.parse_multi_service_burn_rates(res_1h)

        violated_services = []
        for service, br_5m in burn_rates_5m.items():
            br_1h = burn_rates_1h.get(service, 0.0)
            if br_5m >= 14.4 and br_1h >= 14.4:
                violated_services.append((service, br_5m, br_1h))

        if violated_services:
            for service, br_5m, br_1h in violated_services:
                logger.warning(f"SLO Burn Rate BREACHED on service: {service} (5m: {br_5m:.2f}, 1h: {br_1h:.2f})")
            return True

        max_5m_svc = max(burn_rates_5m.items(), key=lambda x: x[1], default=("None", 0.0))
        max_1h_svc = max(burn_rates_1h.items(), key=lambda x: x[1], default=("None", 0.0))
        logger.info(f"SLO Burn Rate Check (Max) - 5m: {max_5m_svc[1]:.2f} ({max_5m_svc[0]}), 1h: {max_1h_svc[1]:.2f} ({max_1h_svc[0]})")
        return False

    def check_infra_z_score(self, metric_name: str, window_days: int = 1) -> float:
        """
        Lớp 2 - ML-based Saturation & Lag Monitor
        Tính toán chỉ số Z-Score dựa trên baseline cửa sổ trượt window_days (mặc định 1 ngày)
        để phát hiện bất thường sớm của hệ thống (như CPU, Memory, Kafka lag).
        """
        import os
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            from config import SIMULATION_STATE
            scenario = SIMULATION_STATE["scenario"]
            remediated = SIMULATION_STATE["remediated"]
            if scenario in ["inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew"] and not remediated:
                logger.info(f"[SIMULATION] Z-Score for {metric_name}: anomalous (Z-Score = 5.0) due to scenario {scenario}")
                return 5.0
            logger.info(f"[SIMULATION] Z-Score for {metric_name}: healthy (Z-Score = 0.0)")
            return 0.0

        if "(" in metric_name or "}" in metric_name:
            query_mean = f"avg_over_time(({metric_name})[{window_days}d:5m])"
            query_stddev = f"stddev_over_time(({metric_name})[{window_days}d:5m])"
        else:
            query_mean = f"avg_over_time({metric_name}[{window_days}d])"
            query_stddev = f"stddev_over_time({metric_name}[{window_days}d])"
        query_current = f"{metric_name}"
        
        mean_res = self.query_prometheus(query_mean)
        stddev_res = self.query_prometheus(query_stddev)
        current_res = self.query_prometheus(query_current)
        
        if (not mean_res.get("data", {}).get("result") or 
            not stddev_res.get("data", {}).get("result") or 
            not current_res.get("data", {}).get("result")):
            logger.warning(f"No metric data returned from Prometheus for {metric_name}. Treating as anomalous (Z-Score = 999.0)")
            return 999.0
            
        mean = self.parse_query_value(mean_res)
        stddev = self.parse_query_value(stddev_res)
        current = self.parse_query_value(current_res)
        
        if stddev == 0:
            if current == 0:
                return 0.0
            logger.warning(f"Zero standard deviation in baseline history but current value is non-zero ({current:.2f}) for {metric_name}. Flagging anomaly (Z = 999.0).")
            return 999.0
            
        z_score = (current - mean) / stddev
        logger.info(f"Z-Score for {metric_name} - Current: {current:.2f}, Mean: {mean:.2f}, Stddev: {stddev:.2f}, Z: {z_score:.2f}")
        return z_score

    def parse_query_value(self, response: dict) -> float:
        try:
            if response.get("status") == "success":
                results = response.get("data", {}).get("result", [])
                if results:
                    return float(results[0]["value"][1])
        except (IndexError, KeyError, ValueError, TypeError):
            pass
        return 0.0

    def parse_multi_service_burn_rates(self, response: dict) -> dict:
        """Trích xuất map {service_name: burn_rate} từ response Prometheus."""
        burn_rates = {}
        results = response.get("data", {}).get("result", [])
        for r in results:
            service = r.get("metric", {}).get("service_name")
            if service:
                try:
                    val = float(r.get("value", [0, "0"])[1])
                    burn_rates[service] = val
                except Exception:
                    pass
        return burn_rates

    def _load_models_from_s3(self):
        """Tải và nạp các mô hình Isolation Forest từ S3 vào RAM (Sử dụng Manifest)."""
        import json
        manifest_loaded = False
        
        try:
            if os.getenv("AWS_ACCESS_KEY_ID"):
                s3 = boto3.client("s3")
                manifest_local_path = os.path.join(self.models_dir, "active_manifest.json")
                
                # 1. Thử tải active_manifest.json
                logger.info("Attempting to download active_manifest.json from S3...")
                try:
                    s3.download_file(self.s3_bucket, "active_manifest.json", manifest_local_path)
                    with open(manifest_local_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    
                    # Kiểm định manifest chất lượng
                    if manifest.get("validation_passed", False):
                        logger.info(f"Manifest loaded successfully: version={manifest.get('version')}, F1={manifest.get('f1_score_average')}")
                        for service_name, s3_path in manifest.get("model_paths", {}).items():
                            s3_key = s3_path.replace("models/", "")
                            local_path = os.path.join(self.models_dir, f"{service_name}_iforest.joblib")
                            logger.info(f"Downloading model for {service_name} from s3://{self.s3_bucket}/{s3_key}...")
                            s3.download_file(self.s3_bucket, s3_key, local_path)
                        manifest_loaded = True
                    else:
                        logger.warning("Manifest validation_passed is False. Model quality did not pass guardrail. Falling back to current/.")
                except Exception as e:
                    logger.warning(f"Could not download or parse manifest from S3: {e}. Falling back to current/.")
                
                # 2. Fallback nếu manifest thất bại
                if not manifest_loaded:
                    logger.info("Running fallback: downloading latest models from current/ folder on S3...")
                    self.download_models_from_s3()
            else:
                logger.info("No AWS credentials found. Skipping S3 download (using local cache if available).")
                
            # 3. Nạp tất cả file model joblib cục bộ vào RAM
            if os.path.exists(self.models_dir):
                # Clear RAM cache trước khi nạp lại (dành cho hot reload)
                self.iforest_models.clear()
                for file in os.listdir(self.models_dir):
                    if file.endswith("_iforest.joblib"):
                        service_name = file.replace("_iforest.joblib", "")
                        model_path = os.path.join(self.models_dir, file)
                        self.iforest_models[service_name] = joblib.load(model_path)
                logger.info(f"Loaded {len(self.iforest_models)} Isolation Forest models into memory: {list(self.iforest_models.keys())}")
        except Exception as e:
            logger.error(f"Error loading models in _load_models_from_s3: {e}")

    def check_infra_anomaly(self, service: str, features: list) -> bool:
        """Dùng IF nếu có model, fallback Z-Score nếu không."""
        # 1. Chế độ giả lập Sandbox
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            from config import SIMULATION_STATE
            scenario = SIMULATION_STATE["scenario"]
            remediated = SIMULATION_STATE["remediated"]
            if scenario in ["inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew", "ml_proactive"] and not remediated:
                if scenario == "ml_proactive" and service != "frontend":
                    return False
                logger.info(f"[SIMULATION] Anomaly check (IF) for {service}: anomalous due to scenario {scenario}")
                return True
            return False

        if service in self.iforest_models:
            try:
                feature_cols = [
                    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
                    "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
                    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
                ]
                df_t = pd.DataFrame([features], columns=feature_cols)
                prediction = int(self.iforest_models[service].predict(df_t)[0])
                logger.info(f"IF prediction for {service}: {prediction} (1: Normal, -1: Anomaly)")
                return prediction == -1
            except Exception as e:
                logger.error(f"Failed to run IF inference for {service}: {e}. Falling back to Z-Score.")
                
        # Fallback Z-Score nếu không có model
        try:
            cpu_z = self.check_infra_z_score(f'sum(rate(container_cpu_usage_seconds_total{{container="{service}"}}[5m]))')
            return abs(cpu_z) >= 3.0
        except Exception as e:
            logger.error(f"Failed to run Z-Score fallback for {service}: {e}")
            return False
