import time
import logging
import asyncio
import json
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
from anomaly_detector import AnomalyDetector
from rca_engine import RCAEngine
from evidence_collector import EvidenceCollector
from llm_diagnostician import LLMDiagnostician
from remediation_handler import RemediationHandler
from slack_notifier import SlackNotifier
from alert_correlator import AlertCorrelator

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AIOpsEngine.Main")

app = FastAPI(title="TF3 AIOps CMDR Engine", version="1.0")

# Khởi tạo các module
detector = AnomalyDetector()
rca_engine = RCAEngine()
evidence_collector = EvidenceCollector()
diagnostician = LLMDiagnostician()
handler = RemediationHandler()
notifier = SlackNotifier()
correlator = AlertCorrelator()

# Bộ đếm số lần chạy hành động chống chạy lặp vô hạn (C6 Invariant 4)
action_counters = {}  # {incident_id: count}
active_incidents = {}  # {incident_id: diagnosis_dict}
last_proactive_alert_time = {}  # {service_name: timestamp} (Chống alert fatigue)

# Cấu hình Sandbox Giả lập (Local Chaos Sandbox)
import datetime
import os
from config import SIMULATION_STATE
simulation_state = SIMULATION_STATE

# Cấu hình Active Metrics Polling Loop (Chế độ tự động quét chủ động - Mode B)
ACTIVE_POLLING_ENABLED = True
POLLING_INTERVAL_SECONDS = 30

