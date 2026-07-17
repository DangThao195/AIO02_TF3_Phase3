import requests
import json
import logging
from config import OPENSEARCH_URL
# Drain3 imports (for log clustering)
from drain3.template_miner import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

logger = logging.getLogger("AIOpsEngine.EvidenceCollector")

class EvidenceCollector:
    def __init__(self):
        self.opensearch_url = OPENSEARCH_URL
        # Khởi tạo bộ gom log Drain3
        config = TemplateMinerConfig()
        self.template_miner = TemplateMiner(config=config)


    def fetch_opensearch_logs(self, service_name: str, start_time: int, end_time: int) -> list:
        """
        Query OpenSearch logs for a specific service in a time range.
        Uses otel-logs-* index pattern.
        """
        import os
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            from config import SIMULATION_STATE
            scenario = SIMULATION_STATE["scenario"]
            remediated = SIMULATION_STATE["remediated"]
            if scenario == "stable" or remediated:
                import datetime
                return [
                    {
                        "body": f"HTTP GET /cart success for service {service_name}",
                        "resource": {"service.name": service_name},
                        "@timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                    },
                    {
                        "body": f"Transaction completed successfully in 12ms",
                        "resource": {"service.name": service_name},
                        "@timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                    }
                ]
            fixture_path = f"fixtures/{scenario}_logs.json"
            if not os.path.exists(fixture_path):
                fixture_path = f"aiops-engine/{fixture_path}"
            if os.path.exists(fixture_path):
                try:
                    with open(fixture_path, "r", encoding="utf-8") as f:
                        raw_logs = json.load(f)
                    return [{
                        "body": log.get("body", "") or log.get("message", ""),
                        "resource": {"service.name": service_name},
                        "@timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                    } for log in raw_logs]
                except Exception as e:
                    logger.error(f"Error reading mock logs fixture: {e}")
            return []

        # Quy đổi unix timestamp sang ISO8601
        import datetime
        start_iso = datetime.datetime.utcfromtimestamp(start_time).isoformat() + "Z"
        end_iso = datetime.datetime.utcfromtimestamp(end_time).isoformat() + "Z"

        query = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"resource.service.name": service_name}},
                        {"range": {"@timestamp": {"gte": start_iso, "lte": end_iso}}}
                    ]
                }
            },
            "size": 100
        }

        try:
            url = f"{self.opensearch_url}/otel-logs-*/_search"
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, headers=headers, data=json.dumps(query), timeout=10)
            if response.status_code == 200:
                hits = response.json().get("hits", {}).get("hits", [])
                return [hit["_source"] for hit in hits]
        except Exception as e:
            logger.error(f"Error fetching logs from OpenSearch: {str(e)}")
        return []

    def cluster_logs(self, logs: list) -> list:
        """
        Giai đoạn 3: Log Miner & Clustering bằng Drain3.
        Gom hàng ngàn dòng log thô giống nhau thành các log templates gọn gàng để nhét vào prompt LLM.
        """
        if not logs:
            return []

        # Tạo mới TemplateMiner để reset clusters cho mỗi incident
        config = TemplateMinerConfig()
        self.template_miner = TemplateMiner(config=config)
        
        for log in logs:

            log_message = log.get("body", "") or log.get("message", "")
            if log_message:
                self.template_miner.add_log_message(log_message)

        # Trích xuất danh sách templates đã gom nhóm
        clustered_templates = []
        for cluster in self.template_miner.drain.clusters:
            template = cluster.get_template()
            size = cluster.size
            clustered_templates.append({
                "template": template,
                "count": size
            })
            
        logger.info(f"Log clustering complete. Reduced {len(logs)} raw logs to {len(clustered_templates)} templates.")
        return clustered_templates

    def build_evidence_pack(self, culprit_service: str, alert_time: float, trace_id: str) -> dict:
        """
        Đóng gói bằng chứng sự cố (Evidence Pack)
        """
        start_t = int(alert_time - 30)
        end_t = int(alert_time + 30)
        
        # 1. Lấy logs từ OpenSearch và chạy Drain3
        if trace_id.startswith("mock-"):
            import os
            inc_num = trace_id.split("-")[-1]  # inc1, inc2, inc3
            fixture_path = f"fixtures/{inc_num}_logs.json"
            if not os.path.exists(fixture_path):
                fixture_path = f"aiops-engine/{fixture_path}"
            try:
                with open(fixture_path, "r", encoding="utf-8") as f:
                    raw_logs = json.load(f)
                logger.info(f"Loaded OPENSEARCH MOCK Logs from fixture: {fixture_path}")
            except Exception as e:
                logger.error(f"Failed to load mock logs fixture {fixture_path}: {e}")
                raw_logs = []
        else:
            raw_logs = self.fetch_opensearch_logs(culprit_service, start_t, end_t)
            
        log_templates = self.cluster_logs(raw_logs)
        
        # 2. Lấy trace data và phân tích chuỗi liên kết lỗi (Dependency chain)
        from rca_engine import RCAEngine
        rca_engine = RCAEngine()
        
        if trace_id.startswith("mock-"):
            import os
            inc_num = trace_id.split("-")[-1]  # inc1, inc2, inc3
            fixture_path = f"fixtures/{inc_num}_trace_response.json"
            if not os.path.exists(fixture_path):
                fixture_path = f"aiops-engine/{fixture_path}"
            try:
                with open(fixture_path, "r", encoding="utf-8") as f:
                    trace_data = json.load(f)
            except Exception:
                trace_data = {}
        else:
            trace_data = rca_engine.fetch_trace(trace_id)
            
        trace_analysis = rca_engine.build_error_dependency_chain(trace_data, culprit_service)

        # 3. Đóng gói
        evidence_pack = {
            "culprit_service": culprit_service,
            "trace_id": trace_id,
            "alert_time": alert_time,
            "log_templates": log_templates,
            "total_raw_logs": len(raw_logs),
            "trace_analysis": trace_analysis
        }
        
        return evidence_pack
