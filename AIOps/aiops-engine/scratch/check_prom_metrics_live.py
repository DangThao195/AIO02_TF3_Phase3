import os, sys, json
sys.path.insert(0, "aiops-engine")
from anomaly_detector import AnomalyDetector

detector = AnomalyDetector()

# Test PromQL query directly on Prometheus
query = 'sum(traces_span_metrics_calls_total) by (service_name)'
print(f"Querying Prometheus: {query}")
res = detector.query_prometheus(query)
print("Prometheus Response:")
print(json.dumps(res, indent=2))