async def active_metrics_polling_loop():
    logger.info("Starting Active Metrics Polling Loop (Mode B)...")
    await asyncio.sleep(5)  # Đợi uvicorn khởi tạo xong cổng kết nối
    while ACTIVE_POLLING_ENABLED:
        try:
            # Chỉ bỏ qua nếu có sự cố đang xử lý (active) thực tế (không phải là cảnh báo sớm ML)
            running_incidents = {k: v for k, v in active_incidents.items() if v.get("status") != "proactive_warning"}
            if running_incidents:
                logger.info("Active running incident exists. Skipping duplicate polling run.")
                await asyncio.sleep(POLLING_INTERVAL_SECONDS)
                continue

            logger.info("Active Polling Check: checking system SLO via Prometheus...")
            is_breached = detector.check_slo_burn_rate()
            
            if is_breached:
                logger.warning("SLO Burn Rate breach detected via Active Polling!")
                
                # Check xem đã có cảnh báo sớm ML trong cache chưa để nâng cấp
                proactive_inc_id = None
                for inc_id, inc_data in list(active_incidents.items()):
                    if inc_data.get("status") == "proactive_warning":
                        proactive_inc_id = inc_id
                        break
                        
                if proactive_inc_id:
                    logger.warning(f"Promoting proactive ML warning {proactive_inc_id} to active incident due to SLO breach!")
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(
                        None,
                        process_incident_promotion_background,
                        proactive_inc_id
                    )
                else:
                    incident_id = f"INC-{int(time.time())}"
                    # Nếu đang trong kịch bản giả lập Sandbox
                    if simulation_state["scenario"].startswith("inc"):
                        trace_id = f"mock-{simulation_state['scenario']}"
                    else:
                        trace_id = rca_engine.fetch_latest_trace_id("frontend")
                    
                    # Gọi RCA để xác định thủ phạm
                    if trace_id.startswith("mock-"):
                        inc_num = trace_id.split("-")[-1]
                        fixture_path = f"fixtures/{inc_num}_trace_response.json"
                        if not os.path.exists(fixture_path):
                            fixture_path = f"aiops-engine/{fixture_path}"
                        try:
                            with open(fixture_path, "r", encoding="utf-8") as f:
                                trace_data = json.load(f)
                            logger.info(f"Loaded JAEGER MOCK Trace data from fixture: {fixture_path}")
                        except Exception as e:
                            logger.error(f"Failed to load mock trace fixture {fixture_path}: {e}")
                            trace_data = {}
                    else:
                        trace_data = rca_engine.fetch_trace(trace_id)
                        
                    culprit_service = rca_engine.locate_culprit_service(trace_data)
                    if culprit_service == "unknown-service":
                        culprit_service = "checkout"  # Fallback mặc định
                        
                    logger.info(f"Triggering CMDR Pipeline for {incident_id} (Culprit: {culprit_service}, Trace ID: {trace_id})")
                    
                    # Chạy luồng chẩn đoán và sửa lỗi bất đồng bộ
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(
                        None,
                        process_incident_background,
                        incident_id,
                        culprit_service,
                        trace_id,
                        time.time()
                    )
            else:
                # Lớp 2: Quét máy học (Isolation Forest) cho từng dịch vụ chủ động
                logger.info("SLO is stable. Running ML Isolation Forest proactive scans on core services...")
                
                SERVICES = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]
                detected_culprit = None
                anomalous_services = set()
                
                for service in SERVICES:
                    # 1. Trích xuất đặc trưng thời gian thực
                    df_features = detector.extract_features_realtime(service)
                    if df_features.empty or len(df_features) < 1:
                        # Fallback Z-Score nếu thiếu dữ liệu ngữ cảnh
                        is_anomalous = detector.check_infra_anomaly(service, [])
                    else:
                        feature_cols = [
                            "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
                            "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
                            "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
                        ]
                        features_list = df_features[feature_cols].iloc[-1].tolist()
                        is_anomalous = detector.check_infra_anomaly(service, features_list)
                    
                    if is_anomalous:
                        logger.warning(f"ML Isolation Forest proactively detected ANOMALY on service: {service}!")
                        anomalous_services.add(service)
                            
                # Dọn dẹp các proactive warning cũ của các service đã trở lại bình thường
                for inc_id, inc_data in list(active_incidents.items()):
                    if inc_data.get("status") == "proactive_warning":
                        svc = inc_data.get("culprit_service")
                        if svc not in anomalous_services:
                            logger.info(f"Proactive anomaly resolved for service {svc}. Removing {inc_id} from cache.")
                            active_incidents.pop(inc_id, None)
                        
                if anomalous_services:
                    # Chuyển đổi anomalous_services thành danh sách mock alerts để chạy qua correlator
                    mock_alerts = []
                    for service in anomalous_services:
                        if simulation_state["scenario"].startswith("inc"):
                            trace_id = f"mock-{simulation_state['scenario']}"
                        else:
                            trace_id = rca_engine.fetch_latest_trace_id(service)
                        mock_alerts.append({
                            "labels": {"service": service, "alertname": "MLProactiveAnomaly", "severity": "warning"},
                            "annotations": {"trace_id": trace_id}
                        })
                    
                    # Sử dụng Union-Find & Topology Correlation để gom nhóm và xác định culprit gốc
                    clusters = correlator.correlate_alerts(mock_alerts)
                    
                    for cluster in clusters:
                        service = cluster["culprit_service"]
                        trace_id = cluster["trace_id"]
                        
                        # Chống alert fatigue: Kiểm tra thời gian cooldown (300 giây = 5 phút) cho culprit
                        now_ts = time.time()
                        last_alert_ts = last_proactive_alert_time.get(service, 0)
                        if now_ts - last_alert_ts < 300:
                            logger.info(f"Proactive warning for {service} was sent recently. Throttling to prevent alert fatigue (cooldown remaining: {300 - (now_ts - last_alert_ts):.1f}s).")
                        else:
                            last_proactive_alert_time[service] = now_ts
                            incident_id = f"INC-ML-{int(now_ts)}"
                            
                            logger.info(f"Triggering PROACTIVE CMDR Pipeline for {incident_id} (Culprit: {service}, Clustered Services: {cluster['services']}, Trace ID: {trace_id})")
                            
                            loop = asyncio.get_running_loop()
                            loop.run_in_executor(
                                None,
                                process_proactive_anomaly_background,
                                incident_id,
                                service,
                                trace_id,
                                now_ts
                            )
                else:
                    logger.info("Active Polling Check: All services are healthy under ML Isolation Forest scans.")
        except Exception as e:
            logger.error(f"Error in active metrics polling loop: {str(e)}")
            
        await asyncio.sleep(POLLING_INTERVAL_SECONDS)

async def periodic_graph_reload_loop():
    """Tự động reload đồ thị services.json mỗi 5 phút để giữ đồ thị luôn mới (Graph Freshness)."""
    while True:
        await asyncio.sleep(300)
        logger.info("Periodic Graph Reload: Checking and reloading service graph...")
        correlator.reload_graph()

@app.on_event("startup")
async def startup_event():
    # Khởi động tác vụ quét ngầm khi FastAPI start
    asyncio.create_task(active_metrics_polling_loop())
    asyncio.create_task(periodic_graph_reload_loop())

@app.get("/readyz")
async def readiness_probe():
    """
    Readiness Probe check xem dịch vụ đã sẵn sàng phục vụ chưa.
    Yêu cầu: Đồ thị topology đã được load thành công và có số nút > 0.
    """
    if not correlator.service_graph or correlator.metadata["graph_node_count"] == 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Service topology graph not loaded or empty.")
    return {
        "status": "ready",
        "checks": {
            "topology_graph": "ok",
            "local_kb": "ok"
        }
    }

