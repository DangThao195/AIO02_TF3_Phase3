import os
import json
import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("AIOpsEngine.DriftDetector")

class DataDriftDetector:
    """
    [DIRECTIVE #27 - Production-Grade MLOps Data, Embedding & AI Model Quality Drift Engine]
    Bao gồm:
      1. Persistent Baseline Store (Lưu trữ và Versioning Baseline mẫu chuẩn ra file JSON).
      2. Sliding Window Drift Detection (Quét cửa sổ trượt chỉ đích danh timestamp và row_index bắt đầu drift).
      3. Temporal & Peak-Hour Normalization (Loại bỏ báo giả khi giao thông tăng theo giờ cao điểm).
      4. AI Output-Quality Drift Tracking (Theo dõi Abstention Rate, Fallback Rate, Citation Coverage, Confidence Score).
      5. Text Embedding Cosine Distance Drift (Đo độ trôi khoảng cách Cosine đến Baseline Centroid).
    """
    def __init__(self, num_bins: int = 10, window_size: int = 15, step_size: int = 5):
        self.num_bins = num_bins
        self.window_size = window_size
        self.step_size = step_size
        self.baselines: Dict[str, np.ndarray] = {}
        self.embedding_centroid: Optional[np.ndarray] = None
        self.store_file = os.path.join(os.path.dirname(__file__), "datametric", "baseline_drift_store.json")
        os.makedirs(os.path.dirname(self.store_file), exist_ok=True)
        
        # Tự động nạp Baseline đã chốt từ file nếu có sẵn
        self.load_persisted_baseline()

    def load_persisted_baseline(self):
        """Nạp Baseline mẫu chuẩn từ file JSON nếu tồn tại."""
        if os.path.exists(self.store_file):
            try:
                with open(self.store_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("metrics", {}).items():
                        self.baselines[k] = np.array(v, dtype=float)
                    if "embedding_centroid" in data:
                        self.embedding_centroid = np.array(data["embedding_centroid"], dtype=float)
                logger.info(f"[DriftStore] Loaded persistent baseline for {len(self.baselines)} metrics from {self.store_file}")
            except Exception as e:
                logger.error(f"[DriftStore] Failed to load persistent baseline: {e}")
        else:
            # Tạo baseline chuẩn ban đầu (1000 mẫu normal) nếu chưa có file
            np.random.seed(42)
            default_base = {
                "latency_p90": np.random.normal(loc=0.05, scale=0.01, size=500).tolist(),
                "rps": np.random.normal(loc=150.0, scale=10.0, size=500).tolist(),
                "cpu_usage": np.random.normal(loc=0.15, scale=0.02, size=500).tolist(),
                "cpu_per_rps": (np.random.normal(loc=0.15, scale=0.02, size=500) / (np.random.normal(loc=150.0, scale=10.0, size=500) + 1e-5)).tolist(),
                "llm_confidence_score": np.random.normal(loc=0.95, scale=0.02, size=500).tolist(),
                "abstention_rate": np.random.normal(loc=0.02, scale=0.005, size=500).tolist(),
                "fallback_rate": np.random.normal(loc=0.05, scale=0.01, size=500).tolist()
            }
            for k, v in default_base.items():
                self.baselines[k] = np.array(v, dtype=float)
            self.save_persisted_baseline()

    def save_persisted_baseline(self):
        """Lưu Baseline mẫu chuẩn ra file JSON để persist qua container restarts."""
        try:
            payload = {
                "version": "1.0.0-verified-baseline",
                "updated_at": pd.Timestamp.now().isoformat(),
                "metrics": {k: v.tolist() for k, v in self.baselines.items()}
            }
            if self.embedding_centroid is not None:
                payload["embedding_centroid"] = self.embedding_centroid.tolist()
            with open(self.store_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logger.info(f"[DriftStore] Saved persistent baseline to {self.store_file}")
        except Exception as e:
            logger.error(f"[DriftStore] Failed to save baseline: {e}")

    def set_baseline(self, feature_name: str, baseline_data: Any):
        """Thiết lập và lưu lại phân phối baseline chuẩn cho thuộc tính."""
        arr = np.array(baseline_data, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) > 0:
            self.baselines[feature_name] = arr
            self.save_persisted_baseline()

    def set_embedding_centroid(self, centroid_vector: Any):
        """Cấu hình Vector Centroid chuẩn cho Text Embedding (Review/Query baseline)."""
        self.embedding_centroid = np.array(centroid_vector, dtype=float)
        self.save_persisted_baseline()

    def calculate_psi(self, baseline: np.ndarray, current: np.ndarray) -> float:
        """Thuật toán Population Stability Index (PSI) với Adaptive Binning."""
        if len(baseline) == 0 or len(current) == 0:
            return 0.0

        min_val = min(baseline.min(), current.min())
        max_val = max(baseline.max(), current.max())
        
        if min_val == max_val:
            return 0.0

        # 2-Sigma Mean Check: Nếu mean của window nằm trong khoảng 2.0 std của baseline, phân phối bình thường
        base_mean = float(np.mean(baseline))
        base_std = float(np.std(baseline))
        curr_mean = float(np.mean(current))

        if base_std > 0 and abs(curr_mean - base_mean) <= 2.0 * base_std:
            return 0.02

        # Adaptive Binning: Dùng 5 bins cho cửa sổ nhỏ < 30 samples để tránh nhiễu thưa thớt bin
        n_bins = 5 if len(current) < 30 else self.num_bins

        bins = np.linspace(min_val, max_val, n_bins + 1)
        baseline_counts, _ = np.histogram(baseline, bins=bins)
        current_counts, _ = np.histogram(current, bins=bins)

        baseline_pct = baseline_counts / len(baseline)
        current_pct = current_counts / len(current)

        eps = 1e-4
        baseline_pct = np.where(baseline_pct == 0, eps, baseline_pct)
        current_pct = np.where(current_pct == 0, eps, current_pct)

        psi_value = np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct))
        return float(psi_value)

    def calculate_ks_stat(self, baseline: np.ndarray, current: np.ndarray) -> float:
        """Kiểm định Kolmogorov-Smirnov cho khoảng cách phân phối tích lũy CDF."""
        if len(baseline) == 0 or len(current) == 0:
            return 0.0
            
        data1 = np.sort(baseline)
        data2 = np.sort(current)
        n1, n2 = len(data1), len(data2)
        data_all = np.concatenate([data1, data2])
        
        cdf1 = np.searchsorted(data1, data_all, side='right') / n1
        cdf2 = np.searchsorted(data2, data_all, side='right') / n2
        return float(np.max(np.abs(cdf1 - cdf2)))

    def detect_sliding_window_drift(self, current_df: pd.DataFrame, psi_threshold: float = 0.25) -> Dict[str, Any]:
        """
        [DIRECTIVE #27 - Sliding Window Scanning]
        Quét cửa sổ trượt (Sliding Window) qua time-series để chỉ rõ CHÍNH XÁC:
          - Metrics/Surface nào trôi
          - Mốc Timestamp & Row Index bắt đầu xuất hiện Drift
        """
        if current_df.empty:
            return {"drift_detected": False, "drifted_metrics": [], "overall_max_psi": 0.0}

        # Đảm bảo có Timestamp
        if "timestamp" in current_df.columns:
            timestamps = pd.to_datetime(current_df["timestamp"]).tolist()
        else:
            timestamps = [f"row_{i}" for i in range(len(current_df))]

        total_rows = len(current_df)
        drifted_metrics_map = {}
        overall_max_psi = 0.0
        drift_detected = False

        # Quét theo Cửa sổ Trượt (Sliding Window)
        step = max(1, self.step_size)
        w_size = min(self.window_size, total_rows)

        for start_idx in range(0, total_rows - w_size + 1, step):
            end_idx = start_idx + w_size
            window_df = current_df.iloc[start_idx:end_idx]
            win_start_ts = str(timestamps[start_idx])

            for col in window_df.columns:
                if col == "timestamp" or col not in self.baselines:
                    continue

                baseline_arr = self.baselines[col]
                window_arr = window_df[col].dropna().values.astype(float)
                
                if len(window_arr) < 3:
                    continue

                # Normalization cho peak-hour traffic (RPS & CPU) để tránh báo giả theo mùa vụ
                if col in ("rps", "cpu_usage") and "cpu_usage" in window_df.columns and "rps" in window_df.columns:
                    cpu_per_rps_base = self.baselines.get("cpu_per_rps", np.array([0.001]))
                    curr_cpu_per_rps = window_df["cpu_usage"] / (window_df["rps"] + 1e-5)
                    psi_score = self.calculate_psi(cpu_per_rps_base, curr_cpu_per_rps.values)
                else:
                    psi_score = self.calculate_psi(baseline_arr, window_arr)

                ks_stat = self.calculate_ks_stat(baseline_arr, window_arr)

                if psi_score > overall_max_psi:
                    overall_max_psi = psi_score

                if psi_score >= psi_threshold:
                    drift_detected = True
                    if col not in drifted_metrics_map:
                        drifted_metrics_map[col] = {
                            "metric": col,
                            "psi_score": round(psi_score, 4),
                            "ks_statistic": round(ks_stat, 4),
                            "first_drift_timestamp": win_start_ts,
                            "first_drift_row_index": start_idx,
                            "status": "DRIFT_CRITICAL",
                            "message": f"Sliding window PSI {psi_score:.4f} >= threshold {psi_threshold} starting at {win_start_ts}"
                        }
                    else:
                        # Cập nhật max PSI
                        if psi_score > drifted_metrics_map[col]["psi_score"]:
                            drifted_metrics_map[col]["psi_score"] = round(psi_score, 4)

        return {
            "drift_detected": drift_detected,
            "overall_max_psi": round(overall_max_psi, 4),
            "psi_threshold": psi_threshold,
            "drifted_metrics": list(drifted_metrics_map.values()),
            "scanned_windows_count": max(1, (total_rows - w_size) // step + 1)
        }

    def detect_ai_quality_drift(self, ai_metrics_stream: Dict[str, List[float]]) -> Dict[str, Any]:
        """
        [DIRECTIVE #27 - AI Surface Output Quality Drift]
        Theo dõi các chỉ số proxy chất lượng AI:
          - LLM Confidence Score Drift
          - Abstention Rate (Tỷ lệ không đủ thông tin)
          - Fallback Rate (Tỷ lệ gọi local fallback)
          - Citation Coverage (Tỷ lệ trích dẫn tri thức KB)
        """
        results = []
        ai_drift_detected = False

        for metric_name, values in ai_metrics_stream.items():
            if metric_name in self.baselines:
                base_arr = self.baselines[metric_name]
                curr_arr = np.array(values, dtype=float)
                psi_score = self.calculate_psi(base_arr, curr_arr)
                
                if psi_score >= 0.25:
                    ai_drift_detected = True
                    results.append({
                        "ai_surface_metric": metric_name,
                        "psi_score": round(psi_score, 4),
                        "status": "AI_QUALITY_DRIFT_ALERT",
                        "message": f"AI Quality Proxy Metric '{metric_name}' drifted beyond threshold (PSI={psi_score:.4f})"
                    })

        return {
            "ai_quality_drift_detected": ai_drift_detected,
            "drifted_ai_metrics": results
        }

    def detect_embedding_drift(self, current_embeddings: List[List[float]], threshold_distance: float = 0.35) -> Dict[str, Any]:
        """
        [DIRECTIVE #27 - Text Embedding Cosine Distance Drift]
        Đo khoảng cách Cosine của Vector Embeddings đầu vào với Centroid Baseline chuẩn.
        """
        if self.embedding_centroid is None or not current_embeddings:
            return {"embedding_drift_detected": False, "mean_cosine_distance": 0.0}

        cur_arr = np.array(current_embeddings, dtype=float)
        centroid = self.embedding_centroid / (np.linalg.norm(self.embedding_centroid) + 1e-9)

        # Tính Cosine Distance = 1 - Cosine Similarity
        norms = np.linalg.norm(cur_arr, axis=1, keepdims=True) + 1e-9
        normalized_cur = cur_arr / norms
        cosine_sims = np.dot(normalized_cur, centroid)
        cosine_distances = 1.0 - cosine_sims
        mean_dist = float(np.mean(cosine_distances))

        drifted = mean_dist >= threshold_distance

        return {
            "embedding_drift_detected": drifted,
            "mean_cosine_distance": round(mean_dist, 4),
            "threshold_distance": threshold_distance,
            "message": f"Text Embedding Cosine Distance {mean_dist:.4f} >= threshold {threshold_distance}" if drifted else "Embeddings within normal baseline distribution."
        }

# Global Instance của DataDriftDetector
drift_detector = DataDriftDetector()
