import os
import time
import logging
import asyncio
import json
import subprocess
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
from anomaly_detector import AnomalyDetector
from rca_engine import RCAEngine
from evidence_collector import EvidenceCollector
from llm_diagnostician import LLMDiagnostician
from remediation_handler import RemediationHandler
from slack_notifier import SlackNotifier
from alert_correlator import AlertCorrelator
from audit_logger import audit_logger


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
correlator = AlertCorrelator(window_seconds=600)  # 10 phút — đủ bao phủ cascade failure chậm

# Bộ đếm số lần chạy hành động chống chạy lặp vô hạn (C6 Invariant 4)
action_counters = {}  # {incident_id: count}
active_incidents = {}  # {incident_id: diagnosis_dict}
emergency_stop_state = {"active": False, "stopped_at": 0, "reason": ""}
AUTO_REMEDIATION_LIVE_TEST = os.getenv("AUTO_REMEDIATION_LIVE_TEST", "false").lower() == "true"
last_proactive_alert_time = {}  # {service_name: timestamp} (Chống alert fatigue)

# Rolling Alert Buffer — lưu trữ các ML anomaly alert trong 15 phút trượt
# Mỗi entry: {"service": str, "fired_at": float, "trace_id": str, "alertname": str, "severity": str}
# Mục đích: giải quyết vấn đề mock_alerts = [] bị reset mỗi chu kỳ 30s
# → correlator nhìn thấy đủ context 15 phút để gom cluster đúng
ROLLING_ALERT_BUFFER_SECONDS = 900  # 15 phút
rolling_alert_buffer: list[dict] = []

# Cấu hình Sandbox Giả lập (Local Chaos Sandbox)
import datetime
import os
from config import SIMULATION_STATE
simulation_state = SIMULATION_STATE

# Cấu hình Active Metrics Polling Loop (Chế độ tự động quét chủ động - Mode B)
ACTIVE_POLLING_ENABLED = True
POLLING_INTERVAL_SECONDS = 30


def enrich_culprit_with_upstream_check(trigger_service: str, lookback_minutes: int = 15) -> str:
    """
    RCA Telemetry Enrichment Full-Scan (5 Core Metrics):
      1. Latency P90 (Trễ mạng/Timeout)
      2. Error Rate (Lỗi 5xx/gRPC)
      3. CPU Usage Saturation (Quá tải CPU)
      4. Memory Usage % (Bội nạp bộ nhớ/OOM)
      5. Kafka Consumer Lag (Nghẽn hàng đợi)
      + Trọng số độ sâu hạ nguồn (Depth Weighting)
    """
    if os.getenv("AIOPS_SIMULATION_MODE") == "true":
        return trigger_service

    if trigger_service not in correlator.nx_graph:
        logger.debug(f"[UpstreamCheck] {trigger_service} not in topology graph, skipping.")
        return trigger_service

    import networkx as nx
    related_services = set(nx.descendants(correlator.nx_graph, trigger_service)) | set(nx.ancestors(correlator.nx_graph, trigger_service))
    if not related_services:
        return trigger_service

    logger.info(f"[UpstreamCheck] Full 5-Factor Telemetry Audit for {trigger_service} across {len(related_services)} service(s): {list(related_services)}")

    best_culprit = trigger_service
    highest_score = 0.0
    all_candidates = [trigger_service] + list(related_services)

    for svc in all_candidates:
        lat_query = (
            f'max_over_time('
            f'(histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{{'
            f'service_name="{svc}",span_kind="SPAN_KIND_SERVER"}}[5m])) by (le)) or vector(0))'
            f'[{lookback_minutes}m:]) / 1000.0'
        )
        err_query = (
            f'max_over_time('
            f'(sum(rate(traces_span_metrics_calls_total{{'
            f'service_name="{svc}",span_kind="SPAN_KIND_SERVER",'
            f'status_code="STATUS_CODE_ERROR"}}[5m])) or vector(0))'
            f'[{lookback_minutes}m:])'
        )
        cpu_query = f'max_over_time((sum(rate(container_cpu_usage_seconds_total{{container="{svc}"}}[5m])) or vector(0))[{lookback_minutes}m:])'
        mem_query = f'max_over_time((sum(container_memory_working_set_bytes{{container="{svc}"}}) / (sum(container_spec_memory_limit_bytes{{container="{svc}"}}) or vector(1)) * 100 or vector(0))[{lookback_minutes}m:])'
        lag_query = f'max_over_time((sum(kafka_consumer_records_lag{{service_name="{svc}"}}) or vector(0))[{lookback_minutes}m:])'

        lat_val = detector.parse_query_value(detector.query_prometheus(lat_query))
        err_val = detector.parse_query_value(detector.query_prometheus(err_query))
        cpu_val = detector.parse_query_value(detector.query_prometheus(cpu_query))
        mem_val = detector.parse_query_value(detector.query_prometheus(mem_query))
        lag_val = detector.parse_query_value(detector.query_prometheus(lag_query))

        depth = len(nx.descendants(correlator.nx_graph, svc)) if svc in correlator.nx_graph else 0
        depth_weight = 1.0 / (depth + 1.0)
        
        score = (
            (lat_val * 2.0) +
            (err_val * 10.0) +
            (cpu_val * 1.5) +
            (mem_val * 0.05) +
            (lag_val * 0.01)
        ) * (1.0 + depth_weight)

        logger.info(
            f"[UpstreamCheck] Candidate {svc}: lat={lat_val:.2f}s, err={err_val:.3f}, cpu={cpu_val:.2f}, mem={mem_val:.1f}%, lag={lag_val:.0f}, depth={depth} → score={score:.2f}"
        )

        if score > highest_score:
            highest_score = score
            best_culprit = svc

    if best_culprit != trigger_service and highest_score > 1.0:
        logger.warning(
            f"[UpstreamCheck] ROOT CAUSE ENRICHED: {trigger_service} → {best_culprit} "
            f"(highest_anomaly_score={highest_score:.2f} in last {lookback_minutes}m)"
        )
        return best_culprit

    return trigger_service

async def active_metrics_polling_loop():
    logger.info("Starting Active Metrics Polling Loop (Mode B)...")
    await asyncio.sleep(5)  # Đợi uvicorn khởi tạo xong cổng kết nối
    while ACTIVE_POLLING_ENABLED:
        try:
            # Auto-expire incidents older than 10 minutes (600 seconds) to prevent polling lockup
            now_ts = time.time()
            stale_incidents = [
                inc_id for inc_id, inc_data in list(active_incidents.items())
                if now_ts - inc_data.get("created_at", now_ts) > 600
            ]
            for inc_id in stale_incidents:
                logger.info(f"[AutoExpire] Incident {inc_id} expired after 10m timeout. Removing from active cache.")
                active_incidents.pop(inc_id, None)

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

                # Xóa service đã hồi phục khỏi rolling buffer
                resolved_services = {
                    e["service"] for e in rolling_alert_buffer
                    if e["service"] not in anomalous_services
                }
                if resolved_services:
                    rolling_alert_buffer[:] = [
                        e for e in rolling_alert_buffer
                        if e["service"] not in resolved_services
                    ]
                    logger.info(f"[RollingBuffer] Removed resolved services: {resolved_services}")
                        
                if anomalous_services:
                    now_ts = time.time()

                    # === ROLLING ALERT BUFFER ===
                    # Push các service vừa phát hiện vào buffer với fired_at thực tế
                    for service in anomalous_services:
                        if simulation_state["scenario"].startswith("inc"):
                            trace_id = f"mock-{simulation_state['scenario']}"
                        else:
                            trace_id = rca_engine.fetch_latest_trace_id(service)

                        # Chỉ thêm vào buffer nếu service chưa có entry trong 30s gần nhất
                        # (tránh duplicate cùng service qua nhiều chu kỳ liên tiếp)
                        already_recent = any(
                            e["service"] == service and (now_ts - e["fired_at"]) < POLLING_INTERVAL_SECONDS
                            for e in rolling_alert_buffer
                        )
                        if not already_recent:
                            rolling_alert_buffer.append({
                                "labels": {"service": service, "alertname": "MLProactiveAnomaly", "severity": "warning"},
                                "annotations": {"trace_id": trace_id},
                                "service": service,
                                "fired_at": last_proactive_alert_time.get(service, now_ts),
                                "trace_id": trace_id,
                                "alertname": "MLProactiveAnomaly",
                                "severity": "warning"
                            })
                            logger.info(f"[RollingBuffer] Added {service} to buffer (total={len(rolling_alert_buffer)})")

                    # Prune entries cũ hơn ROLLING_ALERT_BUFFER_SECONDS (15 phút)
                    rolling_alert_buffer[:] = [
                        e for e in rolling_alert_buffer
                        if now_ts - e["fired_at"] <= ROLLING_ALERT_BUFFER_SECONDS
                    ]
                    logger.info(
                        f"[RollingBuffer] After prune: {len(rolling_alert_buffer)} entries "
                        f"covering services: {sorted({e['service'] for e in rolling_alert_buffer})}"
                    )

                    # Truyền TOÀN BỘ buffer (15 phút) cho correlator thay vì chỉ chu kỳ hiện tại
                    # → correlator nhìn thấy recommendation (10:12) + frontend-proxy (10:13)
                    #   trong cùng 1 window → gom đúng 1 cluster, bắn đúng 1 Slack
                    clusters = correlator.correlate_alerts_windowed(rolling_alert_buffer)
                    
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
    """
    Tự động rebuild topology từ Jaeger mỗi 24 giờ, rồi hot-reload vào correlator.

    Chu kỳ:
      - Mỗi 24h: chạy rebuild_topology_from_jaeger() để cập nhật services.json
        từ trace thực tế — bắt được các dependency mới hoặc thay đổi kiến trúc.
      - Mỗi 5 phút: reload services.json vào RAM (hot-reload, không query Jaeger).

    Nếu Jaeger không accessible, giữ nguyên services.json hiện tại.
    """
    REBUILD_INTERVAL_SECONDS = 86400   # 24 giờ
    RELOAD_INTERVAL_SECONDS  = 300     # 5 phút
    last_rebuild_time = 0.0

    while True:
        await asyncio.sleep(RELOAD_INTERVAL_SECONDS)
        now = time.time()

        # Rebuild topology từ Jaeger mỗi 24h
        if now - last_rebuild_time >= REBUILD_INTERVAL_SECONDS:
            logger.info("Periodic Topology Rebuild: querying Jaeger to rebuild services.json...")
            try:
                # Import và chạy builder trong executor để không block event loop
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _rebuild_topology_background)
                last_rebuild_time = now
                logger.info("Topology rebuild complete.")
            except Exception as e:
                logger.error(f"Topology rebuild failed: {e}. Keeping existing services.json.")

        # Hot-reload services.json vào RAM mỗi 5 phút
        logger.info("Periodic Graph Reload: reloading service graph from disk...")
        correlator.reload_graph()


def _rebuild_topology_background():
    """
    Wrapper chạy trong ThreadPoolExecutor để rebuild topology từ Jaeger và upload S3.
    Quy trình:
      1. Query Jaeger lấy traces của tất cả services
      2. Extract edges từ CHILD_OF span relationships
      3. Merge với services.json hiện tại
      4. Ghi local (services.json) + upload S3 (topology/services.json)
    Khi hoàn thành, correlator.reload_graph() sẽ pick up từ S3 trong chu kỳ 5 phút tiếp theo.
    """
    script_path = os.path.join(os.path.dirname(__file__), "scripts", "rebuild_topology_from_jaeger.py")
    services_json_path = os.path.join(os.path.dirname(__file__), "services.json")

    if not os.path.exists(script_path):
        logger.warning(f"Topology rebuild script not found: {script_path}")
        return

    result = subprocess.run(
        ["python", script_path,
         "--output", services_json_path,
         "--limit", "30"],   # 30 traces/service để nhẹ nhàng với Jaeger
        capture_output=True,
        text=True,
        timeout=120   # tối đa 2 phút
    )
    if result.returncode == 0:
        logger.info(f"Topology rebuild success:\n{result.stdout[-800:]}")
    else:
        logger.error(f"Topology rebuild failed (returncode={result.returncode}):\n{result.stderr[-500:]}")


@app.post("/topology/rebuild")
async def trigger_topology_rebuild():
    """
    Endpoint kích hoạt thủ công việc rebuild topology từ Jaeger traces.
    Hữu ích sau khi deploy service mới hoặc thay đổi kiến trúc.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _rebuild_topology_background)
        return {
            "status": "triggered",
            "message": "Topology rebuild from Jaeger started in background. "
                       "Check logs for progress. Graph will hot-reload within 5 minutes."
        }
    except Exception as e:
        logger.error(f"Failed to trigger topology rebuild: {e}")
        return {"status": "error", "message": str(e)}

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

    # [Upstream Health Check] Nếu culprit chỉ là service bị trigger mà không có context
    # upstream rõ ràng từ correlator, thử Prometheus lookback để enrich culprit
    enriched_culprit = enrich_culprit_with_upstream_check(culprit_service, lookback_minutes=15)
    if enriched_culprit != culprit_service:
        logger.warning(
            f"[Incident {incident_id}] Culprit enriched via Prometheus upstream check: "
            f"{culprit_service} → {enriched_culprit}"
        )
        culprit_service = enriched_culprit

    # 1. Giai đoạn 3: Gom logs và traces làm Bằng chứng (Evidence Pack)
    logger.info("Step 1: Generating Evidence Pack...")
    evidence = evidence_collector.build_evidence_pack(culprit_service, alert_time, trace_id)
    
    # 2. Giai đoạn 4: Gọi Bedrock Chẩn đoán
    logger.info("Step 2: Invoking LLM Bedrock Diagnostician...")
    diagnosis = diagnostician.diagnose(evidence)
    
    # Bổ sung thông tin bổ sung vào diagnosis trước khi phân loại rủi ro
    diagnosis["incident_id"] = incident_id
    diagnosis["culprit_service"] = culprit_service
    diagnosis["trace_id"] = trace_id
    diagnosis["trace_analysis"] = evidence.get("trace_analysis", culprit_service)
    
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

    # [Mandate #22] 1. Tính toán Blast Radius % (chỉ trên 7 Application Services)
    blast_radius = correlator.calculate_blast_radius(culprit_service)
    confidence_score = float(diagnosis.get("confidence_score", 1.0))
    logger.info(f"Remediation Safety Check - Service: {culprit_service}, Action: {proposed_action}, Blast Radius: {blast_radius}%, Confidence: {confidence_score * 100}%")

    # [Mandate #22] 2. Ma Trận Phân Loại Rủi Ro (Risk Assessment Matrix)
    # BASE RISK: scale, restart, cache-flush, breaker-force -> BASE = LOW
    current_risk = "LOW" if proposed_action in ["scale", "restart", "cache-flush", "breaker-force"] else "HIGH"

    # ELEVATE TO MEDIUM RISK IF:
    # 1. blast_radius > 60% AND action is restart/scale
    # 2. confidence_score < 0.80
    # 3. culprit_service == "frontend" (Main Gateway entrypoint affecting 100% users)
    if current_risk == "LOW":
        if proposed_action in ["scale", "restart"] and blast_radius > 60.0:
            logger.warning(f"Blast radius {blast_radius}% > 60%. Elevating LOW RISK action to MEDIUM RISK for safety.")
            current_risk = "MEDIUM"
        elif confidence_score < 0.80:
            logger.warning(f"Confidence score {confidence_score:.2f} < 0.80. Elevating LOW RISK action to MEDIUM RISK for safety.")
            current_risk = "MEDIUM"
        elif culprit_service == "frontend":
            logger.warning("Culprit service is 'frontend' (Main Gateway). Elevating to MEDIUM RISK for safety.")
            current_risk = "MEDIUM"

    diagnosis["risk_level"] = current_risk
    diagnosis["blast_radius"] = blast_radius

    if current_risk == "LOW":
        # Mức LOW RISK: Tự động dập khép kín (Auto-Execute) theo Mandate #22
        logger.info(f"[Mandate #22] Action '{proposed_action}' on {culprit_service} classified as LOW RISK. Starting Safety Check...")

        # 2.1 Cổng Dry-Run Check trước khi thực thi lệnh thật
        logger.info(f"[Safety Gate 1] Running Dry-Run check: {action_command}")
        dry_run_passed = handler.execute_k8s_command(action_command, dry_run=True)

        if not dry_run_passed:
            logger.error(f"[Safety Gate 1 FAILED] Dry-run failed for command: {action_command}. Aborting execution.")
            audit_logger.log_remediation_event(
                incident_id=incident_id,
                trigger="IncidentDetected",
                culprit_service=culprit_service,
                proposed_action=proposed_action,
                action_command=action_command,
                blast_radius_percent=blast_radius,
                risk_level="LOW",
                dry_run_passed=False,
                executed=False,
                verification_passed=False,
                rollback_executed=False,
                status="DRY_RUN_FAILED",
                message="Dry-run command execution failed safety check"
            )
            active_incidents.pop(incident_id, None)
            return

        # 2.2 Thực thi lệnh thật (Live Action Execution)
        logger.info(f"[Safety Gate 1 PASSED] Dry-run succeeded. Executing live command: {action_command}")
        executed_success = handler.execute_k8s_command(action_command, dry_run=False)

        if not executed_success:
            logger.error(f"Live command execution failed: {action_command}")
            audit_logger.log_remediation_event(
                incident_id=incident_id,
                trigger="IncidentDetected",
                culprit_service=culprit_service,
                proposed_action=proposed_action,
                action_command=action_command,
                blast_radius_percent=blast_radius,
                risk_level="LOW",
                dry_run_passed=True,
                executed=False,
                verification_passed=False,
                rollback_executed=False,
                status="EXECUTION_FAILED",
                message="Live command execution failed"
            )
            active_incidents.pop(incident_id, None)
            return

        # 2.3 Verify Telemetry thật trong 5 phút
        logger.info(f"Starting Telemetry Verification for {culprit_service}...")
        is_resolved = handler.verify_remediation(culprit_service)

        if is_resolved:
            logger.info(f"✅ Self-Remediation SUCCESS! Service {culprit_service} recovered safely.")
            audit_logger.log_remediation_event(
                incident_id=incident_id,
                trigger="IncidentDetected",
                culprit_service=culprit_service,
                proposed_action=proposed_action,
                action_command=action_command,
                blast_radius_percent=blast_radius,
                risk_level="LOW",
                dry_run_passed=True,
                executed=True,
                verification_passed=True,
                rollback_executed=False,
                status="REMEDIATION_SUCCESS",
                message="Telemetry verification passed. Service restored."
            )
            active_incidents.pop(incident_id, None)
        else:
            # 2.4 TỰ ĐỘNG ROLLBACK khi Verify FAIL (Mandate #22 requirement)
            logger.warning(f"⚠️ Telemetry Verification FAILED for {culprit_service}! Triggering AUTO-ROLLBACK: {rollback_command}")
            rollback_passed = handler.trigger_rollback(rollback_command)

            if rollback_passed:
                logger.info(f"🔄 AUTO-ROLLBACK SUCCESSFUL for {culprit_service} using command: {rollback_command}")
                audit_logger.log_remediation_event(
                    incident_id=incident_id,
                    trigger="IncidentDetected",
                    culprit_service=culprit_service,
                    proposed_action=proposed_action,
                    action_command=action_command,
                    blast_radius_percent=blast_radius,
                    risk_level="LOW",
                    dry_run_passed=True,
                    executed=True,
                    verification_passed=False,
                    rollback_executed=True,
                    rollback_command=rollback_command,
                    rollback_passed=True,
                    status="ROLLED_BACK_SUCCESSFULLY",
                    message="Verification failed. Auto-rollback executed successfully."
                )
            else:
                logger.critical(f"🚨 AUTO-ROLLBACK FAILED for {culprit_service}! Escalating to SRE!")
                handler.escalate(incident_id, culprit_service, proposed_action)
                audit_logger.log_remediation_event(
                    incident_id=incident_id,
                    trigger="IncidentDetected",
                    culprit_service=culprit_service,
                    proposed_action=proposed_action,
                    action_command=action_command,
                    blast_radius_percent=blast_radius,
                    risk_level="LOW",
                    dry_run_passed=True,
                    executed=True,
                    verification_passed=False,
                    rollback_executed=True,
                    rollback_command=rollback_command,
                    rollback_passed=False,
                    status="ROLLBACK_FAILED_ESCALATED",
                    message="Verification failed and auto-rollback failed. Escalated to SRE."
                )
            active_incidents.pop(incident_id, None)

    elif current_risk == "MEDIUM":
        # Mức MEDIUM RISK: Gửi Slack chờ Approve
        logger.info(f"Action '{proposed_action}' classified as MEDIUM RISK (Blast Radius: {blast_radius}%, Culprit: {culprit_service}). Sending Slack card...")
        notifier.send_incident_notification(incident_id, diagnosis)

    else:
        # Mức HIGH RISK hoặc lệnh lạ: Tự động từ chối
        logger.warning(f"Action '{proposed_action}' classified as HIGH RISK. Rejecting automatically.")
        diagnosis["analysis"] = f"[AUTO-REJECTED] Dangerous/Uncertain command blocked: {diagnosis['analysis']}"
        notifier.send_incident_notification(incident_id, diagnosis)
        active_incidents.pop(incident_id, None)




def process_proactive_anomaly_background(incident_id: str, culprit_service: str, trace_id: str, alert_time: float):
    """
    Chạy chẩn đoán sớm cho máy học: Gọi Bedrock LLM để phân tích chuyên sâu
    và đề xuất hành động khắc phục, nhưng ép buộc mức rủi ro là MEDIUM
    để SRE phê duyệt thủ công qua Slack, không bao giờ tự động hành động.
    """
    logger.info(f"--- [PROACTIVE ML WARNING] Processing early anomaly for {culprit_service} ({incident_id}) ---")

    # [Upstream Health Check] Với proactive scan, culprit là service IF phát hiện lỗi.
    # Tuy nhiên lỗi có thể bắt nguồn từ upstream dependency — enrich trước khi chạy pipeline.
    enriched_culprit = enrich_culprit_with_upstream_check(culprit_service, lookback_minutes=15)
    if enriched_culprit != culprit_service:
        logger.warning(
            f"[Proactive {incident_id}] Culprit enriched via Prometheus upstream check: "
            f"{culprit_service} → {enriched_culprit}"
        )
        culprit_service = enriched_culprit
    
    # 1. Thu thập bằng chứng
    logger.info("[PROACTIVE] Step 1: Generating Evidence Pack...")
    evidence = evidence_collector.build_evidence_pack(culprit_service, alert_time, trace_id)
    
    # 2. Gọi Bedrock Chẩn đoán
    logger.info("[PROACTIVE] Step 2: Invoking LLM Bedrock Diagnostician...")
    diagnosis = diagnostician.diagnose(evidence)
    
    # Bổ sung thông tin bổ sung vào diagnosis
    diagnosis["incident_id"] = incident_id
    diagnosis["culprit_service"] = culprit_service
    diagnosis["status"] = "proactive_warning"
    diagnosis["alert_time"] = alert_time
    diagnosis["trace_id"] = trace_id
    diagnosis["trace_analysis"] = evidence.get("trace_analysis", culprit_service)
    
    proposed_action = diagnosis.get("proposed_action", "none")
    
    # Mẫu lệnh chuẩn hóa an toàn
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
        logger.warning("[PROACTIVE] Action failed safety validation gate. Rejecting.")
        diagnosis["analysis"] = f"[SAFETY REJECTED] {diagnosis['analysis']}"
        diagnosis["action_command"] = "Command blocked due to C6 policy violation."
        notifier.send_incident_notification(incident_id, diagnosis)
        return
        
    # Ép buộc rủi ro là MEDIUM để tuyệt đối không tự động chạy
    logger.info(f"[PROACTIVE] Action '{proposed_action}' forced to MEDIUM RISK for manual SRE approval.")
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
    diagnosis["trace_id"] = evidence.get("trace_id", "unknown-trace-id")
    diagnosis["trace_analysis"] = evidence.get("trace_analysis", culprit_service)
    
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
    diagnosis["created_at"] = time.time()
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
        
    # BUG 1+2 FIX: Dùng correlate_alerts_windowed để gom nhóm theo time-window
    # và chọn culprit bằng upstream NetworkX topology scoring
    # Alertmanager truyền fired_at qua label "startsAt" — normalize về float timestamp
    for alert in raw_alerts:
        if "fired_at" not in alert:
            starts_at_str = alert.get("labels", {}).get("startsAt", "")
            if starts_at_str:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(starts_at_str.replace("Z", "+00:00"))
                    alert["fired_at"] = dt.timestamp()
                except Exception:
                    alert["fired_at"] = time.time()
            else:
                alert["fired_at"] = time.time()
    clusters = correlator.correlate_alerts_windowed(raw_alerts)
    
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
    if emergency_stop_state["active"]:
        logger.warning(f"Emergency stop is ACTIVE! Rejecting remediation for {incident_id}.")
        return {"text": f"🛑 CẢNH BÁO: Nút phanh khẩn cấp đang BẬT! Lệnh khắc phục cho {incident_id} đã bị ngắt an toàn."}
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
    Endpoint nhận tín hiệu phản hồi khi người dùng bấm button [Approve] / [Reject] / [Emergency Stop] trên Slack.
    """
    form_data = await request.form()
    payload = json.loads(form_data.get("payload", "{}"))
    
    actions = payload.get("actions", [])
    if not actions:
        return {"status": "ignored"}
        
    action = actions[0]
    action_id = action.get("action_id", "")
    value = action.get("value", "")  # "approve", "reject", hoặc "emergency_stop"
    
    if action_id.startswith("emergency_stop") or value == "emergency_stop":
        emergency_stop_state["active"] = True
        emergency_stop_state["stopped_at"] = time.time()
        emergency_stop_state["reason"] = f"Operator pressed Slack Emergency Stop button for {action_id}"
        active_incidents.clear()
        logger.error(f"[EMERGENCY STOP] Triggered via Slack Button for {action_id}")
        return {"text": "🛑 NÚT PHANH KHẨN CẤP ĐÃ KÍCH HOẠT! Toàn bộ luồng Remediation & Re-planning đã bị HỦY ngay lập tức!"}
        
    parts = action_id.split("_")
    if len(parts) < 2:
        return {"status": "invalid"}
    incident_id = parts[1]
    
    logger.info(f"Slack action received: {value} for Incident {incident_id}")
    return await process_approval_action(incident_id, value)


@app.post("/remediation/stop")
async def emergency_stop_remediation(reason: str = "Manual Emergency Brake Activated"):
    """
    NÚT PHANH NGUYÊN CẤP: Dừng ngay lập tức toàn bộ hành động khắc phục của Engine.
    """
    emergency_stop_state["active"] = True
    emergency_stop_state["stopped_at"] = time.time()
    emergency_stop_state["reason"] = reason
    active_incidents.clear()
    logger.error(f"[EMERGENCY STOP] Remediation halted immediately by operator! Reason: {reason}")
    return {
        "status": "EMERGENCY_STOP_ACTIVATED",
        "message": "Toàn bộ luồng Remediation và Re-planning đã bị DỪNG KHẨN CẤP lập tức!",
        "reason": reason
    }

@app.post("/remediation/resume")
async def resume_remediation():
    """
    Mở lại hệ thống Remediation sau khi kiểm tra xong.
    """
    emergency_stop_state["active"] = False
    emergency_stop_state["reason"] = ""
    logger.info("[EMERGENCY RESUME] Operator resumed Remediation Engine.")
    return {
        "status": "REMEDIATION_RESUMED",
        "message": "Engine Remediation đã được khôi phục hoạt động bình thường."
    }


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

@app.post("/remediation/approve")
async def remediation_approve(incident_id: str = None):
    return await simulate_approve(incident_id)

@app.post("/simulate/approve")
async def simulate_approve(incident_id: str = None):
    """
    Endpoint phê duyệt hành động khắc phục cho sự cố đang ở trạng thái pending.
    """
    if not active_incidents:
        raise HTTPException(status_code=400, detail="No active incidents in memory.")
    if not incident_id:
        incident_id = list(active_incidents.keys())[-1]
    logger.info(f"[REMEDIATION APPROVE] Manually approving Incident {incident_id}")
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


from typing import List

class MetricPoint(BaseModel):
    timestamp: str
    rps: float
    cpu_usage: float
    memory_usage: float
    latency_p90: float
    error_rate: float
    client_error_rate: float
    kafka_lag: float
    label: int

class ReplayPayload(BaseModel):
    service: str
    data: List[MetricPoint]

@app.post("/simulate/replay")
async def simulate_replay(payload: ReplayPayload):
    import pandas as pd
    import numpy as np
    
    service = payload.service
    records = [p.model_dump() for p in payload.data]
    
    if not records:
        raise HTTPException(status_code=400, detail="Empty data list")
        
    # 1. Convert to DataFrame
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    # 2. Derived features calculation
    df["error_ratio"] = df["error_rate"] / (df["rps"] + 1e-5)
    df["client_error_ratio"] = df["client_error_rate"] / (df["rps"] + 1e-5)
    df["rolling_median_1h"] = df["latency_p90"].rolling(window=12, min_periods=1).median()
    df["latency_deviation"] = df["latency_p90"] / (df["rolling_median_1h"] + 1e-5)
    df["rps_delta"] = df["rps"] - df["rps"].shift(1).fillna(0)
    df["cpu_per_rps"] = df["cpu_usage"] / (df["rps"] + 1e-5)
    df["memory_growth"] = df["memory_usage"] - df["memory_usage"].shift(6).fillna(0)
    df["kafka_lag_growth"] = df["kafka_lag"] - df["kafka_lag"].shift(1).fillna(0)
    
    df["hour_of_day"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.weekday
    df["is_business_hours"] = ((df["hour_of_day"] >= 8) & (df["hour_of_day"] <= 18) & (df["day_of_week"] < 5)).astype(int)
    
    df["rolling_median_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).median()
    df["is_high_traffic_period"] = ((df["rps"] > 100) & (df["rps"] > 1.5 * df["rolling_median_rps_1h"])).astype(int)
    
    df = df.fillna(0)
    
    # 3. Model inference
    feature_cols = [
        "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
        "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
        "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
    ]
    
    predictions = []
    scores = []
    
    model = detector.models.get(service)
    
    for idx, row in df.iterrows():
        X_t = row[feature_cols].values.reshape(1, -1)
        if model:
            pred = int(model.predict(X_t)[0])
            score = float(model.decision_function(X_t)[0])
        else:
            pred = 1
            score = 0.0




        
        predictions.append(pred)
        scores.append(score)
    df["prediction"] = predictions
    df["anomaly_score"] = scores
    
    # Calculate SLO Burn Rate metrics for each row
    df["burn_rate_5m"] = df["error_ratio"] * 1000.0
    df["rolling_error_rate_1h"] = df["error_rate"].rolling(window=12, min_periods=1).mean()
    df["rolling_rps_1h"] = df["rps"].rolling(window=12, min_periods=1).mean()
    df["rolling_error_ratio_1h"] = df["rolling_error_rate_1h"] / (df["rolling_rps_1h"] + 1e-5)
    df["burn_rate_1h"] = df["rolling_error_ratio_1h"] * 1000.0
    df["slo_breached"] = (df["burn_rate_5m"] >= 14.4) & (df["burn_rate_1h"] >= 14.4)
    # 2-Layer AIOps Incident Classifier:
    # Layer 1: ML Isolation Forest Anomaly Detection (prediction == -1)
    # Layer 2: Multi-Window Multi-Burn-Rate SLO Breached OR High Latency/Kafka Lag (slo_breached | latency_p90 > 0.05 | kafka_lag > 10)
    # Combined: Incident Alert is triggered when ML Anomaly aligns with SLO Burn Rate breach or latency degradation
    df["has_health_degradation"] = df["slo_breached"] | (df["latency_p90"] > 0.05) | (df["kafka_lag"] > 10)
    df["incident_alert"] = ((df["prediction"] == -1) & df["has_health_degradation"]).map({True: -1, False: 1})



    # 4. Metrics evaluation (excluding warmup rows to let sliding window features stabilize)
    warmup = 12
    eval_df = df.iloc[warmup:] if len(df) > warmup else df
    
    # Combined 2-Layer Metrics (ML + SLO Gate)
    tp = int(((eval_df["incident_alert"] == -1) & (eval_df["label"] == -1)).sum())
    fp = int(((eval_df["incident_alert"] == -1) & (eval_df["label"] == 1)).sum())
    fn = int(((eval_df["incident_alert"] == 1) & (eval_df["label"] == -1)).sum())
    tn = int(((eval_df["incident_alert"] == 1) & (eval_df["label"] == 1)).sum())
    precision = float(tp) / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = float(tp) / (tp + fn) if (tp + fn) > 0 else 1.0

    # Pure ML (Isolation Forest Only) Metrics
    ml_tp = int(((eval_df["prediction"] == -1) & (eval_df["label"] == -1)).sum())
    ml_fp = int(((eval_df["prediction"] == -1) & (eval_df["label"] == 1)).sum())
    ml_fn = int(((eval_df["prediction"] == 1) & (eval_df["label"] == -1)).sum())
    ml_tn = int(((eval_df["prediction"] == 1) & (eval_df["label"] == 1)).sum())
    ml_precision = float(ml_tp) / (ml_tp + ml_fp) if (ml_tp + ml_fp) > 0 else 1.0
    ml_recall = float(ml_tp) / (ml_tp + ml_fn) if (ml_tp + ml_fn) > 0 else 1.0

    # Lead-Time calculation:
    first_label_idx = None
    first_pred_idx = None
    
    start_idx = warmup if len(df) > warmup else 0
    for idx in range(start_idx, len(df)):
        row = df.iloc[idx]
        if row["label"] == -1 and first_label_idx is None:
            first_label_idx = idx
        if row["incident_alert"] == -1 and first_pred_idx is None:
            first_pred_idx = idx

    lead_time_seconds = 0.0
    lead_time_cycles = 0
    if first_label_idx is not None and first_pred_idx is not None:
        lead_time_cycles = first_pred_idx - first_label_idx
        t_label = df.iloc[first_label_idx]["timestamp"]
        t_pred = df.iloc[first_pred_idx]["timestamp"]
        lead_time_seconds = (t_pred - t_label).total_seconds()
        
    results_detail = []
    for idx, row in df.iterrows():
        results_detail.append({
            "timestamp": row["timestamp"].isoformat(),
            "rps": float(row["rps"]),
            "latency_p90": float(row["latency_p90"]),
            "error_rate": float(row["error_rate"]),
            "label": int(row["label"]),
            "prediction": int(row["prediction"]),
            "anomaly_score": float(row["anomaly_score"]),
            "burn_rate_5m": float(row["burn_rate_5m"]),
            "burn_rate_1h": float(row["burn_rate_1h"]),
            "slo_breached": bool(row["slo_breached"])
        })
        
    return {
        "status": "evaluated",
        "service": service,
        "metrics": {
            "precision": precision,
            "recall": recall,
            "lead_time_cycles": lead_time_cycles,
            "lead_time_seconds": lead_time_seconds,
            "confusion_matrix": {
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "true_negatives": tn
            },
            "pure_ml": {
                "precision": ml_precision,
                "recall": ml_recall,
                "confusion_matrix": {
                    "true_positives": ml_tp,
                    "false_positives": ml_fp,
                    "false_negatives": ml_fn,
                    "true_negatives": ml_tn
                }
            },
            "combined_2layer": {
                "precision": precision,
                "recall": recall,
                "confusion_matrix": {
                    "true_positives": tp,
                    "false_positives": fp,
                    "false_negatives": fn,
                    "true_negatives": tn
                }
            },
            "slo_breaches_detected": int(eval_df["slo_breached"].sum())
        },
        "details": results_detail
    }

@app.get("/evaluate/live")
async def evaluate_live_eks(minutes: int = 60):
    """
    [Mandate #7b Real-time EKS Evaluator]
    Đo đạc chỉ số Precision, Recall và Lead-time trực tiếp từ dữ liệu Prometheus trên cụm EKS thực tế
    trong cửa sổ thời gian 'minutes' gần nhất khi thực hiện Fault Injection (bơm lỗi bằng flagd).
    """
    import time
    import pandas as pd
    import numpy as np
    
    end_time = time.time()
    start_time = end_time - (minutes * 60)
    
    services = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]
    
    tp_count = 0
    fp_count = 0
    fn_count = 0
    tn_count = 0
    k_incidents_detected = 0
    total_ground_truth_blocks = 0
    
    for service in services:
        try:
            df_feat = detector.extract_features_realtime(service)
            if not df_feat.empty and "timestamp" in df_feat.columns:
                df_window = df_feat[df_feat["timestamp"] >= pd.to_datetime(start_time, unit='s')].copy()
                if df_window.empty:
                    df_window = df_feat.copy()
                
                # Ground truth: Lỗi 5xx > 0.005 HOẶC Latency > 50ms HOẶC Kafka lag > 10
                gt = (df_window["error_rate"] > 0.005) | (df_window["latency_p90"] > 0.05) | (df_window["kafka_lag"] > 10)
                
                feature_cols = [
                    "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
                    "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
                    "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
                ]
                
                if service in detector.models:
                    model = detector.models[service]
                    X_data = df_window[feature_cols].fillna(0)
                    preds = model.predict(X_data)
                    is_pred_anomaly = (preds == -1)
                else:
                    is_pred_anomaly = np.array([False] * len(df_window))
                    
                for is_gt, is_pred in zip(gt, is_pred_anomaly):
                    if is_gt and is_pred:
                        tp_count += 1
                    elif not is_gt and is_pred:
                        fp_count += 1
                    elif is_gt and not is_pred:
                        fn_count += 1
                    else:
                        tn_count += 1
        except Exception as e:
            logger.warning(f"Error evaluating live telemetry for {service}: {e}")

    precision = float(tp_count) / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 1.0
    recall = float(tp_count) / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 1.0
    
    return {
        "status": "evaluated_live",
        "evaluation_window_minutes": minutes,
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "lead_time_seconds": 0.0,
            "confusion_matrix": {
                "true_positives": tp_count,
                "false_positives": fp_count,
                "false_negatives": fn_count,
                "true_negatives": tn_count
            }
        },
        "description": f"Real-time evaluation on EKS Prometheus telemetry across last {minutes} minutes."
    }

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


def run_retrain_and_hot_reload():
    """Chạy tiến trình huấn luyện mô hình thực tế và hot-reload sau khi hoàn tất."""
    logger.info(">>> [API TRIGGER] Starting background model retraining pipeline...")
    try:
        import train_anomaly_model_eks as trainer
        trainer.main()
        logger.info(">>> [API TRIGGER] Retraining completed. Hot-reloading models from S3...")
        detector._load_models_from_s3()
        logger.info(">>> [API TRIGGER] Models successfully retrained and hot-reloaded into memory!")
    except Exception as e:
        logger.error(f">>> [API TRIGGER] Retraining background task failed: {e}")


@app.post("/retrain")
async def trigger_retrain(background_tasks: BackgroundTasks):
    """
    Kích hoạt tiến trình retrain mô hình ML từ Prometheus trên cụm EKS
    và tự động hot-reload model mới vào RAM sau khi hoàn tất.
    """
    background_tasks.add_task(run_retrain_and_hot_reload)
    return {
        "status": "started",
        "message": "Automated ML retraining pipeline triggered in background. Models will hot-reload upon completion."
    }


# === [MANDATE #22] ENDPOINTS TỰ DẬP SỰ CỐ AN TOÀN (SAFE SELF-REMEDIATION & AUDIT LOGS) ===

class RemediateReplayPayload(BaseModel):
    scenario: str = "inc1"
    culprit_service: str = "shipping"
    force_verify_fail: bool = False  # Ép verify_remediation trả về False để test nhánh Auto-Rollback cho BTC!

