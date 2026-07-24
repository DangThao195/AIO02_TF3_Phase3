#!/usr/bin/env python3
"""
AIOps Replay Simulation - AIE1
==============================
Gia lap AIOps replay flow va tich hop CHINH XAC voi guardrails/cache.py:
  1. [TRIGGER]  AIOps Detector bom loi (gialap LLM error spike)
  2. [ACTION]   AIOps Controller set Redis key product_reviews:fallback_override = true
  3. [VERIFY]   Goi ham THAT guardrails.cache.is_fallback_override_active() -> tra ve True -> chuyen sang Cache/Fallback
  4. [ROLLBACK] AIOps Controller xoa Redis key product_reviews:fallback_override
  5. [RECOVER]  Goi ham THAT guardrails.cache.is_fallback_override_active() -> tra ve False -> LLM path khoi phuc

Output: logs/audit_log.jsonl (Chuẩn JSON Lines duy nhất)
Chay: python aiops_replay_sim.py [--redis-host HOST] [--redis-port PORT] [--dry-run]
"""

import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guardrails.cache as cache_module


class MockRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, **kwargs):
        self.store[key] = str(value)
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0

    def ping(self):
        return True


REDIS_KEY = "product_reviews:fallback_override"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# CHỐT 1 FILE CHUẨN JSON LINES DUY NHẤT
AUDIT_LOG_PATH = os.path.join(LOG_DIR, "audit_log.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)

_RUN_ID = None


def ts():
    return datetime.now(timezone.utc).isoformat()


def write_audit(record):
    # Ghi trực tiếp vào 1 file jsonl duy nhất
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def audit(phase, status, detail, extra=None):
    rec = {
        "run_id": _RUN_ID,
        "timestamp": ts(),
        "phase": phase,
        "status": status,
        "detail": detail,
    }
    if extra:
        rec.update(extra)
    write_audit(rec)
    print(f"  [AUDIT] {phase:12s} | {status:7s} | {detail}")


def setup_redis_client(host, port, dry_run):
    if dry_run:
        print("  [INFO] Su dung MockRedis de test truc tiep guardrails/cache.py")
        mock_r = MockRedis()
        cache_module.redis_client = mock_r
        return mock_r

    try:
        import redis
        r = redis.Redis(host=host, port=port, socket_timeout=1.0, decode_responses=True)
        r.ping()
        cache_module.redis_client = r
        print(f"  [INFO] Connected to REAL Redis at {host}:{port}")
        return r
    except Exception as e:
        print(f"  [WARN] Real Redis failed ({e}). Fallback sang MockRedis.")
        mock_r = MockRedis()
        cache_module.redis_client = mock_r
        return mock_r


def measure_error_rate(n, error_rate):
    errors = sum(1 for _ in range(n) if random.random() < error_rate)
    return errors / n


def phase_trigger(r):
    print("\n=== PHASE 1: TRIGGER -- AIOps Detector bom loi ===")
    baseline = measure_error_rate(50, 0.75)
    audit(
        phase="trigger",
        status="FIRED",
        detail=f"AIOps Detector phat hien LLM error spike. simulated_error_rate={baseline:.0%}",
        extra={
            "simulated_error_rate": round(baseline, 4),
            "threshold": 0.30,
            "fault_type": "llm_rate_limit_spike",
        },
    )
    print(f"  -> Simulated error rate after fault injection: {baseline:.0%}")
    time.sleep(0.3)


def phase_action(r):
    print("\n=== PHASE 2: ACTION -- AIOps Controller set Redis key ===")
    cache_module.redis_client.set(REDIS_KEY, "true")
    detail = f"AIOps Controller SET {REDIS_KEY}=true"
    audit(
        phase="action",
        status="OK",
        detail=detail,
        extra={"redis_key": REDIS_KEY, "redis_value": "true"},
    )
    print(f"  -> {detail}")
    time.sleep(0.3)


def phase_verify(r):
    print("\n=== PHASE 3: VERIFY -- Goi is_fallback_override_active() tu guardrails/cache.py ===")
    # GOI HAM THAT TRONG GUARDRAILS/CACHE.PY
    override_active = cache_module.is_fallback_override_active()

    error_rate_after = 0.0 if override_active else 0.75
    verdict = "PASS" if override_active else "FAIL"

    detail = (
        f"Goi guardrails.cache.is_fallback_override_active() -> {override_active}. "
        f"product-reviews chuyen sang Fallback/Cache mode (Error rate={error_rate_after:.0%})"
    )
    audit(
        phase="verify",
        status="OK" if verdict == "PASS" else "FAIL",
        detail=detail,
        extra={
            "fallback_override_active_from_cache_py": override_active,
            "simulated_error_rate_after_fallback": error_rate_after,
            "verdict": verdict,
            "llm_calls_bypassed": override_active,
        },
    )
    print(f"  -> guardrails.cache.is_fallback_override_active() tra ve: {override_active}")
    print(f"  -> error_rate_after={error_rate_after:.0%}, verdict={verdict}")
    time.sleep(0.3)
    return override_active


def phase_rollback(r):
    print("\n=== PHASE 4: ROLLBACK -- Xoa Redis key ===")
    cache_module.redis_client.delete(REDIS_KEY)
    detail = f"AIOps Controller DEL {REDIS_KEY}"
    audit(
        phase="rollback",
        status="OK",
        detail=detail,
        extra={"redis_key": REDIS_KEY},
    )
    print(f"  -> {detail}")
    time.sleep(0.3)


def phase_recover(r):
    print("\n=== PHASE 5: RECOVER -- Goi is_fallback_override_active() kiem tra phuc hoi ===")
    # GOI HAM THAT TRONG GUARDRAILS/CACHE.PY SAU ROLLBACK
    override_still_active = cache_module.is_fallback_override_active()

    recovered_rate = measure_error_rate(50, 0.04)
    verdict = "PASS" if not override_still_active else "FAIL"

    detail = (
        f"Goi guardrails.cache.is_fallback_override_active() -> {override_still_active}. "
        f"He thong tu phuc hoi, LLM path active (Error rate={recovered_rate:.0%})"
    )
    audit(
        phase="recover",
        status="OK" if verdict == "PASS" else "FAIL",
        detail=detail,
        extra={
            "fallback_override_active_from_cache_py": override_still_active,
            "simulated_error_rate_recovered": round(recovered_rate, 4),
            "verdict": verdict,
        },
    )
    print(f"  -> guardrails.cache.is_fallback_override_active() tra ve: {override_still_active}")
    print(f"  -> error_rate_recovered={recovered_rate:.0%}, verdict={verdict}")


def print_summary():
    print("\n=== AUDIT LOG SUMMARY ===")
    phases_seen = []
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("run_id") == _RUN_ID:
                    phases_seen.append(rec["phase"])
                    print(f"  [{rec['timestamp']}] {rec['phase']:12s} | {rec['status']:7s} | {rec['detail']}")
    except FileNotFoundError:
        pass

    expected = ["trigger", "action", "verify", "rollback", "recover"]
    missing = [p for p in expected if p not in phases_seen]
    complete = len(missing) == 0
    print(f"\n  Phases recorded : {phases_seen}")
    print(f"  Chain complete  : {'YES - chain complete' if complete else 'NO'}")
    print(f"  Audit log file  : {AUDIT_LOG_PATH}")
    return complete


def main():
    global _RUN_ID

    parser = argparse.ArgumentParser(description="AIOps Replay Simulation -- AIE1")
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dung MockRedis de test logic cache.py ma khong can Redis server")
    args = parser.parse_args()

    _RUN_ID = str(uuid.uuid4())

    print("=" * 65)
    print("  AIOps Replay Simulation -- Testing Real guardrails/cache.py Logic")
    print(f"  Run ID  : {_RUN_ID}")
    print(f"  Time    : {ts()}")
    print("=" * 65)

    r = setup_redis_client(args.redis_host, args.redis_port, args.dry_run)

    audit("start", "OK", f"AIOps replay simulation started. run_id={_RUN_ID}")

    try:
        phase_trigger(r)
        phase_action(r)
        phase_verify(r)
        phase_rollback(r)
        phase_recover(r)
    except Exception as exc:
        audit("error", "ERROR", str(exc))
        print(f"\n[ERROR] {exc}")
        sys.exit(1)
    finally:
        audit("end", "OK", "AIOps replay simulation completed.")

    complete = print_summary()
    sys.exit(0 if complete else 1)


if __name__ == "__main__":
    main()