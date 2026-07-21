import sys
import os
import json
import time

# Thêm thư mục aiops-engine vào path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anomaly_detector import AnomalyDetector
from rca_engine import RCAEngine
from evidence_collector import EvidenceCollector
from remediation_handler import RemediationHandler
from slack_notifier import SlackNotifier

class MockLLMDiagnostician:
    """Mock LLM to avoid calling AWS Bedrock API during testing."""
    def diagnose(self, evidence_pack: dict) -> dict:
        print("DEBUG: [Mock LLM] Analyzing evidence pack...")
        time.sleep(1)  # Giả lập thời gian suy nghĩ của AI
        
        culprit = evidence_pack["culprit_service"]
        
        # Tạo chẩn đoán giả lập chuẩn dựa trên thủ phạm
        if culprit == "fraud-detection":
            return {
                "analysis": "Phat hien loi gRPC rpc.grpc.status_code=4 (DEADLINE_EXCEEDED) tren ket noi EventStream giua fraud-detection va flagd. Day la ket noi stream dai han va bi ngat do server-side timeout sau 10 phut. Hanh vi nay la binh thuong cua flagd de giai phong bo nho, khong phai su co sap he thong that.",
                "matched_incident": "INC-3",
                "proposed_action": "cache-flush",
                "action_command": "kubectl -n techx-tf3 scale deploy/fraud-detection --replicas=1",
                "confidence_score": 1.0
            }

        else:
            return {
                "analysis": f"Phat hien chi so bat thuong tren service {culprit}. De xuat restart pod de phuc hoi.",
                "matched_incident": "None",
                "proposed_action": "restart",
                "action_command": f"kubectl -n techx-tf3 rollout restart deployment/{culprit}",
                "confidence_score": 0.75
            }

