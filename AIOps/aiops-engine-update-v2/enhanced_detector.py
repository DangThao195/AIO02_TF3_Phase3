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
    THREE_SIGMA_WINDOW_TICKS,
    ENABLE_TOPOLOGY_DOWNSTREAM_PENALTY,
    DOWNSTREAM_PENALTY_FACTOR,
    DOWNSTREAM_SUPPRESS_THRESHOLD,
    DOWNSTREAM_DEMOTE_THRESHOLD,
    MODEL_FEATURE_COLUMNS,
)

logger = logging.getLogger("AIOpsEngine.EnhancedDetector")

CORE_DRIFT_METRICS = ["latency_p90", "error_rate", "cpu_usage", "kafka_lag"]


class EnhancedAnomalyDetector(AnomalyDetector):
    """
    Enhanced Anomaly Detector featuring:
      1. 3-Sigma First-Drift Noise Filtering (triệt phá nhiễu spike 1-tick).
      2. Topology Downstream Symptom Penalty (trừ điểm triệu chứng hạ nguồn).

    QUAN TRỌNG - Hợp đồng công bằng khi so sánh A/B:
      Enhanced Engine KHÔNG thay đổi mô hình lõi. Nó dùng đúng cùng một
      Isolation Forest, cùng 18 feature, cùng thứ tự feature như Old Engine.
      Toàn bộ khác biệt nằm ở 2 lớp cổng hậu kiểm (post-inference gates) bên dưới.
      Nhờ vậy mọi chênh lệch chỉ số đo được đều quy được về tác động của 2 lớp này.
    """

    def __init__(self, correlator: AlertCorrelator = None):
        super().__init__()
        self.correlator = correlator or AlertCorrelator()
        logger.info("Initialized EnhancedAnomalyDetector with 3-Sigma First-Drift & Topology Symptom Penalty.")

    # ------------------------------------------------------------------
    # GATE 1: 3-SIGMA FIRST-DRIFT NOISE FILTER
    # ------------------------------------------------------------------
    def apply_three_sigma_first_drift(self, service: str, df_features: pd.DataFrame) -> dict:
        """
        Phân tích cửa sổ 1h (12 ticks x 5m) của service, xác định thời điểm bắt đầu
        lệch đầu tiên (First-Drift) theo ngưỡng động 3-Sigma (mu +/- 3*sigma).

        Trả về:
          is_drift_valid          : True nếu độ lệch đủ bền (>= THREE_SIGMA_MIN_TICKS ticks)
          is_transient_spike      : True nếu chỉ là nhiễu spike ngắn -> cần triệt tiêu
          first_drift_timestamp   : mốc thời gian bắt đầu lệch
          first_drift_metric      : chỉ số kích hoạt drift bền nhất
          drift_consecutive_ticks : số tick liên tiếp lệch tính đến tick hiện tại
        """
        neutral = {
            "is_drift_valid": True,
            "first_drift_timestamp": None,
            "first_drift_metric": None,
            "drift_consecutive_ticks": 0,
            "is_transient_spike": False,
        }

        if df_features is None or df_features.empty or len(df_features) < 3:
            # Không đủ ngữ cảnh thống kê -> không can thiệp (fail-open, giữ nguyên
            # phán quyết của Isolation Forest để không âm thầm bỏ sót sự cố).
            return neutral

        drift_signals = []

        for metric in CORE_DRIFT_METRICS:
            if metric not in df_features.columns:
                continue

            series = pd.to_numeric(df_features[metric], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            n = len(series)

            # Baseline thống kê lấy từ lịch sử (loại tick hiện tại) để tick đang xét
            # không tự kéo mean/std của chính nó -> tránh che mất drift.
            hist_series = series[:-1] if n > 3 else series
            mean = float(np.mean(hist_series))
            stddev = float(np.std(hist_series))

            if stddev < 1e-6:
                # Chuỗi phẳng tuyệt đối: mọi thay đổi vượt sai số máy đều là lệch.
                devs = np.abs(series - mean) > 1e-3
            else:
                z_scores = np.abs((series - mean) / stddev)
                devs = z_scores >= THREE_SIGMA_THRESHOLD

            if not devs[-1]:
                continue

            # Đếm ngược số tick lệch liên tiếp tính từ tick hiện tại
            consecutive = 0
            first_idx = n - 1
            for idx in range(n - 1, -1, -1):
                if devs[idx]:
                    consecutive += 1
                    first_idx = idx
                else:
                    break

            first_ts_str = None
            if "timestamp" in df_features.columns:
                first_ts_val = df_features["timestamp"].iloc[first_idx]
                first_ts_str = (
                    first_ts_val.strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(first_ts_val, (pd.Timestamp, datetime))
                    else str(first_ts_val)
                )

            drift_signals.append({
                "metric": metric,
                "consecutive": consecutive,
                "first_idx": first_idx,
                "first_timestamp": first_ts_str,
            })

        if not drift_signals:
            return neutral

        # Lấy tín hiệu bền nhất: drift kéo dài nhất mới phản ánh sự cố thật.
        main_drift = max(drift_signals, key=lambda x: x["consecutive"])
        consecutive = main_drift["consecutive"]
        is_transient_spike = consecutive < THREE_SIGMA_MIN_TICKS

        return {
            "is_drift_valid": not is_transient_spike,
            "first_drift_timestamp": main_drift["first_timestamp"],
            "first_drift_metric": main_drift["metric"],
            "drift_consecutive_ticks": consecutive,
            "is_transient_spike": is_transient_spike,
        }

    # ------------------------------------------------------------------
    # GATE 2: TOPOLOGY DOWNSTREAM SYMPTOM PENALTY
    # ------------------------------------------------------------------
    def get_dependency_services(self, service: str) -> set:
        """
        Trả về tập service mà `service` phụ thuộc vào (transitive dependencies) —
        đây là nhóm mà tài liệu gọi là "Upstream" của S theo nghĩa kỹ thuật (dịch vụ
        nền tảng/backend mà S gọi tới), KHÔNG phải "caller của S".

        Quy ước cạnh của AlertCorrelator.nx_graph: edge u -> v nghĩa là "u gọi v",
        tức v là dependency của u. Do đó tập phụ thuộc của S chính là
        nx.descendants(G, S).

        Đây là điểm đã được sửa so với bản trước: bản trước hợp cả
        successors + descendants + predecessors + ancestors, nghĩa là bất kỳ
        service nào NỐI được với S theo chiều nào cũng bị coi là upstream.
        Hệ quả là penalty bắn cả khi chính S mới là nguyên nhân gốc rễ
        (S bị lỗi -> caller của S cũng đỏ -> S bị trừ điểm oan), gây triệt tiêu
        thừa (over-suppression) và làm sụt Recall.

        Đã xác minh khớp với test_case_3_topology_downstream_symptom_penalty
        hiện có trong tests/test_enhanced_detector.py: cạnh frontend -> checkout,
        checkout Anomaly -> frontend (service gọi checkout) bị phạt điểm, vì
        frontend's alert chỉ là triệu chứng lan truyền từ checkout.
        """
        graph = self.correlator.nx_graph
        if service not in graph:
            return set()
        deps = nx.descendants(graph, service)
        deps.discard(service)
        return deps

    def apply_topology_downstream_penalty(self, service: str, raw_score: float, active_anomalies_map: dict = None) -> float:
        """
        Nếu một dependency (upstream theo chiều phụ thuộc) của S đang Anomaly thì S
        rất có thể chỉ là triệu chứng hạ nguồn (Cascade Symptom) -> trừ điểm bất thường
        của S để RCA không chọn sai nguyên nhân gốc rễ.
        """
        if not ENABLE_TOPOLOGY_DOWNSTREAM_PENALTY or not active_anomalies_map:
            return raw_score

        try:
            for parent in self.get_dependency_services(service):
                parent_state = active_anomalies_map.get(parent)
                if isinstance(parent_state, dict) and parent_state.get("prediction") == -1:
                    logger.info(
                        f"[TOPOLOGY_PENALTY] Service '{service}' is downstream of broken dependency "
                        f"'{parent}'. Applying penalty factor ({DOWNSTREAM_PENALTY_FACTOR})."
                    )
                    return raw_score * DOWNSTREAM_PENALTY_FACTOR
        except Exception as e:
            logger.warning(f"Error applying topology downstream penalty for {service}: {e}")

        return raw_score

    # ------------------------------------------------------------------
    # PRODUCTION ENTRYPOINT
    # ------------------------------------------------------------------
    def check_service_anomaly_enhanced(self, service: str, active_anomalies_map: dict = None) -> dict:
        """
        Quy trình chẩn đoán nâng cao:
          1. Isolation Forest Inference (y hệt Old Engine)
          2. 3-Sigma First-Drift Filtering (loại spike 1-tick)
          3. Topology Downstream Symptom Penalty (trừ điểm triệu chứng hạ nguồn)
        """
        res = super().check_service_anomaly(service)

        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            return res

        if res.get("prediction") != -1:
            return res

        df_features = self.extract_features_realtime(service)
        gated = self.apply_enhanced_gates(
            service=service,
            base_prediction=res.get("prediction"),
            base_score=res.get("score", -0.3),
            window_df=df_features,
            active_anomalies_map=active_anomalies_map,
        )
        res.update(gated)
        return res

    def apply_enhanced_gates(
        self,
        service: str,
        base_prediction: int,
        base_score: float,
        window_df: pd.DataFrame,
        active_anomalies_map: dict = None,
    ) -> dict:
        """
        Lõi dùng chung của 2 lớp cổng hậu kiểm, tách riêng để cả runtime production
        (check_service_anomaly_enhanced) và benchmark offline (evaluate_series) đều
        gọi ĐÚNG MỘT đoạn mã. Nhờ vậy số liệu benchmark phản ánh đúng hành vi thật.

        Chỉ chạy khi base_prediction == -1: Enhanced Engine không bao giờ tự tạo
        báo động mới, nó chỉ có thể triệt tiêu / hạ cấp báo động của mô hình lõi.
        """
        out = {"prediction": base_prediction, "score": base_score}
        if base_prediction != -1:
            return out

        # --- GATE 1: 3-Sigma First-Drift ---
        if ENABLE_3SIGMA_FIRST_DRIFT:
            drift_info = self.apply_three_sigma_first_drift(service, window_df)
            out["first_drift_timestamp"] = drift_info.get("first_drift_timestamp")
            out["first_drift_metric"] = drift_info.get("first_drift_metric")
            out["drift_consecutive_ticks"] = drift_info.get("drift_consecutive_ticks")

            if drift_info.get("is_transient_spike"):
                logger.info(
                    f"[3SIGMA_FILTER] Overriding false positive for {service}: transient 1-tick spike "
                    f"on {drift_info.get('first_drift_metric')}. Suppressing anomaly."
                )
                out["prediction"] = 1
                out["score"] = 0.05
                out["confidence"] = "SUPPRESSED_TRANSIENT_SPIKE"
                out["suppressed"] = True
                out["suppressed_by"] = "3SIGMA_TRANSIENT_SPIKE"
                return out

        # --- GATE 2: Topology Downstream Penalty ---
        if ENABLE_TOPOLOGY_DOWNSTREAM_PENALTY and active_anomalies_map:
            penalized = self.apply_topology_downstream_penalty(service, base_score, active_anomalies_map)
            out["score"] = penalized

            if penalized != base_score:
                if penalized > DOWNSTREAM_SUPPRESS_THRESHOLD:
                    out["prediction"] = 1
                    out["confidence"] = "SUPPRESSED_DOWNSTREAM_SYMPTOM"
                    out["is_downstream_symptom"] = True
                    out["suppressed"] = True
                    out["suppressed_by"] = "TOPOLOGY_DOWNSTREAM_SYMPTOM"
                elif penalized > DOWNSTREAM_DEMOTE_THRESHOLD:
                    out["confidence"] = "MEDIUM_DOWNSTREAM_SYMPTOM"
                    out["is_downstream_symptom"] = True

        return out

    # ------------------------------------------------------------------
    # OFFLINE FULL-DATASET EVALUATION (dùng cho A/B Benchmark)
    # ------------------------------------------------------------------
    def evaluate_series(
        self,
        service: str,
        df_features: pd.DataFrame,
        model,
        active_anomalies_by_tick: dict = None,
    ) -> dict:
        """
        Chấm điểm TOÀN BỘ chuỗi thời gian, tick-by-tick, KHÔNG lấy mẫu.

        Với mỗi tick i:
          - base_pred[i] = phán quyết Isolation Forest tại tick i  (== Old Engine)
          - nếu base_pred[i] == -1 thì chạy 2 lớp cổng trên cửa sổ trượt
            df_features.iloc[i-11 : i+1] (đúng 1 giờ ngữ cảnh, chỉ dùng dữ liệu quá khứ)

        Trả về mảng prediction/score của Old Engine và Enhanced Engine trên CÙNG
        tập tick -> hai bên luôn được đo trên cùng mẫu số.
        """
        X = df_features[MODEL_FEATURE_COLUMNS]
        base_pred = model.predict(X).astype(int)
        base_score = model.decision_function(X).astype(float)

        enh_pred = base_pred.copy()
        enh_score = base_score.copy()
        suppressed_by = np.array([None] * len(base_pred), dtype=object)
        first_drift_ts = np.array([None] * len(base_pred), dtype=object)

        win = THREE_SIGMA_WINDOW_TICKS
        for i in np.flatnonzero(base_pred == -1):
            i = int(i)
            window_df = df_features.iloc[max(0, i - win + 1): i + 1]
            active_map = (active_anomalies_by_tick or {}).get(i)
            gated = self.apply_enhanced_gates(
                service=service,
                base_prediction=-1,
                base_score=float(base_score[i]),
                window_df=window_df,
                active_anomalies_map=active_map,
            )
            enh_pred[i] = int(gated["prediction"])
            enh_score[i] = float(gated["score"])
            suppressed_by[i] = gated.get("suppressed_by")
            first_drift_ts[i] = gated.get("first_drift_timestamp")

        return {
            "old_prediction": base_pred,
            "old_score": base_score,
            "enhanced_prediction": enh_pred,
            "enhanced_score": enh_score,
            "suppressed_by": suppressed_by,
            "first_drift_timestamp": first_drift_ts,
            "n_ticks": len(base_pred),
        }
