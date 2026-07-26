import urllib.request
import json

url = "http://localhost:9090/api/v1/query?query=traces_span_metrics_calls_total"
try:
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            results = data["data"]["result"]
            if results:
                ts = results[0]["value"][0]
                import datetime
                dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                print(f"Current Prometheus timestamp: {ts} -> {dt} UTC")
except Exception as e:
    print("Error:", e)
