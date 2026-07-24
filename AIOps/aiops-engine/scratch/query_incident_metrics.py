import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

start = 1784880000  # 08:00 UTC (15:00 VN)
end = 1784881800    # 08:30 UTC (15:30 VN)

q = 'histogram_quantile(0.95, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name=~"payment|checkout|frontend", span_kind="SPAN_KIND_SERVER"}[1m])) by (le, service_name))'
url = f"https://localhost:8443/api/v1/query_range?query={urllib.parse.quote(q)}&start={start}&end={end}&step=60s"

try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            results = data["data"]["result"]
            print(f"Found {len(results)} metric series for 15:00-15:30 VN window:")
            for r in results:
                svc = r["metric"].get("service_name")
                vals = r.get("values", [])
                max_val = max([float(v[1]) for v in vals]) if vals else 0.0
                print(f"- Service {svc}: max P95 latency = {max_val:.1f} ms ({len(vals)} data points)")
except Exception as e:
    print("Error querying range:", e)
