import requests
import time
import logging
from config import PROMETHEUS_URL

logger = logging.getLogger("AIOpsEngine.AnomalyDetector")

class AnomalyDetector:
    def __init__(self):
        self.prometheus_url = PROMETHEUS_URL

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

    def check_slo_burn_rate(self) -> bool:
        """
        Giai đoạn 1: Lớp 1 - SLO Burn-rate Monitor
        Kiểm tra xem tốc độ tiêu thụ ngân sách lỗi (Error Budget Burn Rate) có vượt ngưỡng K=14.4
        trên cả 2 cửa sổ thời gian 5 phút và 1 giờ hay không (tiêu chuẩn SRE của Google).
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

        # Giả lập query đo burn rate vỡ SLO (ví dụ tỷ lệ lỗi checkout/storefront)
        query_5m = 'sum(rate(http_server_duration_milliseconds_count{http_status_code=~"5.."}[5m])) / sum(rate(http_server_duration_milliseconds_count[5m])) * 720'
        query_1h = 'sum(rate(http_server_duration_milliseconds_count{http_status_code=~"5.."}[1h])) / sum(rate(http_server_duration_milliseconds_count[1h])) * 720'
        
        res_5m = self.query_prometheus(query_5m)
        res_1h = self.query_prometheus(query_1h)
        
        burn_rate_5m = self.parse_query_value(res_5m)
        burn_rate_1h = self.parse_query_value(res_1h)
        
        logger.info(f"SLO Burn Rate Check - 5m: {burn_rate_5m:.2f}, 1h: {burn_rate_1h:.2f}")
        
        # Ngưỡng kích hoạt cảnh báo critical K = 14.4
        return burn_rate_5m >= 14.4 and burn_rate_1h >= 14.4

    def check_infra_z_score(self, metric_name: str, window_days: int = 7) -> float:
        """
        Giai đoạn 1: Lớp 2 - ML-based Saturation & Lag Monitor
        Tính toán chỉ số Z-Score dựa trên baseline cửa sổ trượt window_days (mặc định 7 ngày)
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
        # Query tính giá trị trung bình (mean) và độ lệch chuẩn (stddev) của 7 ngày qua
        query_mean = f"avg_over_time({metric_name}[{window_days}d])"
        query_stddev = f"stddev_over_time({metric_name}[{window_days}d])"
        query_current = f"{metric_name}"
        
        mean_res = self.query_prometheus(query_mean)
        stddev_res = self.query_prometheus(query_stddev)
        current_res = self.query_prometheus(query_current)
        
        # Nếu Prometheus unreachable hoặc metric không tồn tại (trả về danh sách trống/lỗi)
        if (not mean_res.get("data", {}).get("result") or 
            not stddev_res.get("data", {}).get("result") or 
            not current_res.get("data", {}).get("result")):
            logger.warning(f"No metric data returned from Prometheus for {metric_name}. Treating as anomalous (Z-Score = 999.0)")
            return 999.0
            
        mean = self.parse_query_value(mean_res)
        stddev = self.parse_query_value(stddev_res)
        current = self.parse_query_value(current_res)
        
        if stddev == 0:
            return 0.0
            
        z_score = (current - mean) / stddev
        logger.info(f"Z-Score for {metric_name} - Current: {current:.2f}, Mean: {mean:.2f}, Stddev: {stddev:.2f}, Z: {z_score:.2f}")
        return z_score

    def parse_query_value(self, response: dict) -> float:
        """Parses PromQL response and returns float value."""
        try:
            if response.get("status") == "success":
                results = response.get("data", {}).get("result", [])
                if results:
                    return float(results[0]["value"][1])
        except (IndexError, KeyError, ValueError, TypeError):
            pass
        return 0.0