@app.get("/version")
async def get_version_info():
    """
    Trả về phiên bản phần mềm, cấu hình pipeline và metadata chi tiết của Topology Graph (Graph Versioning).
    """
    return {
        "app_version": "1.0.0",
        "pipeline_config": {
            "gap_sec": 120,
            "max_hop": correlator.max_hop
        },
        "graph_metadata": correlator.metadata
    }


class AlertItem(BaseModel):
    status: str
    labels: dict
    annotations: dict

class AlertmanagerWebhook(BaseModel):
    alerts: list[AlertItem]

def process_incident_background(incident_id: str, culprit_service: str, trace_id: str, alert_time: float):
    """
    Quy trình tự động hóa khép kín chạy ngầm (Giai đoạn 3 -> Giai đoạn 5)
    """
    logger.info(f"--- Processing Incident {incident_id} ---")
    
    # 1. Giai đoạn 3: Gom logs và traces làm Bằng chứng (Evidence Pack)
    logger.info("Step 1: Generating Evidence Pack...")
    evidence = evidence_collector.build_evidence_pack(culprit_service, alert_time, trace_id)
    
    # 2. Giai đoạn 4: Gọi Bedrock Chẩn đoán
    logger.info("Step 2: Invoking LLM Bedrock Diagnostician...")
    diagnosis = diagnostician.diagnose(evidence)
    
    # Bổ sung thông tin bổ sung vào diagnosis trước khi phân loại rủi ro
    diagnosis["incident_id"] = incident_id
    diagnosis["culprit_service"] = culprit_service
    
    # 3. Giai đoạn 5.1 & 5.2: Bộ lọc an toàn & Phân loại rủi ro (Risk Assessment)
    proposed_action = diagnosis.get("proposed_action", "none")
    
    # Lớp 3 - Command Template Whitelist: Định nghĩa mẫu lệnh an toàn tuyệt đối
    COMMAND_TEMPLATES = {
        "scale":       "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "restart":     "kubectl -n techx-tf3 rollout restart deployment/{service}",
        "cache-flush": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "breaker-force": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "none": ""
    }
    ROLLBACK_TEMPLATES = {
        "scale":       "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "restart":     "kubectl -n techx-tf3 rollout undo deployment/{service}",
        "cache-flush": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "breaker-force": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "none": ""
    }
    
    # Ép buộc sử dụng lệnh được chuẩn hóa từ template an toàn
    if proposed_action in COMMAND_TEMPLATES:
        action_command = COMMAND_TEMPLATES[proposed_action].format(service=culprit_service)
        rollback_command = ROLLBACK_TEMPLATES[proposed_action].format(service=culprit_service)
    else:
        action_command = diagnosis.get("action_command", "")
        rollback_command = diagnosis.get("rollback_command", "")
        
    diagnosis["action_command"] = action_command
    diagnosis["rollback_command"] = rollback_command
    active_incidents[incident_id] = diagnosis
    
    # Validation Gate
    if not handler.validate_action(proposed_action, action_command):
        logger.warning("Action failed safety validation gate. Rejecting.")
        diagnosis["analysis"] = f"[SAFETY REJECTED] {diagnosis['analysis']}"
        diagnosis["action_command"] = "Command blocked due to C6 policy violation."
        notifier.send_incident_notification(incident_id, diagnosis)
        return

    # Phân loại rủi ro (Risk Assessment) kết hợp độ tự tin LLM (Confidence Score)
    confidence_score = float(diagnosis.get("confidence_score", 1.0))
    logger.info(f"LLM Decision Confidence Score: {confidence_score * 100}%")
    
    current_risk = "UNKNOWN"
    if proposed_action in ["cache-flush", "breaker-force"]:
        current_risk = "LOW"
    elif proposed_action in ["scale", "restart", "toggle-tf-flag"]:
        current_risk = "MEDIUM"
    else:
        current_risk = "HIGH"
        
    # Nâng cấp rủi ro nếu độ tự tin thấp
    if current_risk == "LOW" and confidence_score < 0.80:
        logger.warning(f"Confidence score {confidence_score} < 0.80. Elevating LOW RISK action to MEDIUM RISK for safety.")
        current_risk = "MEDIUM"

    if current_risk == "LOW":
        # Mức LOW RISK: Tự động chạy ngay lập tức
        logger.info(f"Action '{proposed_action}' classified as LOW RISK. Auto-executing...")
        success = handler.execute_k8s_command(action_command)
        if success:
            logger.info("Low risk action executed successfully.")
            # Verify 5 phút
            is_resolved = handler.verify_remediation(culprit_service)
            if is_resolved:
                active_incidents.pop(incident_id, None)
        else:
            logger.error("Low risk action execution failed.")
            active_incidents.pop(incident_id, None)
            
    elif current_risk == "MEDIUM":
        # Mức MEDIUM RISK: Gửi Slack chờ Approve
        logger.info(f"Action '{proposed_action}' classified as MEDIUM RISK. Sending Slack card...")
        notifier.send_incident_notification(incident_id, diagnosis)
        
    else:
        # Mức HIGH RISK hoặc lệnh lạ: Tự động từ chối
        logger.warning(f"Action '{proposed_action}' classified as HIGH RISK. Rejecting automatically.")
        diagnosis["analysis"] = f"[AUTO-REJECTED] Dangerous/Uncertain command blocked: {diagnosis['analysis']}"
        notifier.send_incident_notification(incident_id, diagnosis)
        active_incidents.pop(incident_id, None)



def process_proactive_anomaly_background(incident_id: str, culprit_service: str, trace_id: str, alert_time: float):
    """
    Chạy chẩn đoán sớm cho máy học: Chạy RCA để tìm nguyên nhân gốc từ Jaeger trace
    và OpenSearch logs, không gọi Bedrock LLM và không đề xuất phương án khắc phục tự động.
    """
    logger.info(f"--- [PROACTIVE ML WARNING] Processing early anomaly for {culprit_service} ({incident_id}) ---")
    
    # 1. Thu thập bằng chứng
    logger.info("[PROACTIVE] Step 1: Generating Evidence Pack...")
    evidence = evidence_collector.build_evidence_pack(culprit_service, alert_time, trace_id)
    
    # 2. Phân tích Jaeger Trace RCA & logs lỗi
    logs_summary = []
    templates = evidence.get("log_templates", [])
    error_keywords = ["error", "fail", "warn", "exception", "deadline", "out of order", "epoch"]
    
    def priority_score(t_dict):
        text = t_dict.get("template", "").lower()
        if any(kw in text for kw in error_keywords):
            return 0
        return 1
        
    sorted_templates = sorted(templates, key=priority_score)
    for log_t in sorted_templates[:5]:
        template = log_t.get("template", "")
        count = log_t.get("count", 1)
        if len(template) > 100:
            template = template[:100] + "..."
        logs_summary.append(f"• `[Count: {count}]` {template}")
        
    logs_section = "\n".join(logs_summary) if logs_summary else "• *Không tìm thấy logs lỗi liên quan trong OpenSearch.*"
    
    rca_path = f"Phát hiện bất thường bắt nguồn từ dịch vụ `{culprit_service}`."
    if "trace_analysis" in evidence:
        rca_path = f"Trace Path / Dependency chain: {evidence['trace_analysis']}"
        
    analysis_str = (
        f"*Thông tin chẩn đoán chủ động (ML early warning):*\n"
        f"• Dịch vụ phát sinh bất thường: `{culprit_service}`\n"
        f"• Trace ID: `{trace_id}`\n"
        f"• Phân tích đường đi lỗi (RCA): {rca_path}\n\n"
        f"*Logs lỗi chi tiết thu thập từ OpenSearch:*\n{logs_section}"
    )
    
    diagnosis = {
        "incident_id": incident_id,
        "culprit_service": culprit_service,
        "analysis": analysis_str,
        "proposed_action": "none",
        "action_command": "",
        "rollback_command": "",
        "confidence_score": 1.0,
        "matched_incident": "N/A",
        "status": "proactive_warning",
        "evidence": evidence,
        "alert_time": alert_time,
        "trace_id": trace_id
    }
    
    active_incidents[incident_id] = diagnosis
    
    # 3. Gửi Slack cảnh báo sớm dạng thông tin (Proactive Warning Card)
    logger.info(f"[PROACTIVE] Sending early warning Slack card (RCA only) for {incident_id}...")
    notifier.send_incident_notification(incident_id, diagnosis)

def process_incident_promotion_background(incident_id: str):
    """
    Nâng cấp sự cố chẩn đoán sớm lên sự cố chính thức khi SLO bị vỡ: Gọi Bedrock và bắn Slack card.
    """
    logger.info(f"--- Promoting Proactive Warning {incident_id} to Active Diagnostics due to SLO breach ---")
    inc_data = active_incidents.get(incident_id)
    if not inc_data:
        logger.error(f"Incident data for {incident_id} not found in cache.")
        return
        
    inc_data["status"] = "active"
    evidence = inc_data["evidence"]
    culprit_service = inc_data["culprit_service"]
    
    # 2. Giai đoạn 4: Gọi Bedrock Chẩn đoán
    logger.info("Step 2: Invoking LLM Bedrock Diagnostician (Promoted Path)...")
    diagnosis = diagnostician.diagnose(evidence)
    
    diagnosis["incident_id"] = incident_id
    diagnosis["culprit_service"] = culprit_service
    
    # 3. Giai đoạn 5.1 & 5.2: Bộ lọc an toàn & Phân loại rủi ro (Risk Assessment)
    proposed_action = diagnosis.get("proposed_action", "none")
    
    COMMAND_TEMPLATES = {
        "scale":       "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "restart":     "kubectl -n techx-tf3 rollout restart deployment/{service}",
        "cache-flush": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "breaker-force": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "none": ""
    }
    ROLLBACK_TEMPLATES = {
        "scale":       "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "restart":     "kubectl -n techx-tf3 rollout undo deployment/{service}",
        "cache-flush": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "breaker-force": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "none": ""
    }
    
    if proposed_action in COMMAND_TEMPLATES:
        action_command = COMMAND_TEMPLATES[proposed_action].format(service=culprit_service)
        rollback_command = ROLLBACK_TEMPLATES[proposed_action].format(service=culprit_service)
    else:
        action_command = diagnosis.get("action_command", "")
        rollback_command = diagnosis.get("rollback_command", "")
        
    diagnosis["action_command"] = action_command
    diagnosis["rollback_command"] = rollback_command
    active_incidents[incident_id] = diagnosis
    
    # Validation Gate
    if not handler.validate_action(proposed_action, action_command):
        logger.warning("Action failed safety validation gate. Rejecting.")
        diagnosis["analysis"] = f"[SAFETY REJECTED] {diagnosis['analysis']}"
        diagnosis["action_command"] = "Command blocked due to C6 policy violation."
        notifier.send_incident_notification(incident_id, diagnosis)
        return
        
    confidence_score = float(diagnosis.get("confidence_score", 1.0))
    logger.info(f"LLM Decision Confidence Score: {confidence_score * 100}%")
    
    current_risk = "UNKNOWN"
    if proposed_action in ["cache-flush", "breaker-force"]:
        current_risk = "LOW"
    elif proposed_action in ["scale", "restart", "toggle-tf-flag"]:
        current_risk = "MEDIUM"
    else:
        current_risk = "HIGH"
        
    if current_risk == "LOW" and confidence_score < 0.80:
        logger.warning(f"Confidence score {confidence_score} < 0.80. Elevating LOW RISK action to MEDIUM RISK for safety.")
        current_risk = "MEDIUM"
        
    if current_risk == "LOW":
        logger.info(f"Action '{proposed_action}' classified as LOW RISK. Auto-executing...")
        success = handler.execute_k8s_command(action_command)
        if success:
            logger.info("Low risk action executed successfully.")
            is_resolved = handler.verify_remediation(culprit_service)
            if is_resolved:
                active_incidents.pop(incident_id, None)
        else:
            logger.error("Low risk action execution failed.")
            active_incidents.pop(incident_id, None)
            
    elif current_risk == "MEDIUM":
        logger.info(f"Action '{proposed_action}' classified as MEDIUM RISK. Sending Slack card...")
        notifier.send_incident_notification(incident_id, diagnosis)
        
    else:
        logger.warning(f"Action '{proposed_action}' classified as HIGH RISK. Rejecting automatically.")
        diagnosis["analysis"] = f"[AUTO-REJECTED] Dangerous/Uncertain command blocked: {diagnosis['analysis']}"
        notifier.send_incident_notification(incident_id, diagnosis)
        active_incidents.pop(incident_id, None)


@app.post("/webhook/alerts")
async def receive_prometheus_alert(payload: AlertmanagerWebhook, background_tasks: BackgroundTasks):
    """
    FastAPI endpoint nhận Alert webhook từ Prometheus Alertmanager.
    Sử dụng AlertCorrelator để gom nhóm lỗi trùng lặp (Dedup) và lỗi lan truyền (Topology correlation).
    """
    raw_alerts = []
    for alert in payload.alerts:
        if alert.status == "firing":
            raw_alerts.append({
                "labels": alert.labels,
                "annotations": alert.annotations
            })
            
    if not raw_alerts:
        return {"status": "no active firing alerts"}
        
    # Gom nhóm cảnh báo bằng AlertCorrelator
    clusters = correlator.correlate_alerts(raw_alerts)
    
    for idx, cluster in enumerate(clusters):
        incident_id = f"INC-{int(time.time())}-{idx}"
        culprit_service = cluster["culprit_service"]
        trace_id = cluster["trace_id"]
        
        # Nếu đang có sự cố active thì bỏ qua chẩn đoán lặp
        if active_incidents:
            logger.info(f"Active incident exists. Skipping diagnostic run for clustered incident {incident_id} to save API costs.")
            continue
            
        logger.info(f"Triggering CMDR Pipeline for Clustered Incident {incident_id} (Culprit: {culprit_service}, Services: {cluster['services']})")
        
        # Đẩy tác vụ xử lý sự cố chạy ngầm để không làm nghẽn Alertmanager
        background_tasks.add_task(
            process_incident_background,
            incident_id=incident_id,
            culprit_service=culprit_service,
            trace_id=trace_id,
            alert_time=time.time()
        )
        
    return {"status": "accepted", "clusters_processed": len(clusters)}

