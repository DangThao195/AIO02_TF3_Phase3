import json

with open("tests/cache-test/mandate_23_test_results.json", encoding="utf-8") as f:
    data = json.load(f)

metrics = data.get("metrics", {})
server = data.get("server_cache_metrics", {})

print("=== MANDATE #23 FULL METRICS DUMP ===")
print(f"PASSED: {data['passed']} / {data['total_tests']}")
print()
print("--- Client-side Metrics ---")
for k, v in metrics.items():
    print(f"  {k}: {v}")
print()
print("--- Server-side Cache Stats ---")
for k, v in server.items():
    print(f"  {k}: {v}")
print()
print("--- PASS/FAIL Table ---")
for t in data.get("test_details", []):
    status = "PASS" if t.get("passed") else "FAIL"
    errs = t.get("errors", [])
    tid = t["test_id"]
    print(f"  {tid:12s} {status}  {errs}")