@app.post("/simulate/remediate_replay")
async def trigger_remediate_replay(payload: RemediateReplayPayload):
    """
    [Mandate #22] Endpoint chuyên biệt Replay toàn bộ luồng Tự Dập Sự Cố Khép Kín (Self-Remediation Pipeline).
    Dành cho Ban Tổ Chức (BTC) chấm điểm end-to-end:
      Detect -> Blast Radius Check -> Dry-Run -> Auto Act -> Verify -> Rollback (nếu fail) -> Audit Log.
    """
    incident_id = f"INC-REPLAY-{int(time.time())}"
    culprit = payload.culprit_service
    scenario = payload.scenario
    
    logger.info(f"=== [MANDATE #22 REPLAY] Triggering Self-Remediation Replay for {culprit} ({scenario}) ===")
    
    # 1. Thu thập chứng cứ & chẩn đoán
    evidence = evidence_collector.build_evidence_pack(culprit, time.time(), f"mock-trace-{scenario}")
    diagnosis = diagnostician.diagnose(evidence)
    
    proposed_action = diagnosis.get("proposed_action", "scale")
    if proposed_action not in ["scale", "restart", "cache-flush", "breaker-force"]:
        proposed_action = "scale"
        
    COMMAND_TEMPLATES = {
        "scale": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "restart": "kubectl -n techx-tf3 rollout restart deployment/{service}",
        "cache-flush": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "breaker-force": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1"
    }
    ROLLBACK_TEMPLATES = {
        "scale": "kubectl -n techx-tf3 scale deploy/{service} --replicas=1",
        "restart": "kubectl -n techx-tf3 rollout undo deployment/{service}",
        "cache-flush": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2",
        "breaker-force": "kubectl -n techx-tf3 scale deploy/{service} --replicas=2"
    }
    action_cmd = COMMAND_TEMPLATES[proposed_action].format(service=culprit)
    rollback_cmd = ROLLBACK_TEMPLATES[proposed_action].format(service=culprit)
    
    # 2. Blast Radius %
    blast_radius = correlator.calculate_blast_radius(culprit)
    confidence = float(diagnosis.get("confidence_score", 1.0))
    
    # 3. Risk Assessment Matrix
    risk = "LOW" if proposed_action in ["scale", "restart", "cache-flush", "breaker-force"] else "HIGH"
    if risk == "LOW":
        if proposed_action in ["scale", "restart"] and blast_radius > 60.0:
            risk = "MEDIUM"
        elif confidence < 0.80:
            risk = "MEDIUM"
        elif culprit == "frontend":
            risk = "MEDIUM"
            
    # 4. Dry-Run Safety Check
    dry_run_passed = handler.execute_k8s_command(action_cmd, dry_run=True)
    if not dry_run_passed:
        audit_record = audit_logger.log_remediation_event(
            incident_id=incident_id, trigger="ReplayTrigger", culprit_service=culprit,
            proposed_action=proposed_action, action_command=action_cmd, blast_radius_percent=blast_radius,
            risk_level=risk, dry_run_passed=False, executed=False, verification_passed=False,
            rollback_executed=False, status="DRY_RUN_FAILED", message="Dry-run safety check failed."
        )
        return {"status": "error", "audit": audit_record}
        
    # 5. Live Execution
    executed_passed = handler.execute_k8s_command(action_cmd, dry_run=False)
    
    # 6. Telemetry Verification & Auto-Rollback Injection
    if payload.force_verify_fail:
        logger.warning(f"[REPLAY INJECTION] Forcefully injecting Verification FAILURE to test Auto-Rollback branch!")
        is_resolved = False
    else:
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            is_resolved = True
        else:
            is_resolved = handler.verify_remediation(culprit)
            
    rollback_executed = False
    rollback_passed = False
    status_str = "REMEDIATION_SUCCESS"
    
    if not is_resolved:
        logger.warning(f"[REPLAY] Verification FAILED! Executing AUTO-ROLLBACK: {rollback_cmd}")
        rollback_executed = True
        rollback_passed = handler.trigger_rollback(rollback_cmd)
        status_str = "ROLLED_BACK_SUCCESSFULLY" if rollback_passed else "ROLLBACK_FAILED"
        
    # 7. Write Audit Log JSONL
    audit_record = audit_logger.log_remediation_event(
        incident_id=incident_id,
        trigger="ReplayTrigger",
        culprit_service=culprit,
        proposed_action=proposed_action,
        action_command=action_cmd,
        blast_radius_percent=blast_radius,
        risk_level=risk,
        dry_run_passed=dry_run_passed,
        executed=executed_passed,
        verification_passed=is_resolved,
        rollback_executed=rollback_executed,
        rollback_command=rollback_cmd,
        rollback_passed=rollback_passed,
        status=status_str,
        message=f"Mandate #22 Replay scenario '{scenario}' completed."
    )
    
    return {
        "status": "success",
        "incident_id": incident_id,
        "scenario": scenario,
        "culprit_service": culprit,
        "proposed_action": proposed_action,
        "action_command": action_cmd,
        "rollback_command": rollback_cmd,
        "blast_radius_percent": blast_radius,
        "risk_level": risk,
        "dry_run_passed": dry_run_passed,
        "executed": executed_passed,
        "verification_passed": is_resolved,
        "rollback_executed": rollback_executed,
        "rollback_passed": rollback_passed,
        "audit_record": audit_record
    }

@app.get("/audit/logs")
async def get_audit_logs(limit: int = 50):
    """
    [Mandate #22] Trả về danh sách Audit Logs đã ghi vết cho kiểm toán và SRE.
    """
    logs = audit_logger.get_audit_logs(limit=limit)
    return {
        "status": "success",
        "total": len(logs),
        "audit_logs": logs
    }



