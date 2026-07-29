import requests
import logging
from config import JAEGER_URL

logger = logging.getLogger("AIOpsEngine.RCAEngine")

class RCAEngine:
    def __init__(self):
        self.jaeger_url = JAEGER_URL

    def fetch_trace(self, trace_id: str) -> dict:
        """Fetch trace details from Jaeger Query API."""
        import os
        import json
        if os.getenv("AIOPS_SIMULATION_MODE") == "true" or trace_id.startswith("mock-"):
            inc_num = "inc3"
            if "inc" in trace_id:
                inc_num = trace_id.split("-")[-1]
            else:
                from config import SIMULATION_STATE
                inc_num = SIMULATION_STATE["scenario"]
                
            fixture_path = f"fixtures/{inc_num}_trace_response.json"
            if not os.path.exists(fixture_path):
                fixture_path = f"aiops-engine/{fixture_path}"
                
            if os.path.exists(fixture_path):
                try:
                    with open(fixture_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.error(f"Error reading mock trace fixture: {e}")
            return {"data": []}
        try:
            response = requests.get(f"{self.jaeger_url}/api/traces/{trace_id}", timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching trace {trace_id}: {str(e)}")
        return {}

    def locate_culprit_service(self, trace_data: dict) -> str:
        """
        Giai đoạn 2: Graph-based RCA Localization
        Duyệt đồ thị Jaeger DAG từ Service Root (frontend) xuống các nút con (leaf nodes).
        Tìm nút sâu nhất bị đánh dấu error=true hoặc latency vọt cao bất thường.
        """
        if not trace_data or "data" not in trace_data or not trace_data["data"]:
            return "unknown-service"

        spans = trace_data["data"][0].get("spans", [])
        processes = trace_data["data"][0].get("processes", {})

        # Xây dựng mối quan hệ cha-con giữa các Span
        parent_child_map = {}
        span_id_to_service = {}
        error_spans = []

        for span in spans:
            span_id = span["spanID"]
            process_id = span["processID"]
            service_name = processes.get(process_id, {}).get("serviceName", "unknown")
            span_id_to_service[span_id] = service_name

            # Kiểm tra xem span có bị lỗi không
            is_error = False
            for tag in span.get("tags", []):
                if tag.get("key") == "error" and tag.get("value") is True:
                    is_error = True
                    break

            if is_error:
                error_spans.append(span)

            # Map cha-con
            for ref in span.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    parent_id = ref["spanID"]
                    if parent_id not in parent_child_map:
                        parent_child_map[parent_id] = []
                    parent_child_map[parent_id].append(span_id)

        if not error_spans:
            return "unknown-service"

        # Tìm Span lỗi nằm sâu nhất (lá)
        deepest_error_span = None
        max_depth = -1

        # Map spanID to parent spanID
        span_to_parent = {}
        for span in spans:
            sid = span["spanID"]
            for ref in span.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    span_to_parent[sid] = ref["spanID"]

        def get_span_depth(sid):
            depth = 0
            curr = sid
            visited = set()
            while curr in span_to_parent and curr not in visited:
                visited.add(curr)
                depth += 1
                curr = span_to_parent[curr]
            return depth

        for span in error_spans:
            sid = span["spanID"]
            depth = get_span_depth(sid)
            if depth > max_depth:
                max_depth = depth
                deepest_error_span = span

        if deepest_error_span:
            pid = deepest_error_span["processID"]
            culprit_service = processes.get(pid, {}).get("serviceName", "unknown")
            logger.info(f"RCA localized culprit service: {culprit_service} (Span ID: {deepest_error_span['spanID']}, Depth: {max_depth})")
            return culprit_service

        return "unknown-service"

    def correlate_change_log(self, culprit_service: str, alert_time: float, change_logs: list) -> dict:
        """
        Đối chiếu mốc thời gian xảy ra sự cố với Change Log trong vòng 10 phút.
        """
        for change in change_logs:
            # Ví dụ: change = {"service": "cart", "time": 1719875400, "action": "helm upgrade"}
            if change.get("service") == culprit_service:
                time_diff = abs(alert_time - change.get("time"))
                if time_diff <= 600:  # <= 10 phút
                     logger.info(f"Change correlation match found! Service: {culprit_service} had changes {time_diff/60:.1f}m ago.")
                     return change
        return {}

    def fetch_latest_trace_id(self, service_name: str) -> str:
        """Fetch the latest trace ID that contains errors for a service from Jaeger Query API."""
        try:
            url = f"{self.jaeger_url}/api/traces"
            # Lấy 20 trace gần nhất để tìm kiếm trace thực sự bị lỗi
            params = {"service": service_name, "limit": 20}
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                traces = response.json().get("data", [])
                for trace in traces:
                    # Kiểm tra xem trace này có chứa span nào bị lỗi không
                    has_error = False
                    for span in trace.get("spans", []):
                        for tag in span.get("tags", []):
                            if tag.get("key") == "error" and tag.get("value") is True:
                                has_error = True
                                break
                        if has_error:
                            break
                    
                    if has_error:
                        tid = trace.get("traceID", "")
                        logger.info(f"Active Polling found latest ERROR trace ID for {service_name}: {tid}")
                        return tid
                
                # Fallback: Nếu không có trace lỗi nào trong 20 cái gần nhất, dùng cái mới nhất
                if traces:
                    tid = traces[0].get("traceID", "")
                    logger.info(f"No error trace found in last 20 traces. Falling back to latest trace ID: {tid}")
                    return tid
        except Exception as e:
            logger.error(f"Error fetching latest trace ID for {service_name}: {str(e)}")
        return "5ee48b0"  # Fallback to standard mock trace ID

    def build_error_dependency_chain(self, trace_data: dict, culprit_service: str) -> str:
        """
        Xây dựng chuỗi liên kết lỗi (Dependency Chain) từ root span đến culprit_service.
        """
        if not trace_data or "data" not in trace_data or not trace_data["data"]:
            return culprit_service

        spans = trace_data["data"][0].get("spans", [])
        processes = trace_data["data"][0].get("processes", {})

        # Map spanID to parent spanID and serviceName
        span_to_parent = {}
        span_to_service = {}
        error_spans = []

        for span in spans:
            sid = span["spanID"]
            pid = span["processID"]
            svc = processes.get(pid, {}).get("serviceName", "unknown")
            span_to_service[sid] = svc

            # Check if error
            is_error = False
            for tag in span.get("tags", []):
                if tag.get("key") == "error" and tag.get("value") is True:
                    is_error = True
                    break
            if is_error:
                error_spans.append(span)

            # References
            for ref in span.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    span_to_parent[sid] = ref["spanID"]

        if not error_spans:
            return culprit_service

        # Find the deepest error span (culprit)
        parent_child_map = {}
        for sid, parent_id in span_to_parent.items():
            if parent_id not in parent_child_map:
                parent_child_map[parent_id] = []
            parent_child_map[parent_id].append(sid)

        def get_span_depth(sid):
            depth = 0
            curr = sid
            visited = set()
            while curr in span_to_parent and curr not in visited:
                visited.add(curr)
                depth += 1
                curr = span_to_parent[curr]
            return depth

        deepest_error_span = None
        max_depth = -1
        for span in error_spans:
            sid = span["spanID"]
            depth = get_span_depth(sid)
            if depth > max_depth:
                max_depth = depth
                deepest_error_span = span

        if not deepest_error_span:
            return culprit_service

        # Trace from deepest error span back to the root
        path = []
        curr_id = deepest_error_span["spanID"]
        while curr_id:
            svc = span_to_service.get(curr_id, "unknown")
            path.append(svc)
            curr_id = span_to_parent.get(curr_id)

        # Reverse to get root -> child path
        path.reverse()

        # Remove consecutive duplicates to make it clean
        clean_path = []
        for svc in path:
            if not clean_path or clean_path[-1] != svc:
                clean_path.append(svc)

        return " -> ".join(clean_path)

    def detect_first_drift_timestamp(self, service_name: str, detector=None) -> float:
        """
        [DIRECTIVE #26 - Causal Inference]
        Xác định mốc thời gian bắt đầu chệch khỏi baseline 3-Sigma sớm nhất (t_drift).
        """
        import time
        if not detector:
            return time.time()
            
        try:
            end_time = time.time()
            start_time = end_time - 900  # 15 phút trước
            
            # Truy vấn Prometheus latency p90 time-series (step=15s)
            q = f'histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{{service_name="{service_name}"}}[1m])) by (le)) or vector(0)'
            raw_res = detector.query_prometheus_range(q, start_time, end_time, step="15s")
            series = detector.parse_range_result(raw_res)
            
            if series.empty or len(series) < 4:
                return end_time
                
            # Tính baseline (mu, sigma) từ 10 phút đầu (idle/normal baseline)
            baseline_data = series.iloc[:-4] if len(series) > 8 else series.iloc[:4]
            mu = baseline_data.mean()
            sigma = baseline_data.std()
            
            # Ngưỡng 3-Sigma (3σ)
            threshold = mu + max(3.0 * (sigma if sigma > 0 else 0.01), 0.1)  # Tối thiểu 100ms drift
            
            # Tìm mốc thời gian bắt đầu chệch 3σ sớm nhất
            for ts, val in series.items():
                if val > threshold:
                    drift_epoch = ts.timestamp()
                    logger.info(f"[CausalInference] Service {service_name} first-drift 3σ detected at {ts} (val={val:.3f}s > 3σ={threshold:.3f}s)")
                    return drift_epoch
        except Exception as e:
            logger.error(f"Error computing first-drift timestamp for {service_name}: {e}")
            
        return time.time()

    def rank_causal_candidates(self, candidates_data: list) -> list:
        """
        [DIRECTIVE #26 - Multi-Signal Causal Scoring Matrix]
        Xếp hạng danh sách nghi phạm theo 5 tín hiệu nhân quả (Time-series First Drift, Trace Depth, Downstream Target, Telemetry Impact, Local CPU Stress).
        """
        import time
        if not candidates_data:
            return []

        min_drift_ts = min((c.get("first_drift_ts", float("inf")) for c in candidates_data), default=time.time())

        ranked = []
        for c in candidates_data:
            svc = c.get("service", "unknown")
            lat = c.get("lat", 0.0)
            err = c.get("err", 0.0)
            cpu = c.get("cpu", 0.0)
            depth = c.get("depth", 0)
            is_downstream = c.get("is_downstream", False)
            first_drift_ts = c.get("first_drift_ts", float("inf"))

            # 1. Điểm ưu tiên thời gian chệch nhịp (Time-Series Priority Score)
            if first_drift_ts < float("inf"):
                time_diff_sec = max(0, first_drift_ts - min_drift_ts)
                time_bonus = max(0.0, 50.0 - time_diff_sec * 2.0)
            else:
                time_bonus = 0.0

            # 2. Điểm ưu tiên vị trí hạ nguồn (Downstream Priority)
            downstream_multiplier = 2.5 if is_downstream else 1.0

            # 3. Điểm tài nguyên cục bộ (CPU Stress Guard)
            cpu_bonus = 50.0 if cpu >= 0.30 else 0.0

            # 4. Điểm suy hao độ trễ & lỗi
            metric_score = (lat * 3.0 + err * 100.0)

            # Tổng điểm nhân quả (Causal Composite Score)
            total_score = (metric_score + time_bonus + depth * 0.5 + cpu_bonus) * downstream_multiplier

            reason = (
                f"First-drift bonus: {time_bonus:.1f}pts, Latency: {lat:.2f}s, Error: {err:.2f}, "
                f"Trace Depth: {depth}, Downstream Target: {is_downstream}"
            )

            ranked.append({
                "service": svc,
                "score": round(total_score, 2),
                "first_drift_ts": first_drift_ts,
                "reason": reason,
                "lat": lat,
                "err": err,
                "is_downstream": is_downstream
            })

        # Sắp xếp giảm dần theo điểm Nhân Quả tổng hợp
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked



