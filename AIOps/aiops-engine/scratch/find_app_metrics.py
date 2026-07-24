import urllib.request
import json

url = "http://localhost:9090/api/v1/label/__name__/values"
try:
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            names = data.get("data", [])
            app_metrics = [n for n in names if any(k in n for k in ["http_request", "calls", "span", "duration_milliseconds", "container_cpu", "kafka", "latency"])]
            print(f"App/Infrastructure metrics ({len(app_metrics)}):")
            for m in app_metrics[:50]:
                print(f"- {m}")
except Exception as e:
    print("Error:", e)
