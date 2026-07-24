import requests

PROM_URL = "http://prometheus.techx-tf3.svc.cluster.local:9090"

def query(q):
    resp = requests.get(f"{PROM_URL}/api/v1/query", params={"query": q}, timeout=5)
    return resp.json().get("data", {}).get("result", [])

print("=== Checking OpenTelemetry Span Metrics in Prometheus ===")
res1 = query('traces_span_metrics_calls_total')
print(f"Total traces_span_metrics_calls_total series: {len(res1)}")
for r in res1[:10]:
    labels = r.get("metric", {})
    print(" - Service label:", labels.get("service_name", labels.get("service", labels.get("job", "unknown"))), "| Value:", r.get("value")[1])

