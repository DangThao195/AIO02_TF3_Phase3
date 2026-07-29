import urllib.request
import json
import time

PROM_URL = "https://localhost:8443/api/v1/query"
import ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

services = ["recommendation", "payment", "product-catalog", "frontend", "checkout"]

def query_prom(query):
    try:
        url = f"{PROM_URL}?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                results = data["data"]["result"]
                return results
    except Exception as e:
        print(f"Error querying {query}: {e}")
    return []

print("=== REAL-TIME EKS METRIC INVESTIGATION FOR SLACK ALERTS ===")
for svc in services:
    q_rps = f'sum(rate(http_requests_total{{app="{svc}"}}[5m])) or sum(rate(grpc_server_handled_total{{app="{svc}"}}[5m]))'
    q_err = f'sum(rate(http_requests_total{{app="{svc}", status=~"5.."}}[5m])) or sum(rate(grpc_server_handled_total{{app="{svc}", grpc_code!="OK"}}[5m]))'
    q_cpu = f'sum(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate{{namespace="techx-tf3", container="{svc}"}})'
    q_lat = f'histogram_quantile(0.90, sum(rate(http_request_duration_seconds_bucket{{app="{svc}"}}[5m])) by (le))'

    r_rps = query_prom(q_rps)
    r_err = query_prom(q_err)
    r_cpu = query_prom(q_cpu)
    r_lat = query_prom(q_lat)

    rps_val = float(r_rps[0]["value"][1]) if r_rps else 0.0
    err_val = float(r_err[0]["value"][1]) if r_err else 0.0
    cpu_val = float(r_cpu[0]["value"][1]) if r_cpu else 0.0
    lat_val = float(r_lat[0]["value"][1]) if r_lat else 0.0

    print(f"\nService: [{svc}]")
    print(f"  RPS: {rps_val:.4f}")
    print(f"  Error Rate (5xx/non-OK): {err_val:.4f}")
    print(f"  CPU Usage (cores): {cpu_val:.4f}")
    print(f"  Latency P90 (sec): {lat_val:.4f}")

