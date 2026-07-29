import requests, json
from datetime import datetime, timezone

prom_url = "http://prometheus.techx-tf3.svc.cluster.local:9090"
start_ts = 1784694600  # 04:30 UTC = 11:30 AM VN
end_ts = 1784696400    # 05:00 UTC = 12:00 PM VN

q_lat = 'histogram_quantile(0.90, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name="shipping"}[5m])) by (le))'
q_err = 'sum(rate(traces_span_metrics_calls_total{service_name="shipping", status_code="STATUS_CODE_ERROR"}[5m]))'
q_cpu = 'sum(rate(container_cpu_usage_seconds_total{container="shipping"}[5m]))'
q_rps = 'sum(rate(traces_span_metrics_calls_total{service_name="shipping"}[5m]))'

def print_metric(name, query):
    print(f"=== {name} ===")
    try:
        res = requests.get(f"{prom_url}/api/v1/query_range", params={"query": query, "start": start_ts, "end": end_ts, "step": "2m"}, timeout=5).json()
        results = res.get("data", {}).get("result", [])
        if not results:
            print("  No data returned")
        for item in results:
            for v in item.get("values", []):
                t_str = datetime.fromtimestamp(v[0], tz=timezone.utc).strftime("%H:%M UTC (%I:%M %p VN)")
                print(f"  {t_str} -> {float(v[1]):.4f}")
    except Exception as e:
        print(f"  Error: {e}")

print_metric("LATENCY P90 (ms)", q_lat)
print_metric("ERROR CALLS", q_err)
print_metric("RPS", q_rps)
print_metric("CPU USAGE", q_cpu)
