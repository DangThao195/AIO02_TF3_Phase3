import os
import logging
import pandas as pd
import numpy as np
import networkx as nx
from datetime import datetime

from anomaly_detector import AnomalyDetector
from alert_correlator import AlertCorrelator
from config import (
    ENABLE_3SIGMA_FIRST_DRIFT,
    THREE_SIGMA_THRESHOLD,
    THREE_SIGMA_MIN_TICKS,
    ENABLE_TOPOLOGY_DOWNSTREAM_PENALTY,
    DOWNSTREAM_PENALTY_FACTOR
)

logger = logging.getLogger("AIOpsEngine.EnhancedDetector")

class EnhancedAnomalyDetector(AnomalyDetector):
    """
    Enhanced Anomaly Detector featuring:
    1. 3-Sigma First-Drift Noise Filtering (triệt phá nhiễu spike 1-tick).
    2. Topology Downstream Symptom Penalty (trừ điểm triệu chứng hạ nguồn).
    """

    def __init__(self, correlator: AlertCorrelator = None):
        super().__init__()
        self.correlator = correlator or AlertCorrelator()
        logger.info("Initialized EnhancedAnomalyDetector with 3-Sigma First-Drift & Topology Symptom Penalty.")

    def apply_three_sigma_first_drift(self, service: str, df_features: pd.DataFrame) -> dict:
        """
        Phân tích chuỗi thời gian 1h của service, xác định thời điểm bắt đầu lệch đầu tiên (First-Drift)
        dựa trên ngưỡng 3-Sigma (μ +/- 3σ).
        """
        if df_features.empty or len(df_features) < 3:
            return {
                "is_drift_valid": True,
                "first_drift_timestamp": None,
                "first_drift_metric": None,
                "drift_consecutive_ticks": 0,
                "is_transient_spike": False
            }

        core_metrics = ["latency_p90", "error_rate", "cpu_usage", "kafka_lag"]
        drift_signals = []

        for metric in core_metrics:
            if metric not in df_features.columns:
                continue

            series = df_features[metric].values
            n = len(series)
            
            hist_series = series[:-1] if n > 3 else series
            mean = np.mean(hist_series)
            stddev = np.std(hist_series)
            
            if stddev < 1e-6:
                devs = np.abs(series - mean) > 1e-3
            else:
                z_scores = np.abs((series - mean) / stddev)
                devs = z_scores >= THREE_SIGMA_THRESHOLD

            if devs[-1]:
                consecutive = 0
                first_idx = n - 1
                for idx in range(n - 1, -1, -1):
                    if devs[idx]:
                        consecutive += 1
                        first_idx = idx
                    else:
                        break
                        
                first_ts_val = df_features["timestamp"].iloc[first_idx]
                first_ts_str = first_ts_val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(first_ts_val, (pd.Timestamp, datetime)) else str(first_ts_val)

                drift_signals.append({
                    "metric": metric,
                    "consecutive": consecutive,
                    "first_idx": first_idx,
                    "first_timestamp": first_ts_str
                })

        if not drift_signals:
            return {
                "is_drift_valid": True,
                "first_drift_timestamp": None,
                "first_drift_metric": None,
                "drift_consecutive_ticks": 0,
                "is_transient_spike": False
            }

        main_drift = max(drift_signals, key=lambda x: x["consecutive"])
        consecutive = main_drift["consecutive"]
        is_transient_spike = (consecutive < THREE_SIGMA_MIN_TICKS)
        is_drift_valid = not is_transient_spike

        return {
            "is_drift_valid": is_drift_valid,
            "first_drift_timestamp": main_drift["first_timestamp"],
            "first_drift_metric": main_drift["metric"],
            "drift_consecutive_ticks": consecutive,
            "is_transient_spike": is_transient_spike
        }

    def apply_topology_downstream_penalty(self, service: str, raw_score: float, active_anomalies_map: dict = None) -> float:
        """
        Kiểm tra nếu bất kỳ Upstream Dependency nào của service S đang bị Anomaly,
        giảm bớt score bất thường của S (Penalize) vì S là triệu chứng hạ nguồn (Downstream Symptom).
        """
        if not ENABLE_TOPOLOGY_DOWNSTREAM_PENALTY or not active_anomalies_map:
            return raw_score

        try:
            graph = self.correlator.nx_graph
            if service in graph:
                # Upstream dependencies of S in u -> v ("u calls v") are successors and descendants
                upstream_nodes = set(graph.successors(service)).union(nx.descendants(graph, service))
                
                # Also include predecessors in case graph is stored as v -> u ("v called by u")
                upstream_nodes.update(graph.predecessors(service))
                upstream_nodes.update(nx.ancestors(graph, service))

                for parent in upstream_nodes:
                    if parent != service and parent in active_anomalies_map:
                        parent_state = active_anomalies_map[parent]
                        if isinstance(parent_state, dict) and parent_state.get("prediction") == -1:
                            logger.info(f"[TOPOLOGY_PENALTY] Service '{service}' is downstream of broken upstream '{parent}'. Applying score penalty factor ({DOWNSTREAM_PENALTY_FACTOR}).")
                            penalized_score = raw_score * DOWNSTREAM_PENALTY_FACTOR
                            return penalized_score
        except Exception as e:
            logger.warning(f"Error applying topology downstream penalty for {service}: {e}")

        return raw_score

    def check_service_anomaly_enhanced(self, service: str, active_anomalies_map: dict = None) -> dict:
        """
        Quy trình chẩn đoán nâng cao:
          1. Isolation Forest Inference
          2. 3-Sigma First-Drift Filtering (Loại bỏ Spike 1-tick)
          3. Topology Downstream Symptom Penalty (Trừ điểm triệu chứng hạ nguồn)
        """
        res = super().check_service_anomaly(service)
        
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            return res

        # 1. Áp dụng 3-Sigma First-Drift Filter
        if ENABLE_3SIGMA_FIRST_DRIFT and res.get("prediction") == -1:
            df_features = self.extract_features_realtime(service)
            drift_info = self.apply_three_sigma_first_drift(service, df_features)
            
            res["first_drift_timestamp"] = drift_info.get("first_drift_timestamp")
            res["first_drift_metric"] = drift_info.get("first_drift_metric")
            res["drift_consecutive_ticks"] = drift_info.get("drift_consecutive_ticks")
            
            if drift_info.get("is_transient_spike"):
                logger.info(f"[3SIGMA_FILTER] Overriding false positive for {service}: Transient 1-tick spike detected on {drift_info.get('first_drift_metric')}. Suppressing anomaly.")
                res["prediction"] = 1
                res["score"] = 0.05
                res["confidence"] = "SUPPRESSED_TRANSIENT_SPIKE"
                res["suppressed"] = True
                return res

        # 2. Áp dụng Topology Downstream Penalty
        if ENABLE_TOPOLOGY_DOWNSTREAM_PENALTY and res.get("prediction") == -1 and active_anomalies_map:
            raw_score = res.get("score", -0.3)
            penalized_score = self.apply_topology_downstream_penalty(service, raw_score, active_anomalies_map)
            res["score"] = penalized_score
            
            if penalized_score > -0.1:
                res["prediction"] = 1
                res["confidence"] = "SUPPRESSED_DOWNSTREAM_SYMPTOM"
                res["is_downstream_symptom"] = True
            elif penalized_score > -0.25:
                res["confidence"] = "MEDIUM_DOWNSTREAM_SYMPTOM"
                res["is_downstream_symptom"] = True

        return res