async def process_approval_action(incident_id: str, value: str) -> dict:
    """
    Core logic to execute or reject an approved remediation action.
    """
    # Đọc thông tin chẩn đoán động từ in-memory store
    diagnosis = active_incidents.get(incident_id)
    if not diagnosis:
        logger.warning(f"Incident {incident_id} not found in in-memory store. Falling back to default reviews-server.")
        command = "kubectl -n techx-tf3 rollout restart deployment/product-reviews-server"
        rollback_command = "kubectl -n techx-tf3 rollout undo deployment/product-reviews-server"
        culprit_service = "product-reviews-server"
        proposed_action = "restart"
    else:
        command = diagnosis.get("action_command", "")
        rollback_command = diagnosis.get("rollback_command", "")
        culprit_service = diagnosis.get("culprit_service", "unknown-service")
        proposed_action = diagnosis.get("proposed_action", "none")
        
        # Nếu LLM không tự sinh lệnh rollback, tự sinh fallback
        if not rollback_command and command:
            if "scale" in command:
                dep_name = culprit_service
                for word in command.split():
                    if "deploy/" in word or "deployment/" in word:
                        dep_name = word.split("/")[-1]
                rollback_command = f"kubectl -n techx-tf3 scale deploy/{dep_name} --replicas=2"
            else:
                dep_name = culprit_service
                for word in command.split():
                    if "deploy/" in word or "deployment/" in word:
                        dep_name = word.split("/")[-1]
                rollback_command = f"kubectl -n techx-tf3 rollout undo deployment/{dep_name}"

    if value == "approve":
        # 1. Kiểm tra giới hạn số lần chạy (C6 Invariant 4)
        count = action_counters.get(incident_id, 0)
        if count >= 3:
            logger.warning(f"Incident {incident_id} exceeded rate limit! Blocking execution.")
            return {"text": "🚨 Lỗi: Sự cố này đã chạy vượt quá giới hạn 3 lần/giờ. Vui lòng xử lý thủ công."}
            
        action_counters[incident_id] = count + 1
        
        # Vệ sinh câu lệnh (Lớp 1 - Namespace injection)
        command = handler.sanitize_command(command)
        if rollback_command:
            rollback_command = handler.sanitize_command(rollback_command)
            
        # Lớp 2 - Kiểm chứng dry-run trước khi chạy thật
        logger.info(f"Dry-running approved remediation command: {command}")
        dry_success = handler.execute_k8s_command(command, dry_run=True)
        if not dry_success:
            logger.error(f"Dry-run verification failed for command: {command}")
            return {"text": f"🚨 Lỗi: Lệnh kiểm thử (dry-run) thất bại! Câu lệnh không hợp lệ: `{command}`"}
            
        # Thực thi lệnh K8s thật (Lớp 3 - Command execution)
        logger.info(f"Executing approved remediation command: {command}")
        success = handler.execute_k8s_command(command, dry_run=False)
        
        if success:
            # 2. Chạy quét xác minh trong 5 phút
            is_resolved = handler.verify_remediation(culprit_service)
            if not is_resolved:
                # 3. Xác minh thất bại -> Tự động Rollback
                logger.warning(f"Remediation verification failed. Triggering rollback for {incident_id}...")
                rollback_success = handler.trigger_rollback(rollback_command)
                active_incidents.pop(incident_id, None)
                if not rollback_success:
                    # 4. Rollback thất bại -> Escalate báo động SRE
                    handler.escalate(incident_id, culprit_service, proposed_action)
                    return {"text": f"🚨 KHẨN CẤP: Lệnh sửa lỗi đã chạy nhưng hệ thống không phục hồi, và quá trình Rollback cũng thất bại! Đã báo động cho đội SRE on-call."}
                return {"text": "⚠️ Cảnh báo: Lệnh sửa lỗi chạy thất bại. Hệ thống đã được tự động Rollback về trạng thái cũ an toàn."}
            active_incidents.pop(incident_id, None)
            return {"text": "✅ Thành công: Lệnh khắc phục đã được duyệt và thực thi thành công. Hệ thống đã phục hồi hoàn toàn."}
        else:
            active_incidents.pop(incident_id, None)
            return {"text": "❌ Lỗi: Không thể thực thi lệnh K8s API. Vui lòng kiểm tra logs hệ thống."}
            
    elif value == "reject":
        logger.info(f"Incident {incident_id} remediation rejected by operator.")
        active_incidents.pop(incident_id, None)
        return {"text": "❌ Hành động khắc phục đã bị từ chối. Hệ thống chuyển sang chế độ Manual Mode."}
        
    return {"status": "ok"}


