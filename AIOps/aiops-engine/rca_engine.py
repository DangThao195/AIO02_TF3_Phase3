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

        def get_span_depth(sid, current_depth=0):
            # Hàm đệ quy tìm độ sâu của span trong cây
            depths = [current_depth]
            for pid, children in parent_child_map.items():
                if sid in children:
                    depths.append(get_span_depth(pid, current_depth + 1))
            return max(depths)

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

