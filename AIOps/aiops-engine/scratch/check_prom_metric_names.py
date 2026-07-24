import requests

PROM_URL = "http://prometheus.techx-tf3.svc.cluster.local:9090"

print("Fetching metric names from Prometheus...")
resp = requests.get(f"{PROM_URL}/api/v1/label/__name__/values", timeout=5)
metrics = resp.json().get("data", [])

http_metrics = [m for m in metrics if "http" in m or "request" in m or "rpc" in m or "app" in m]
print(f"Total metrics in Prometheus: {len(metrics)}")
print(f"HTTP/RPC related metrics ({len(http_metrics)}):")
for m in sorted(http_metrics)[:30]:
    print(" -", m)

