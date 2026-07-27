import urllib.request
import json
import base64

auth_str = base64.b64encode(b"admin:admin").decode("utf-8")
headers = {"Authorization": f"Basic {auth_str}"}

req = urllib.request.Request("http://localhost:3000/api/search", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        dashboards = json.loads(resp.read().decode("utf-8"))
        print("Grafana Dashboards:")
        for d in dashboards:
            print(f"- {d.get('title')} (url: {d.get('url')})")
except Exception as e:
    print("Error:", e)