@app.post("/slack/interactive")
async def handle_slack_approval(request: Request):
    """
    Endpoint nhận tín hiệu phản hồi khi người dùng bấm button [Approve] / [Reject] trên Slack.
    """
    form_data = await request.form()
    payload = json.loads(form_data.get("payload", "{}"))
    
    actions = payload.get("actions", [])
    if not actions:
        return {"status": "ignored"}
        
    action = actions[0]
    action_id = action.get("action_id", "")
    value = action.get("value", "")  # "approve" hoặc "reject"
    
    # Lấy incident_id từ action_id (ví dụ: approve_INC-1719875400)
    parts = action_id.split("_")
    if len(parts) < 2:
        return {"status": "invalid"}
    incident_id = parts[1]
    
    logger.info(f"Slack action received: {value} for Incident {incident_id}")
    return await process_approval_action(incident_id, value)


# ==========================================
# LOCAL SANDBOX SIMULATION ENDPOINTS
# ==========================================
from fastapi import HTTPException

@app.post("/simulate/inject")
async def simulate_inject(scenario: str):
    if scenario not in ["stable", "inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew", "ml_proactive"]:
        raise HTTPException(status_code=400, detail="Invalid scenario")
    simulation_state["scenario"] = scenario
    simulation_state["start_time"] = time.time()
    simulation_state["remediated"] = False
    logger.info(f"[SIMULATION] Injected scenario: {scenario}")
    return {"status": "injected", "scenario": scenario}

@app.post("/simulate/approve")
async def simulate_approve(incident_id: str = None):
    if not active_incidents:
        raise HTTPException(status_code=400, detail="No active incidents in memory.")
    if not incident_id:
        incident_id = list(active_incidents.keys())[-1]
    logger.info(f"[SIMULATION] Manually approving Incident {incident_id} via simulation endpoint")
    res = await process_approval_action(incident_id, "approve")
    return {"status": "approved", "incident_id": incident_id, "result": res}

@app.post("/simulate/remediate")
async def simulate_remediate():
    simulation_state["remediated"] = True
    logger.info(f"[SIMULATION] Remediation command received. Setting remediated=True")
    return {"status": "remediated"}

@app.get("/simulate/state")
async def simulate_state_endpoint():
    return simulation_state

@app.get("/mock-prometheus/api/v1/query")
async def mock_prometheus_query(query: str):
    val = 0.0
    scenario = simulation_state["scenario"]
    remediated = simulation_state["remediated"]
    
    # 1. Trả về burn rate hoặc lỗi 5xx
    if "5.." in query or "http_status_code" in query:
        if scenario in ["inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew"] and not remediated:
            # Trả về tỷ lệ lỗi 18.5% (đủ để burn rate >= 14.4)
            val = 18.5
        else:
            # Dao động nhỏ bình thường
            import random
            val = 0.01 + random.random() * 0.05
    
    # 2. Trả về Z-score check
    elif "active_requests" in query or "prometheus_http_requests_total" in query or "consumer_lag" in query:
        if "avg_over_time" in query:
            val = 1.0  # baseline mean
        elif "stddev_over_time" in query:
            val = 0.5  # baseline stddev
        else:
            # current value
            if scenario in ["inc1", "inc2", "inc3", "inc4", "inc5", "inc6", "inc7", "inc8", "incnew"] and not remediated:
                val = 120.0  # spike
            else:
                import random
                val = 1.0 + random.random() * 0.5  # normal
                
    # 3. Mặc định cho query "up" hoặc khác
    else:
        val = 1.0
        
    return {
        "status": "success",
        "data": {
          "resultType": "vector",
          "result": [
            {
              "metric": {"__name__": "mock_metric"},
              "value": [time.time(), str(val)]
            }
          ]
        }
    }

@app.get("/mock-jaeger/api/traces/{trace_id}")
async def mock_jaeger_trace(trace_id: str):
    scenario = simulation_state["scenario"]
    inc_num = "inc3"
    if "inc" in trace_id:
        inc_num = trace_id.split("-")[-1]
    elif scenario != "stable":
        inc_num = scenario
        
    fixture_path = f"fixtures/{inc_num}_trace_response.json"
    if not os.path.exists(fixture_path):
        fixture_path = f"aiops-engine/{fixture_path}"
        
    if os.path.exists(fixture_path):
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"data": []}

