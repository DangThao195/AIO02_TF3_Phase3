import urllib.request
import json

url = "http://localhost:9090/api/v1/label/__name__/values"
try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            names = data.get("data", [])
            span_metrics = [n for n in names if "traces" in n or "span" in n or "http" in n or "calls" in n or "duration" in n or "cpu" in n or "flagd" in n or "slo" in n]
            print(f"Total metrics in Prometheus: {len(names)}")
            print("Matching metrics:", span_metrics[:30])
except Exception as e:
    print("Error:", e)
