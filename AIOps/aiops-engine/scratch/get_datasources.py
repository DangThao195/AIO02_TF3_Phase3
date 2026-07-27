import urllib.request
import json
import base64

auth_str = base64.b64encode(b"admin:admin").decode("utf-8")
headers = {"Authorization": f"Basic {auth_str}"}

req = urllib.request.Request("http://localhost:3000/api/datasources", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        datasources = json.loads(resp.read().decode("utf-8"))
        print("Grafana Data Sources:")
        for ds in datasources:
            print(f"- Name: {ds.get('name')}, Type: {ds.get('type')}, UID: {ds.get('uid')}, isDefault: {ds.get('isDefault')}")
except Exception as e:
    print("Error:", e)
