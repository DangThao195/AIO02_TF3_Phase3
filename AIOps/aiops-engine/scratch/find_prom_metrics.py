import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def query_prom(q):
    url = f"https://localhost:8443/api/v1/query?query={urllib.parse.quote(q)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                res = data["data"]["result"]
                print(f"Query: {q} -> count: {len(res)}")
                if res:
                    print("  Sample metric labels:", res[0]["metric"])
    except Exception as e:
        print(f"Error {q}: {e}")

query_prom('traces_span_metrics_duration_seconds_bucket')
query_prom('http_request_duration_seconds_bucket')
query_prom('traces_span_metrics_calls_total')
query_prom('node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate{namespace="techx-tf3"}')
