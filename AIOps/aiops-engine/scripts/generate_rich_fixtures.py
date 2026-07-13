import json
import os
import random
import time

# Ensure fixtures directory exists
os.makedirs("fixtures", exist_ok=True)

def generate_rich_trace(scenario, culprit_service, error_service=None, latency_ms=100, error_msg=None):
    # Sơ đồ DAG chuẩn của TechX Corp storefront:
    # frontend-proxy -> frontend -> [checkout | product-reviews | cart | product-catalog]
    # checkout -> [cart | product-catalog | shipping | currency | payment]
    # product-reviews -> [llm | postgresql]
    # product-catalog -> postgresql
    
    trace_id = f"{scenario}-rich-trace-id"
    
    # Định nghĩa cấu trúc dịch vụ và span tương ứng
    services = {
        "frontend-proxy": {"span_id": "proxy-span", "parent": None},
        "frontend": {"span_id": "frontend-span", "parent": "frontend-proxy"},
        "product-reviews": {"span_id": "reviews-span", "parent": "frontend"},
        "llm": {"span_id": "llm-span", "parent": "product-reviews"},
        "product-catalog": {"span_id": "catalog-span", "parent": "frontend"},
        "postgresql": {"span_id": "db-span", "parent": "product-catalog"},
        "cart": {"span_id": "cart-span", "parent": "frontend"},
        "valkey-cart": {"span_id": "valkey-span", "parent": "cart"},
        "checkout": {"span_id": "checkout-span", "parent": "frontend"},
        "payment": {"span_id": "payment-span", "parent": "checkout"},
        "shipping": {"span_id": "shipping-span", "parent": "checkout"},
        "currency": {"span_id": "currency-span", "parent": "checkout"},
        "fraud-detection": {"span_id": "fraud-span", "parent": "frontend"},
        "accounting": {"span_id": "accounting-span", "parent": None} # Kafka consumer
    }
    
    spans = []
    processes = {}
    
    for svc_name, info in services.items():
        process_id = f"p-{svc_name}"
        processes[process_id] = {"serviceName": svc_name}
        
        # Thiết lập tag lỗi hoặc trễ cho culprit
        tags = []
        is_error = False
        duration = 5000 + random.randint(10, 500) if svc_name == culprit_service else random.randint(20, 150)
        
        # Ghi đè cấu hình cho các lỗi cụ thể
        if svc_name == error_service or svc_name == culprit_service:
            is_error = True
            tags.append({"key": "error", "type": "bool", "value": True})
            if error_msg:
                tags.append({"key": "error.message", "type": "string", "value": error_msg})
                
        # INC-8 Cold Start (latency cao nhưng không có error tag)
        if scenario == "inc8" and svc_name == "currency":
            duration = 3200000 # 3.2s
            is_error = False
            tags = []
            
        references = []
        if info["parent"]:
            references.append({
                "refType": "CHILD_OF",
                "spanID": services[info["parent"]]["span_id"],
                "traceID": trace_id
            })
            
        spans.append({
            "traceID": trace_id,
            "spanID": info["span_id"],
            "operationName": f"op_{svc_name}",
            "processID": process_id,
            "duration": duration * 1000, # convert to microseconds
            "tags": tags,
            "references": references
        })
        
    return {
        "data": [
            {
                "traceID": trace_id,
                "spans": spans,
                "processes": processes
            }
        ]
    }

def generate_rich_logs(scenario, culprit_service, error_message_template):
    logs = []
    
    # 1. Sinh 80 dòng logs INFO bình thường với tham số động (timestamps, request ID, latency)
    for i in range(80):
        req_id = f"req-{random.randint(100000, 999999)}"
        latency = random.randint(5, 45)
        body = f"INFO: [RequestID: {req_id}] HTTP GET /products/details success. Processed in {latency}ms."
        logs.append({
            "body": body,
            "timestamp": int((time.time() - 300 + i * 3) * 1000)
        })
        
    # 2. Sinh 20 dòng logs ERROR với lỗi biến đổi động để kiểm thử Drain3
    for i in range(20):
        err_id = f"err-{random.randint(200000, 899999)}"
        conn_active = random.randint(90, 105)
        # Sử dụng error template được định nghĩa cho từng kịch bản
        body = error_message_template.format(err_id=err_id, conn_active=conn_active)
        logs.append({
            "body": body,
            "timestamp": int((time.time() - 60 + i * 3) * 1000)
        })
        
    # Trộn ngẫu nhiên logs để sát thực tế
    random.shuffle(logs)
    return logs

