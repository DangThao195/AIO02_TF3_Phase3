import requests
import json
import time

def run_test():
    url = "http://localhost:8000/webhook/alerts"
    
    # Giả lập một đợt bão cảnh báo (Alert Flood) gồm 7 alert từ 3 sự cố độc lập
    payload = {
        "alerts": [
            # Nhóm 1: Nhánh thanh toán lỗi lan truyền (frontend -> checkout -> payment -> payments-db)
            {
                "status": "firing",
                "labels": {
                    "alertname": "HTTP5xxRateHigh",
                    "service": "frontend",
                    "severity": "critical"
                },
                "annotations": {
                    "trace_id": "mock-inc1"
                }
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "gRPCLatencyHigh",
                    "service": "checkout",
                    "severity": "critical"
                },
                "annotations": {
                    "trace_id": "mock-inc1"
                }
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "DatabaseConnectionFailed",
                    "service": "payment",
                    "severity": "critical"
                },
                "annotations": {
                    "trace_id": "mock-inc1"
                }
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "PostgresPoolExhausted",
                    "service": "payments-db",
                    "severity": "critical"
                },
                "annotations": {
                    "trace_id": "mock-inc1"
                }
            },
            
            # Nhóm 2: Sự cố Valkey giỏ hàng bị tràn RAM (cart -> valkey-cart)
            {
                "status": "firing",
                "labels": {
                    "alertname": "ValkeyMemoryUsageHigh",
                    "service": "valkey-cart",
                    "severity": "warning"
                },
                "annotations": {
                    "trace_id": "mock-inc2"
                }
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "CartSaveFailure",
                    "service": "cart",
                    "severity": "warning"
                },
                "annotations": {
                    "trace_id": "mock-inc2"
                }
            },
            
            # Nhóm 3: Nghẽn consumer lag trên hàng đợi (accounting)
            {
                "status": "firing",
                "labels": {
                    "alertname": "KafkaConsumerLagHigh",
                    "service": "accounting",
                    "severity": "warning"
                },
                "annotations": {
                    "trace_id": "mock-inc5"
                }
            }
        ]
    }
    
    print("Sending alert flood payload to AIOps webhook...")
    try:
        response = requests.post(url, json=payload, timeout=5)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Failed to send request: {e}")

if __name__ == "__main__":
    run_test()
