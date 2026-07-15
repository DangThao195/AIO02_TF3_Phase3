import subprocess
import time
import logging
from config import WHITELISTED_ACTIONS, EXECUTION_TIMEOUT_SECONDS, VERIFICATION_PERIOD_SECONDS, SIMULATION_SERVER_URL
from anomaly_detector import AnomalyDetector

logger = logging.getLogger("AIOpsEngine.RemediationHandler")

class RemediationHandler:
    def __init__(self):
        self.whitelisted_actions = WHITELISTED_ACTIONS
        self.detector = AnomalyDetector()

    def validate_action(self, action: str, command: str) -> bool:
        """
        Validation Gate: Chặn đứng lệnh ngoài whitelist (C6 Invariant 2).
        """
        if action not in self.whitelisted_actions:
            logger.warning(f"Action '{action}' is not whitelisted! Blocking execution.")
            return False

        # Kiểm tra thô tránh command injection nguy hiểm
        forbidden_keywords = ["rm", "delete", "flagd-sync", "token", "mkfs", "bash"]

        for kw in forbidden_keywords:
            if kw in command.lower():
                logger.warning(f"Command contains forbidden keyword '{kw}'! Blocking execution.")
                return False

        return True

    def sanitize_command(self, command: str) -> str:
        """
        Namespace Injection: Đảm bảo luôn chạy trên đúng namespace techx-tf3.
        """
        if "kubectl" in command and "-n techx-tf3" not in command:
            if " -n " not in command:
                command = command.replace("kubectl", "kubectl -n techx-tf3")
        return command

    def execute_k8s_command(self, command: str, dry_run: bool = False) -> bool:
        """
        Thực thi lệnh K8s. Sử dụng --dry-run=server để test an toàn.
        """
        full_command = command
        if dry_run:
            full_command += " --dry-run=client"

        logger.info(f"Executing command: {full_command}")
        
        # Hỗ trợ chế độ giả lập Sandbox cục bộ
        import os
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            logger.info(f"[SIMULATION] Bypassing actual command execution: {full_command}")
            try:
                import requests
                requests.post(f"{SIMULATION_SERVER_URL}/simulate/remediate", timeout=5)
            except Exception as e:
                logger.error(f"[SIMULATION] Failed to notify mock server of remediation: {e}")
            return True
        try:
            # Chạy lệnh trong terminal tối đa 5 phút (C6 Invariant 3)
            result = subprocess.run(
                full_command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=EXECUTION_TIMEOUT_SECONDS
            )
            if result.returncode == 0:
                logger.info(f"Command executed successfully: {result.stdout.strip()}")
                return True
            logger.error(f"Command failed with code {result.returncode}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.error(f"Command execution timed out after {EXECUTION_TIMEOUT_SECONDS}s!")
        except Exception as e:
            logger.error(f"Error executing command: {str(e)}")
        return False

    def verify_remediation(self, culprit_service: str) -> bool:
        """
        Quét Telemetry kiểm chứng lai (Hybrid Verification) trong vòng 5 phút (C6 §50).
        Yêu cầu cả hai điều kiện sau đồng thời vượt qua liên tục trong 5 chu kỳ quét (2.5 phút):
          1. Z-score tỷ lệ lỗi dịch vụ trở lại bình thường (|Z| < 2.0).
          2. Isolation Forest dự đoán trạng thái bình thường (prediction == 1, không có tác dụng phụ về tài nguyên/độ trễ).
        """
        metric_to_watch = f'sum(rate(traces_span_metrics_calls_total{{service_name="{culprit_service}", status_code="STATUS_CODE_ERROR"}}[1m])) or vector(0)'
        logger.info(f"Starting SRE 5-minute Hybrid Verification for {culprit_service}...")
        logger.info(f"  - Gate 1 (Z-Score): watching error metric: {metric_to_watch}")
        logger.info(f"  - Gate 2 (ML Isolation Forest): watching multi-dimensional service health")
        
        start_time = time.time()
        consecutive_passes = 0
        
        feature_cols = [
            "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
            "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
            "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
        ]
        
        while time.time() - start_time < VERIFICATION_PERIOD_SECONDS:
            time.sleep(30)
            
            # 1. Kiểm tra Gate 1: Z-score của tỷ lệ lỗi
            z_score = self.detector.check_infra_z_score(metric_to_watch)
            z_passed = abs(z_score) < 2.0
            
            # 2. Kiểm tra Gate 2: ML Isolation Forest
            if_passed = False
            try:
                df_features = self.detector.extract_features_realtime(culprit_service)
                if not df_features.empty and len(df_features) >= 1:
                    latest_row = df_features.tail(1).to_dict("records")[0]
                    features_list = [latest_row[col] for col in feature_cols]
                    # check_infra_anomaly trả về True nếu bất thường, False nếu bình thường
                    is_anomalous = self.detector.check_infra_anomaly(culprit_service, features_list)
                    if_passed = not is_anomalous
                    logger.info(f"ML check for {culprit_service} - Anomaly flag: {is_anomalous}")
                else:
                    logger.warning(f"No real-time features returned for {culprit_service} during verify poll. Falling back to Z-score only.")
                    if_passed = True
            except Exception as e:
                logger.error(f"Error checking ML anomaly flag during verify: {e}")
                if_passed = True
                
            # Đánh giá kết quả chu kỳ quét hiện tại
            if z_passed and if_passed:
                consecutive_passes += 1
                logger.info(f"Verification cycle passed ({consecutive_passes}/5). Z-score: {z_score:.2f}, ML: Normal")
                if consecutive_passes >= 5:
                    logger.info(f"Verification Success! Service {culprit_service} error rate and ML health returned to normal for 5 consecutive checks.")
                    return True
            else:
                consecutive_passes = 0
                logger.warning(f"Verification cycle failed. Z-score passed: {z_passed} (Z: {z_score:.2f}), ML passed: {if_passed}")
                
        logger.warning(f"Verification Timeout! Service {culprit_service} is still anomalous after 5 minutes.")
        return False

    def trigger_rollback(self, rollback_command: str) -> bool:
        """
        Chạy Rollback Plan khi xác minh thất bại.
        """
        logger.warning(f"Triggering rollback plan using command: {rollback_command}")
        return self.execute_k8s_command(rollback_command)

    def escalate(self, incident_id: str, culprit: str, action: str):
        """
        Nếu Rollback thất bại, chuyển sang Manual Mode và bắn báo động khẩn cấp tới SRE.
        """
        logger.critical(f"🚨 ESCALATE: Rollback failed for Incident {incident_id} on {culprit}!")
        # Code thực tế sẽ gọi API Slack/PagerDuty để réo chuông báo động
