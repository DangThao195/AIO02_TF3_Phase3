import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# DO NOT SET AIOPS_SIMULATION_MODE="true" to test real model & guardrail physics!
from anomaly_detector import AnomalyDetector

print("=================================================================")
print("  REAL MODEL & GUARDRAIL PHYSICS VERIFICATION TEST ")
print("=================================================================\n")

detector = AnomalyDetector()

# 1. True Idle Service ([0.0]*18)
idle_features = [0.0]*18
is_anom_idle = detector.check_infra_anomaly("checkout", idle_features)
print(f"  -> True Idle Service ([0.0]*18): Anomaly={is_anom_idle} (Expected: False/Normal)")

# 2. Chaos Mesh Latency Injection (Latency=1.5s)
chaos_latency_features = [0.0, 0.05, 0.3, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 14, 3, 1, 0]
is_anom_chaos = detector.check_infra_anomaly("checkout", chaos_latency_features)
print(f"  -> Chaos Mesh Latency Injection (Latency=1.5s): Anomaly={is_anom_chaos} (Expected: True/Anomaly)")

# 3. Chaos Mesh Error Rate Injection (ErrorRate=0.25)
chaos_error_features = [12.0, 0.35, 0.4, 0.12, 0.25, 0.0, 0.0, 0.25, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 14, 3, 1, 0]
is_anom_error = detector.check_infra_anomaly("checkout", chaos_error_features)
print(f"  -> Chaos Mesh Error Rate Injection (ErrorRate=0.25): Anomaly={is_anom_error} (Expected: True/Anomaly)")

assert not is_anom_idle, "Idle Guardrail failed"
assert is_anom_chaos, "Chaos Latency Fault failed"
assert is_anom_error, "Chaos Error Fault failed"

print("\n=================================================================")
print("  ALL REAL GUARDRAIL TESTS 100% PASSED!")
print("=================================================================")
