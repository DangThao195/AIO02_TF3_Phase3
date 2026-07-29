import requests
import json

url = "http://localhost:9200"

print("=== OPENSEARCH INDICES CHECK ===")
try:
    # 1. Fetch indices
    res = requests.get(f"{url}/_cat/indices?format=json", timeout=5)
    if res.status_code == 200:
        indices = res.json()
        print("Indices found in OpenSearch:")
        for idx in indices:
            print(f"- {idx.get('index')}: count={idx.get('docs.count')}, size={idx.get('store.size')}")
    else:
        print(f"Failed to fetch indices: {res.status_code}")
        
    # 2. Query logs from otel-logs-*
    search_url = f"{url}/otel-logs-*/_search"
    query = {
        "size": 2,
        "query": {
            "match_all": {}
        }
    }
    
    print("\n=== OTEL LOGS SAMPLE DOCUMENT ===")
    res_search = requests.post(search_url, json=query, timeout=5)
    if res_search.status_code == 200:
        hits = res_search.json().get("hits", {}).get("hits", [])
        if hits:
            print(json.dumps(hits[0], indent=2))
        else:
            print("No hits found in otel-logs-* indices.")
    else:
        print(f"Failed to query otel-logs-*: {res_search.status_code}, response: {res_search.text}")

except Exception as e:
    print(f"Error connecting to OpenSearch: {e}")
