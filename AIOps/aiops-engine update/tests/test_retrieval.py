import requests
import json
import sys

def test_jaeger_connection():
    print("Testing connection to Jaeger UI via localhost:8080...")
    # Jaeger API is exposed under /jaeger/ui/api path on the frontend-proxy
    url = "http://localhost:8080/jaeger/ui/api/services"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            services = response.json().get("data", [])
            print(f"SUCCESS: Connected to Jaeger! Available services: {services}")
            return True
        else:
            print(f"FAILED: Jaeger returned status code {response.status_code}")
    except Exception as e:
        print(f"FAILED: Could not connect to Jaeger on localhost:8080. Error: {str(e)}")
    return False

def test_prometheus_connection():
    print("\nTesting connection to Prometheus (via Grafana DataSource API) on localhost:8080...")
    # We query the Prometheus metrics from Grafana API
    url = "http://localhost:8080/grafana/api/datasources/name/Prometheus"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            ds_info = response.json()
            ds_id = ds_info.get("id")

            ds_uid = ds_info.get("uid")
            print(f"SUCCESS: Found Prometheus DataSource ID: {ds_id}, UID: {ds_uid}")
            
            # Run a test query for SLO requests count
            query_url = f"http://localhost:8080/grafana/api/datasources/proxy/uid/{ds_uid}/api/v1/query"
            params = {"query": "up"}
            q_resp = requests.get(query_url, params=params, timeout=5)
            if q_resp.status_code == 200:
                print("SUCCESS: Successfully queried Prometheus metrics!")
                return True
            else:
                print(f"FAILED: Prometheus query failed with status code {q_resp.status_code}, response: {q_resp.text}")

        else:
            print(f"FAILED: Grafana datasource query returned status code {response.status_code}")
    except Exception as e:
        print(f"FAILED: Could not connect to Prometheus/Grafana on localhost:8080. Error: {str(e)}")
    return False

if __name__ == "__main__":
    print("=== AIOPS TELEMETRY CONNECTION TEST ===")
    j_ok = test_jaeger_connection()
    p_ok = test_prometheus_connection()
    print("=======================================")
    if j_ok and p_ok:
        print("ALL TELEMETRY RETRIEVAL TESTS PASSED!")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED. Please ensure your port-forward command is active.")
        sys.exit(1)