# ==========================================
# CẤU HÌNH CHI TIẾT TỪNG SCENARIO
# ==========================================
scenarios = {
    "inc1": {
        "culprit": "postgresql",
        "error_service": "product-catalog",
        "error_msg": "postgresql connection pool exhausted",
        "log_template": "ERROR: [DB_Error_ID: {err_id}] Failed to acquire database connection slot. Connection pool exhausted (active slots: {conn_active}/100)."
    },
    "inc2": {
        "culprit": "valkey-cart",
        "error_service": "cart",
        "error_msg": "valkey OOM connection refused",
        "log_template": "CRITICAL: [Valkey_Alert: {err_id}] Connection refused. Memory limit of 256MB exceeded. Cannot write cart session keys."
    },
    "inc3": {
        "culprit": "fraud-detection",
        "error_service": "fraud-detection",
        "error_msg": "flagd EventStream connection timeout",
        "log_template": "WARNING: [Stream_Warn: {err_id}] Connection to flagd EventStream timeout (gRPC status 4). Re-establishing stream."
    },
    "inc4": {
        "culprit": "llm",
        "error_service": "product-reviews",
        "error_msg": "LLM Provider 429 Too Many Requests",
        "log_template": "ERROR: [LLM_Call: {err_id}] Bedrock API rate limit reached. HTTP 429 Too Many Requests. Timeout after {conn_active}ms."
    },
    "inc5": {
        "culprit": "accounting",
        "error_service": "accounting",
        "error_msg": "Kafka consumer lag exceeded limit",
        "log_template": "CRITICAL: [Kafka_Lag_ID: {err_id}] Consumer lag spike. Topic orders is {conn_active}00 messages behind."
    },
    "inc6": {
        "culprit": "recommendation",
        "error_service": "recommendation",
        "error_msg": "Memory working set limit warning",
        "log_template": "WARNING: [OS_Memory: {err_id}] Container memory usage reached {conn_active}% of cgroup limit (495Mi/500Mi)."
    },
    "inc7": {
        "culprit": "product-reviews", # target breaker
        "error_service": "product-reviews",
        "error_msg": "Circuit breaker stuck in OPEN state",
        "log_template": "CRITICAL: [Breaker_ID: {err_id}] Circuit breaker for LLM service is stuck in OPEN state. Current probe requests: {conn_active}."
    },
    "inc8": {
        "culprit": "currency",
        "error_service": "currency",
        "error_msg": "Cache warm up latency cold start",
        "log_template": "INFO: [Cache_Warmer: {err_id}] Warming exchange rates cache from external API. Elapsed time: 3200ms."
    },
    "incnew": {
        "culprit": "payment",
        "error_service": "payment",
        "error_msg": "Payment Gateway 502 Bad Gateway",
        "log_template": "ERROR: [Payment_Gateway_ID: {err_id}] Connection to merchant failed. HTTP 502 Bad Gateway. Active gateway connections: {conn_active}."
    }
}

# Generate and save all files
for scenario, config in scenarios.items():
    trace = generate_rich_trace(
        scenario, 
        culprit_service=config["culprit"], 
        error_service=config["error_service"], 
        error_msg=config["error_msg"]
    )
    logs = generate_rich_logs(
        scenario, 
        culprit_service=config["culprit"], 
        error_message_template=config["log_template"]
    )
    
    with open(f"fixtures/{scenario}_trace_response.json", "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2)
        
    with open(f"fixtures/{scenario}_logs.json", "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)

print("SUCCESS: Generated 18 rich telemetry fixtures (logs & traces) in 'fixtures/'!")
