import requests
import json
import time

import argparse

def fire_alert(trace_id: str):
    url = "http://localhost:8000/webhook/alerts"
    payload = {
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "CheckoutLatencySpike",
                "service": "frontend",
                "severity": "critical"
            },
            "annotations": {
                "trace_id": trace_id
            }
        }]
    }
    
    print(f"Sending mock Prometheus webhook alert (Trace ID: {trace_id}) to {url}...")
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"FastAPI Server Response Code: {response.status_code}")
        print(f"FastAPI Server Response Body: {response.json()}")
    except Exception as e:
        print(f"Failed to connect to FastAPI server: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fire mock alert webhook to FastAPI server")
    parser.add_argument("--trace", type=str, default="mock-inc3", help="Trace ID to send (e.g. mock-inc1, mock-inc2, mock-inc3, or real trace id)")
    args = parser.parse_args()
    
    fire_alert(args.trace)
