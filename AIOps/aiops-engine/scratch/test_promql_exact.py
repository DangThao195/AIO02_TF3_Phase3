import urllib.request
import json

q1 = 'histogram_quantile(0.95, sum(rate(traces_span_metrics_duration_milliseconds_bucket{service_name=~"payment|checkout|frontend"}[5m])) by (le, service_name))'
url = f"http://localhost:9090/api/v1/query?query={urllib.parse.quote(q1)}"

try:
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("Query result count:", len(data["data"]["result"]))
        for r in data["data"]["result"]:
            print(f"- {r['metric'].get('service_name')}: {r['value'][1]}")
except Exception as e:
    print("Error:", e)
