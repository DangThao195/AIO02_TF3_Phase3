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

    def verify_remediation(self, metric_to_watch: str) -> bool:
        """
        Quét Telemetry kiểm chứng trong vòng 5 phút (C6 §50).
        """
        logger.info(f"Starting 5-minute verification window watching {metric_to_watch}...")
        start_time = time.time()
        
        # Quét cứ mỗi 30 giây
        while time.time() - start_time < VERIFICATION_PERIOD_SECONDS:
            time.sleep(30)
            # Kiểm tra xem Z-score đã về mức bình thường (|Z| < 2.0) chưa
            z_score = self.detector.check_infra_z_score(metric_to_watch)
            if abs(z_score) < 2.0:
                logger.info("Verification Success! Telemetry returned to normal.")
                return True
                
        logger.warning("Verification Timeout! Telemetry is still anomalous after 5 minutes.")
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
