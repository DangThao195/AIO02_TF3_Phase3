import sys
import os

# Build simulated NetworkX service graph
import networkx as nx

nx_graph = nx.DiGraph()
services_topology = {
    "frontend": ["checkout", "recommendation", "product-catalog"],
    "checkout": ["payment", "shipping", "email"],
    "recommendation": ["product-catalog"],
    "product-reviews": ["product-catalog"],
    "payment": [],
    "shipping": [],
    "product-catalog": []
}

for u, neighbors in services_topology.items():
    for v in neighbors:
        nx_graph.add_edge(u, v)

def calculate_anomaly_score(svc, lat_val, err_val, cpu_val, mem_val, lag_val):
    depth = len(nx.descendants(nx_graph, svc)) if svc in nx_graph else 0
    depth_weight = 1.0 / (depth + 1.0)
    score = (
        (lat_val * 2.0) +
        (err_val * 10.0) +
        (cpu_val * 1.5) +
        (mem_val * 0.05) +
        (lag_val * 0.01)
    ) * (1.0 + depth_weight)
    return score, depth

scenarios = [
    {
        "name": "Scenario 1: Payment Latency Spike 5s (Downstream Delay)",
        "trigger": "frontend",
        "metrics": {
            "payment": {"lat": 5.2, "err": 0.0, "cpu": 0.05, "mem": 30.0, "lag": 0},
            "checkout": {"lat": 5.2, "err": 0.0, "cpu": 0.05, "mem": 30.0, "lag": 0},
            "frontend": {"lat": 5.3, "err": 0.02, "cpu": 0.10, "mem": 40.0, "lag": 0},
            "recommendation": {"lat": 0.02, "err": 0.0, "cpu": 0.02, "mem": 20.0, "lag": 0},
            "product-catalog": {"lat": 0.01, "err": 0.0, "cpu": 0.02, "mem": 20.0, "lag": 0},
        },
        "expected_culprit": "payment"
    },
    {
        "name": "Scenario 2: Product Catalog 5xx Error Outage (Database Failure)",
        "trigger": "recommendation",
        "metrics": {
            "product-catalog": {"lat": 0.10, "err": 0.50, "cpu": 0.80, "mem": 85.0, "lag": 0},
            "recommendation": {"lat": 0.12, "err": 0.05, "cpu": 0.10, "mem": 30.0, "lag": 0},
            "frontend": {"lat": 0.15, "err": 0.02, "cpu": 0.10, "mem": 40.0, "lag": 0},
            "payment": {"lat": 0.02, "err": 0.0, "cpu": 0.02, "mem": 20.0, "lag": 0},
        },
        "expected_culprit": "product-catalog"
    },
    {
        "name": "Scenario 3: Frontend Pod OOM / CPU Saturation (Upstream Entrypoint Failure)",
        "trigger": "frontend",
        "metrics": {
            "frontend": {"lat": 2.5, "err": 0.40, "cpu": 0.95, "mem": 95.0, "lag": 0},
            "checkout": {"lat": 0.02, "err": 0.0, "cpu": 0.05, "mem": 20.0, "lag": 0},
            "payment": {"lat": 0.02, "err": 0.0, "cpu": 0.02, "mem": 20.0, "lag": 0},
            "product-catalog": {"lat": 0.01, "err": 0.0, "cpu": 0.02, "mem": 20.0, "lag": 0},
        },
        "expected_culprit": "frontend"
    },
    {
        "name": "Scenario 4: Checkout CPU Stress & Memory Leak (Mid-tier Failure)",
        "trigger": "frontend",
        "metrics": {
            "checkout": {"lat": 3.8, "err": 0.25, "cpu": 0.90, "mem": 90.0, "lag": 0},
            "frontend": {"lat": 4.0, "err": 0.10, "cpu": 0.15, "mem": 40.0, "lag": 0},
            "payment": {"lat": 0.02, "err": 0.0, "cpu": 0.02, "mem": 20.0, "lag": 0},
        },
        "expected_culprit": "checkout"
    }
]

print("="*70)
print("  RCA 5-FACTOR TELEMETRY AUDIT ALGORITHM COMPREHENSIVE TEST SUITE")
print("="*70)

all_passed = True
for idx, sc in enumerate(scenarios, 1):
    print(f"\n[Test {idx}] {sc['name']}")
    scores = {}
    for svc, m in sc["metrics"].items():
        score, depth = calculate_anomaly_score(svc, m["lat"], m["err"], m["cpu"], m["mem"], m["lag"])
        scores[svc] = (score, depth, m)
        print(f"  -> {svc:16s}: score={score:6.2f} (depth={depth}, lat={m['lat']}s, err={m['err']}, cpu={m['cpu']})")
    
    best_culprit = max(scores.keys(), key=lambda k: scores[k][0])
    passed = (best_culprit == sc["expected_culprit"])
    status = "PASSED" if passed else "FAILED"
    print(f"  RESULT: Selected Culprit = '{best_culprit}' | Expected = '{sc['expected_culprit']}' -> {status}")
    if not passed:
        all_passed = False

print("\n"+"="*70)
if all_passed:
    print("  ALL 4 COMPLEX CASCADE RCA TEST SCENARIOS 100% PASSED!")
else:
    print("  SOME TEST SCENARIOS FAILED!")
print("="*70)