@app.post("/mock-opensearch/otel-logs-*/_search")
async def mock_opensearch_logs(request: Request):
    scenario = simulation_state["scenario"]
    remediated = simulation_state["remediated"]
    
    req_body = await request.json()
    service_name = "unknown"
    try:
        must_clauses = req_body.get("query", {}).get("bool", {}).get("must", [])
        for clause in must_clauses:
            if "resource.service.name" in clause.get("match", {}):
                service_name = clause["match"]["resource.service.name"]
    except Exception:
        pass
        
    # Nếu đang stable hoặc đã remediated: trả về log INFO bình thường
    if scenario == "stable" or remediated:
        import datetime
        normal_logs = [
            {
              "_index": "otel-logs-mock",
              "_source": {
                "body": f"HTTP GET /cart success for service {service_name}",
                "resource": {"service.name": service_name},
                "@timestamp": datetime.datetime.utcnow().isoformat() + "Z"
              }
            },
            {
              "_index": "otel-logs-mock",
              "_source": {
                "body": f"Transaction completed successfully in 12ms",
                "resource": {"service.name": service_name},
                "@timestamp": datetime.datetime.utcnow().isoformat() + "Z"
              }
            }
        ]
        return {
            "hits": {
                "hits": normal_logs
            }
        }
        
    # Nếu đang có incident và chưa remediated: trả về log lỗi tương ứng
    fixture_path = f"fixtures/{scenario}_logs.json"
    if not os.path.exists(fixture_path):
        fixture_path = f"aiops-engine/{fixture_path}"
        
    if os.path.exists(fixture_path):
        with open(fixture_path, "r", encoding="utf-8") as f:
            raw_logs = json.load(f)
        hits = []
        for log in raw_logs:
            hits.append({
                "_index": "otel-logs-mock",
                "_source": {
                    "body": log.get("body", "") or log.get("message", ""),
                    "resource": {"service.name": service_name},
                    "@timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                }
            })
        return {
            "hits": {
                "hits": hits
            }
        }
    return {"hits": {"hits": []}}

# --- ENDPOINT TEST ANOMALY MACHINE LEARNING (ISOLATION FOREST) ---
class MetricPayload(BaseModel):
    service: str
    rps: float
    cpu_usage: float
    memory_usage: float
    latency_p90: float
    error_rate: float

@app.post("/anomaly/predict")
async def predict_metric_anomaly(payload: MetricPayload):
    service = payload.service
    if service not in detector.models:
        return {
            "status": "error",
            "message": f"No Isolation Forest model loaded for service: {service}. Available: {list(detector.models.keys())}"
        }
    
    # 1. Tạo baseline 12 mẫu normal để làm nền tính toán rolling features
    baseline_rows = []
    base_time = datetime.datetime.now() - datetime.timedelta(hours=1)
    
    for i in range(12):
        baseline_rows.append({
            "timestamp": base_time + datetime.timedelta(minutes=5 * i),
            "service": service,
            "rps": 80.0,
            "cpu_usage": 0.35,
            "memory_usage": 0.50,
            "latency_p90": 0.05,
            "error_rate": 0.001
        })
        
    # Thêm payload hiện tại vào dòng thứ 13
    baseline_rows.append({
        "timestamp": datetime.datetime.now(),
        "service": service,
        "rps": payload.rps,
        "cpu_usage": payload.cpu_usage,
        "memory_usage": payload.memory_usage,
        "latency_p90": payload.latency_p90,
        "error_rate": payload.error_rate
    })
    
    import pandas as pd
    df_raw = pd.DataFrame(baseline_rows)
    
    # 2. Áp dụng feature engineering (14 đặc trưng)
    from train_anomaly_model_local import feature_engineering as local_fe
    df_features = local_fe(df_raw)
    
    feature_cols = [
        "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate",
        "error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth",
        "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
    ]
    
    # Lấy vector hàng cuối cùng đại diện cho payload
    X_t = df_features[feature_cols].iloc[-1].values.reshape(1, -1)
    
    # 3. Dự đoán trực tiếp bằng model
    model = detector.models[service]
    prediction = int(model.predict(X_t)[0])
    score = float(model.decision_function(X_t)[0])
    
    return {
        "status": "success",
        "service": service,
        "prediction": prediction, # 1: Normal, -1: Anomaly
        "anomaly_detected": True if prediction == -1 else False,
        "anomaly_score": score,
        "features": df_features[feature_cols].iloc[-1].to_dict()
    }

@app.post("/reload-models")
async def reload_models():
    """Hot-reloads Isolation Forest models from S3 without restarting the container."""
    try:
        detector._load_models_from_s3()
        return {
            "status": "success",
            "message": "Successfully hot-reloaded all Isolation Forest models from S3.",
            "loaded_models": list(detector.iforest_models.keys())
        }
    except Exception as e:
        logger.error(f"Failed to reload models: {e}")
        return {
            "status": "error",
            "message": f"Failed to reload models: {str(e)}"
        }

