import requests

PROM_URL = "http://prometheus.techx-tf3.svc.cluster.local:9090"

def query(q):
    resp = requests.get(f"{PROM_URL}/api/v1/query", params={"query": q}, timeout=5)
    return resp.json().get("data", {}).get("result", [])

SERVICES = ["frontend", "checkout", "payment", "product-catalog", "product-reviews", "shipping", "recommendation"]

print("=== CHECKING SPAN CALL RATES FOR ALL SERVICES ===")
for svc in SERVICES:
    q1 = f'sum(rate(traces_span_metrics_calls_total{{service_name="{svc}", span_kind="SPAN_KIND_SERVER"}}[5m]))'
    res1 = query(q1)
    val1 = res1[0]["value"][1] if res1 else "NONE"
    
    q2 = f'sum(rate(traces_span_metrics_calls_total{{service_name="{svc}"}}[5m]))'
    res2 = query(q2)
    val2 = res2[0]["value"][1] if res2 else "NONE"
    
    print(f"Service: {svc:18s} | SERVER kind rate: {val1} | Any kind rate: {val2}")

