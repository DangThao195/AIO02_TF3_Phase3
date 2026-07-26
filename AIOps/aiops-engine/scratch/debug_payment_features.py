import urllib.request
import json

def get_prom(query):
    url = f"http://localhost:9090/api/v1/query?query={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                res = data.get("data", {}).get("result", [])
                if res:
                    return float(res[0]["value"][1])
    except Exception as e:
        print("Error query:", query, e)
    return 0.0

rps = get_prom('sum(rate(traces_span_metrics_calls_total{service_name="payment",span_kind="SPAN_KIND_SERVER"}[5m]))')
err = get_prom('sum(rate(traces_span_metrics_calls_total{service_name="payment",span_kind="SPAN_KIND_SERVER",status_code="STATUS_CODE_ERROR"}[5m]))')
lat = get_prom('histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="payment",span_kind="SPAN_KIND_SERVER"}[5m])) by (le))')
cpu = get_prom('sum(rate(container_cpu_usage_seconds_total{container="payment"}[5m]))')
mem = get_prom('sum(container_memory_working_set_bytes{container="payment"})')

print(f"DEBUG payment features right now:")
print(f"RPS: {rps}")
print(f"Error Rate: {err}")
print(f"Latency P90 (ms): {lat}")
print(f"CPU: {cpu}")
print(f"Mem: {mem}")
