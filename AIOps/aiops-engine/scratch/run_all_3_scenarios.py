import os, sys, json
os.environ["AIOPS_SIMULATION_MODE"] = "true"
sys.path.insert(0, "aiops-engine")
from main import app
from fastapi.testclient import TestClient

client = TestClient(app)
with open("aiops-engine/datametric/labeled_scenarios.json", "r") as f:
    scenarios = json.load(f)["scenarios"]

print("=================== REPLAY API (PURE ML vs COMBINED 2-LAYER) ===================")
for sc in scenarios:
    name = sc["scenario_name"]
    payload = {"service": sc["service"], "data": sc["data"]}
    res = client.post("/simulate/replay", json=payload).json()
    metrics = res.get("metrics", {})
    
    pure_ml = metrics.get("pure_ml", {})
    combined = metrics.get("combined_2layer", {})
    
    p_ml = pure_ml.get("precision", 0) * 100
    r_ml = pure_ml.get("recall", 0) * 100
    cm_ml = pure_ml.get("confusion_matrix", {})
    
    p_c = combined.get("precision", 0) * 100
    r_c = combined.get("recall", 0) * 100
    cm_c = combined.get("confusion_matrix", {})
    
    print(f"\nScenario: [{name}] (Service: {sc['service']})")
    print(f"  [1] Pure ML (Isolation Forest Alone):")
    print(f"      - Precision: {p_ml:.1f}%, Recall: {r_ml:.1f}%")
    print(f"      - Confusion Matrix -> TP: {cm_ml.get('true_positives')}, FP: {cm_ml.get('false_positives')}, FN: {cm_ml.get('false_negatives')}, TN: {cm_ml.get('true_negatives')}")
    print(f"  [2] Combined 2-Layer (ML + SLO Gate):")
    print(f"      - Precision: {p_c:.1f}%, Recall: {r_c:.1f}%")
    print(f"      - Confusion Matrix -> TP: {cm_c.get('true_positives')}, FP: {cm_c.get('false_positives')}, FN: {cm_c.get('false_negatives')}, TN: {cm_c.get('true_negatives')}")
