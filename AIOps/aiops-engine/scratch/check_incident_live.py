import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

services = ['frontend', 'checkout', 'payment', 'product-catalog', 'product-reviews', 'shipping', 'recommendation']

def get_metric(q):
    url = f"https://localhost:8443/api/v1/query?query={urllib.parse.quote(q)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success" and data["data"]["result"]:
                return float(data["data"]["result"][0]["value"][1])
    except Exception as e:
        pass
    return 0.0

print("="*60)
print("LIVE PROMETHEUS METRICS AUDIT (Current EKS State)")
print("="*60)
for svc in services:
    rps = get_metric(f'sum(rate(traces_span_metrics_calls_total{{service_name="{svc}",span_kind="SPAN_KIND_SERVER"}}[1m]))')
    err = get_metric(f'sum(rate(traces_span_metrics_calls_total{{service_name="{svc}",span_kind="SPAN_KIND_SERVER",status_code="STATUS_CODE_ERROR"}}[1m]))')
    lat_p95 = get_metric(f'histogram_quantile(0.95, sum(rate(traces_span_metrics_duration_milliseconds_bucket{{service_name="{svc}",span_kind="SPAN_KIND_SERVER"}}[1m])) by (le))')
    print(f"Service: {svc:16s} | RPS: {rps:6.2f} | Error: {err:6.3f} | Latency P95: {lat_p95:8.1f} ms")
print("="*60)