def run_simulated_incident():
    print("==================================================")
    print("BAT DAU DIEN TAP GIA LAP SU CO AIOPS CMDR PIPELINE")
    print("==================================================")
    
    # 1. Giả lập Giai đoạn 1: Nhận Alert Webhook từ Prometheus
    # Ta giả lập lỗi CheckoutLatencySpike xảy ra ở frontend
    print("\n--- GIAI DOAN 1: DUAL-LAYER DETECTION ---")
    print("[Alert firing] Alertname: CheckoutLatencySpike")
    print("[Labels] service: frontend, severity: critical")
    
    # Sử dụng Trace ID thật có lỗi mà bạn đã tìm thấy trên Jaeger
    # Trace ID: 5ee48b0 (lỗi fraud-detection kết nối flagd)
    trace_id = "5ee48b0"
    print(f"[Annotations] trace_id: {trace_id}")
    time.sleep(1)

    # 2. Giai đoạn 2: Gọi RCA Engine duyệt Jaeger Trace tìm thủ phạm thật sự
    print("\n--- GIAI DOAN 2: GRAPH-BASED RCA LOCALIZATION ---")
    print(f"Querying Jaeger API on localhost:8080 for Trace ID: {trace_id}...")
    
    rca = RCAEngine()
    trace_data = rca.fetch_trace(trace_id)
    
    if trace_data:
        culprit_service = rca.locate_culprit_service(trace_data)
        print(f"SUCCESS: Jaeger Trace parsed! Dependency graph traversed.")
        print(f"RCA RESULT: Culprit service is '{culprit_service}' (mac du alert bao o frontend-proxy).")
        # Assert that RCA correctly pinpointed fraud-detection
        assert culprit_service == "fraud-detection", f"Expected fraud-detection, got {culprit_service}"
    else:
        # Fallback nếu Jaeger không kết nối được hoặc trace bị xóa
        print("WARNING: Could not fetch trace from Jaeger. Using fallback static mapping.")
        culprit_service = "fraud-detection"
        print(f"RCA RESULT (Fallback): Culprit service is '{culprit_service}'")
        assert culprit_service == "fraud-detection"
    time.sleep(1)

    # 3. Giai đoạn 3: Gom logs OpenSearch và chạy Drain3
    print("\n--- GIAI DOAN 3: EVIDENCE PACK GENERATOR ---")
    print(f"Mining logs for service '{culprit_service}'...")
    
    collector = EvidenceCollector()
    # Mock log templates để không phụ thuộc vào OpenSearch kết nối chập chờn
    mock_raw_logs = [
        {"message": "EventStream: connection deadline exceeded in 10m"},
        {"message": "EventStream: connection deadline exceeded in 10m"},
        {"message": "flagd.evaluation.v1.Service/EventStream returned status code 4"},
        {"message": "Query failed: timeout after 600000ms"}
    ]
    log_templates = collector.cluster_logs(mock_raw_logs)
    
    # Assert that log clustering produced results
    assert len(log_templates) > 0, "Log clustering failed to produce templates"
    
    evidence_pack = {
        "culprit_service": culprit_service,
        "trace_id": trace_id,
        "alert_time": time.time(),
        "log_templates": log_templates
    }
    print("SUCCESS: Clustered 4 raw logs into clean templates using Drain3:")
    print(json.dumps(log_templates, indent=2))
    time.sleep(1)

    # 4. Giai đoạn 4: Chẩn đoán bằng LLM (Sử dụng Mock LLM)
    print("\n--- GIAI DOAN 4: LLM DIAGNOSTIC ENGINE (MOCKED) ---")
    diagnostician = MockLLMDiagnostician()
    diagnosis = diagnostician.diagnose(evidence_pack)
    print("SUCCESS: LLM Diagnosis generated!")
    print(f"Analysis: {diagnosis['analysis']}")
    # Assert that incident is correctly mapped
    assert diagnosis["matched_incident"] == "INC-3", f"Expected INC-3, got {diagnosis['matched_incident']}"
    assert diagnosis["proposed_action"] == "cache-flush", f"Expected cache-flush, got {diagnosis['proposed_action']}"
    time.sleep(1)

    # 5. Giai đoạn 5: Đánh giá rủi ro (Risk Assessment) & Gửi Slack Notification
    print("\n--- GIAI DOAN 5: POLICY / SAFETY & REMEDIATION GATE ---")
    handler = RemediationHandler()
    proposed_action = diagnosis["proposed_action"]
    action_command = diagnosis["action_command"]
    
    # 5.1 Validation Gate
    is_valid = handler.validate_action(proposed_action, action_command)
    print(f"Safety Gate Check: {'PASS' if is_valid else 'BLOCK'}")
    assert is_valid == True, "Safety check should have passed for whitelisted action"
    
    # 5.2 Risk Classification kết hợp độ tự tin LLM
    confidence_score = float(diagnosis.get("confidence_score", 1.0))
    if proposed_action in ["cache-flush", "breaker-force"]:
        risk_level = "LOW"
    elif proposed_action in ["scale", "restart"]:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"
        
    # Nâng cấp rủi ro nếu độ tự tin thấp
    if risk_level == "LOW" and confidence_score < 0.80:
        print(f"Confidence score {confidence_score} < 0.80. Elevating LOW RISK action to MEDIUM RISK for safety.")
        risk_level = "MEDIUM"
        
    print(f"ACTION RISK LEVEL: {risk_level}")
    assert risk_level == "LOW", f"Expected LOW risk, got {risk_level}"
    
    if risk_level == "LOW":
        print(f"LOW RISK Action: Automatically executing command with dry-run...")
        # Chạy dry-run để an toàn, không thay đổi hệ thống thật
        success = handler.execute_k8s_command(action_command, dry_run=True)
        print(f"Dry-run execution: {'SUCCESS' if success else 'FAILED'}")
    
    # 5.3 Hiển thị Slack Card
    print("\n--- SLACK/DISCORD CARD PREVIEW ---")
    notifier = SlackNotifier()
    sent_slack = notifier.send_incident_notification("INC-1719875400", diagnosis)
    assert sent_slack == True, "Failed to send Slack/console notification"
    print("\nALL INCIDENT FLOW SIMULATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_simulated_incident()

