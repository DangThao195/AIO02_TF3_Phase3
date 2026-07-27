import urllib.request
import json

url = 'http://localhost:9090/api/v1/query?query=http_server_duration_milliseconds_bucket'
try:
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            results = data.get("data", {}).get("result", [])
            print(f"http_server_duration_milliseconds_bucket count: {len(results)}")
            if results:
                print("Labels:", results[0].get("metric"))
except Exception as e:
    print("Error:", e)

url2 = 'http://localhost:9090/api/v1/query?query=traces_span_metrics_duration_milliseconds_bucket'
try:
    with urllib.request.urlopen(url2, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            results = data.get("data", {}).get("result", [])
            print(f"traces_span_metrics_duration_milliseconds_bucket count: {len(results)}")
            if results:
                print("Labels:", results[0].get("metric"))
except Exception as e:
    print("Error2:", e)
