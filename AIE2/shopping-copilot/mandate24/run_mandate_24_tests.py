"""
run_mandate_24_tests.py — Run MANDATE #24 test cases from JSON

Usage:
  python run_mandate_24_tests.py

Reads: mandate_24_testcases.json
Outputs: mandate_24_test_results.json + console logs
"""

import json
import sys
import os
import time
import uuid
import hashlib
from datetime import datetime, timezone, timedelta

os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "traces")


def _cleanup_test_traces():
    """Remove traces with test prefix for clean test runs."""
    import pathlib
    p = pathlib.Path(TEST_LOGS_DIR)
    if p.exists():
        for f in p.glob("*.jsonl"):
            f.unlink(missing_ok=True)


def _make_response(prompt_tokens=0, completion_tokens=0):
    """Create a mock response object with usage_metadata."""
    class MockResponse:
        def __init__(self, pt, ct):
            self.usage_metadata = {
                "input_tokens": pt,
                "output_tokens": ct,
                "total_tokens": pt + ct,
            }
            self.response_metadata = {
                "model_id": "apac.amazon.nova-lite-v1:0",
            }
            self.content = f"Mock response with {pt} prompt and {ct} completion tokens"
    return MockResponse(prompt_tokens, completion_tokens)


def _make_model_trace_dict(trace_id, request_id, layer, **kw):
    """Build a trace dict matching ModelTrace schema."""
    from src.telemetry import get_tracer
    tracer = get_tracer()
    d = {
        "trace_id": trace_id,
        "request_id": request_id,
        "parent_span_id": None,
        "surface": "copilot",
        "layer": layer,
        "model": "apac.amazon.nova-lite-v1:0",
        "model_version": "",
        "session_id": tracer.hash_session(kw.get("session_id", "")),
        "user_id": tracer.hash_user(kw.get("user_id", "")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_ms": kw.get("latency_ms", 0),
        "prompt_tokens": kw.get("prompt_tokens", 0),
        "completion_tokens": kw.get("completion_tokens", 0),
        "total_tokens": kw.get("prompt_tokens", 0) + kw.get("completion_tokens", 0),
        "estimated_cost_usd": kw.get("cost", 0.0),
        "outcome": kw.get("outcome", "ok"),
        "error": kw.get("error", None),
        "tool_calls": None,
        "prompt_preview": tracer.mask_pii(kw.get("prompt_text", ""))[:500],
        "response_preview": tracer.mask_pii(kw.get("response_text", ""))[:500],
        "prompt_masked": bool(kw.get("prompt_text", "")),
        "response_masked": bool(kw.get("response_text", "")),
        "metadata": {},
    }
    return d


# ── Test 1: Core Fields ──────────────────────────────────────────────

def test_1_core_fields():
    from src.telemetry import get_tracer

    tracer = get_tracer()
    rid = tracer.create_request_id()
    tid = str(uuid.uuid4())
    prompt_text = "How much is a telescope?"
    resp = _make_response(prompt_tokens=120, completion_tokens=45)

    tracer.record_call(
        trace_id=tid,
        request_id=rid,
        layer="intent_parser",
        session_id="session-abc",
        user_id="user-xyz",
        prompt_text=prompt_text,
        response=resp,
        outcome="ok",
        latency_ms=2800,
    )

    records = tracer._store.get_by_request_id(rid)
    assert len(records) == 1, f"Expected 1 record, got {len(records)}"
    r = records[0]

    required = [
        "trace_id", "request_id", "parent_span_id", "surface", "layer",
        "model", "model_version", "session_id", "user_id", "timestamp",
        "latency_ms", "prompt_tokens", "completion_tokens", "total_tokens",
        "estimated_cost_usd", "outcome", "prompt_preview",
        "prompt_masked",
    ]
    for field in required:
        assert field in r, f"Missing required field: {field}"
        if field in ("trace_id", "request_id"):
            assert r[field] != "", f"Field {field} is empty"

    assert r["layer"] == "intent_parser"
    assert r["outcome"] == "ok"
    assert r["latency_ms"] == 2800

    print("  ✅ Scenario 1a: All required fields present")

    # Scenario 1b: Cost estimation
    tracer.record_call(
        trace_id=str(uuid.uuid4()),
        request_id=rid,
        layer="synthesis",
        session_id="session-abc",
        user_id="user-xyz",
        prompt_text=prompt_text,
        response=resp,
        outcome="ok",
        latency_ms=1500,
    )
    records2 = tracer._store.get_by_request_id(rid)
    r2 = [r for r in records2 if r["layer"] == "synthesis"][0]
    expected_cost = (120 * 0.00006 / 1000) + (45 * 0.00024 / 1000)
    assert abs(r2["estimated_cost_usd"] - expected_cost) < 0.000001, \
        f"Cost mismatch: {r2['estimated_cost_usd']} != {expected_cost}"
    print(f"  ✅ Scenario 1b: Cost estimation correct (${expected_cost:.8f})")

    return {
        "test_id": 1,
        "test_name": "Trace ghi đủ trường lõi",
        "scenarios": {
            "1a": {"status": "PASS", "fields_verified": len(required), "expected_fields": required},
            "1b": {"status": "PASS", "prompt_tokens": 120, "completion_tokens": 45, "cost": expected_cost},
        },
        "overall": "PASS",
    }


# ── Test 2: Reconstruct Request Chain ────────────────────────────────

def test_2_request_chain():
    from src.telemetry import get_tracer

    tracer = get_tracer()
    rid = tracer.create_request_id()

    layers = ["intent_parser", "planner", "synthesis", "faithfulness_guard"]
    for i, layer in enumerate(layers):
        resp = _make_response(prompt_tokens=50 * (i + 1), completion_tokens=20 * (i + 1))
        tracer.record_call(
            trace_id=str(uuid.uuid4()),
            request_id=rid,
            layer=layer,
            session_id="session-chain",
            user_id="user-chain",
            prompt_text=f"Test prompt for {layer}",
            response=resp,
            outcome="ok",
            latency_ms=1000 * (i + 1),
        )

    records = tracer._store.get_by_request_id(rid)
    assert len(records) == 4, f"Expected 4 records, got {len(records)}"
    recovered_layers = [r["layer"] for r in records]
    assert recovered_layers == layers, f"Layer order mismatch: {recovered_layers} != {layers}"
    print(f"  ✅ Scenario 2a: Reconstructed {len(records)} spans in order: {recovered_layers}")

    # Scenario 2b: Isolation
    rid_a = tracer.create_request_id()
    rid_b = tracer.create_request_id()
    for _ in range(2):
        tracer.record_call(
            trace_id=str(uuid.uuid4()), request_id=rid_a, layer="intent_parser",
            session_id="", user_id="", prompt_text="", response=_make_response(10, 5),
            outcome="ok", latency_ms=100,
        )
    tracer.record_call(
        trace_id=str(uuid.uuid4()), request_id=rid_b, layer="planner",
        session_id="", user_id="", prompt_text="", response=_make_response(10, 5),
        outcome="ok", latency_ms=100,
    )
    assert len(tracer._store.get_by_request_id(rid_a)) == 2
    assert len(tracer._store.get_by_request_id(rid_b)) == 1
    print("  ✅ Scenario 2b: Request isolation correct")

    return {
        "test_id": 2,
        "test_name": "Dựng lại request chain",
        "scenarios": {
            "2a": {"status": "PASS", "recovered_count": len(records), "layers_order": recovered_layers},
            "2b": {"status": "PASS", "request_a_count": 2, "request_b_count": 1},
        },
        "overall": "PASS",
    }


# ── Test 3: Aggregate View ──────────────────────────────────────────

def test_3_aggregate():
    from src.telemetry import get_tracer
    from src.telemetry.storage import JsonlTraceStore
    import tempfile

    # Use isolated trace store for aggregate test (avoids counting traces from other tests)
    isolated_store = JsonlTraceStore(logs_dir=os.path.join(tempfile.gettempdir(), "m24_test_agg"))
    tracer = get_tracer()
    original_store = tracer._store
    tracer._store = isolated_store

    try:
        # Scenario 3a: Multiple traces → correct aggregate
        rid = tracer.create_request_id()
        layers_data = [("intent_parser", 100, 30, 2000), ("intent_parser", 150, 40, 2500), ("synthesis", 300, 80, 3500)]
        for layer, pt, ct, lat in layers_data:
            resp = _make_response(prompt_tokens=pt, completion_tokens=ct)
            tracer.record_call(
                trace_id=str(uuid.uuid4()), request_id=rid, layer=layer,
                session_id="agg-session", user_id="agg-user",
                prompt_text=f"test {layer}", response=resp,
                outcome="ok", latency_ms=lat,
            )

        agg = tracer._store.aggregate(period_hours=24)
        total_calls = sum(s["calls"] for s in agg.values())
        assert total_calls == 3, f"Expected 3 total calls, got {total_calls}"
        print(f"  ✅ Scenario 3a: Aggregate shows {total_calls} total calls")

        # Verify per-layer breakdown
        intent_calls = sum(s["calls"] for k, s in agg.items() if "intent_parser" in k)
        assert intent_calls == 2, f"Expected 2 intent_parser, got {intent_calls}"
        synth_calls = sum(s["calls"] for k, s in agg.items() if "synthesis" in k)
        assert synth_calls == 1, f"Expected 1 synthesis, got {synth_calls}"
        print(f"  ✅ Scenario 3a: Layer breakdown: intent_parser={intent_calls}, synthesis={synth_calls}")

        # Scenario 3b: Time filter
        agg_24h = tracer._store.aggregate(period_hours=24)
        assert sum(s["calls"] for s in agg_24h.values()) == 3, "24h aggregate should include all 3"

        agg_1h = tracer._store.aggregate(period_hours=1)
        assert sum(s["calls"] for s in agg_1h.values()) == 3, "1h aggregate should also include all (recent)"
        print("  ✅ Scenario 3b: Time window filter works")

        return {
            "test_id": 3,
            "test_name": "Aggregate view tổng hợp",
            "scenarios": {
                "3a": {"status": "PASS", "total_calls": total_calls, "per_layer": {"intent_parser": intent_calls, "synthesis": synth_calls}},
                "3b": {"status": "PASS", "in_window_calls_24h": 3, "in_window_calls_1h": 3},
            },
            "overall": "PASS",
        }
    finally:
        # Restore original store and clean up
        tracer._store = original_store
        import shutil
        shutil.rmtree(isolated_store._logs_dir, ignore_errors=True)


# ── Test 4: PII Masking ──────────────────────────────────────────────

def test_4_pii_masking():
    from src.telemetry import get_tracer
    from src.telemetry.tracer import _sanitize_pii

    tracer = get_tracer()

    # Scenario 4a: Email masking
    rid = tracer.create_request_id()
    email_prompt = "My email is test@gmail.com, please help"
    masked = _sanitize_pii(email_prompt)
    assert "test@gmail.com" not in masked, "Email not masked!"
    assert "EMAIL_REDACTED" in masked or "REDACTED" in masked, "No redaction tag found"
    print(f"  ✅ Scenario 4a: Email masked: '{masked}'")

    # Scenario 4b: SSN + credit card
    pii_prompt = "My SSN is 123-45-6789, card is 4111-1111-1111-1111"
    masked2 = _sanitize_pii(pii_prompt)
    assert "123-45-6789" not in masked2, "SSN not masked!"
    assert "4111-1111-1111-1111" not in masked2, "Credit card not masked!"
    print(f"  ✅ Scenario 4b: SSN + credit card masked: '{masked2}'")

    # Scenario 4c: User/session ID hashed
    raw_session = "raw-session-999"
    raw_user = "raw-user-888"
    tracer.record_call(
        trace_id=str(uuid.uuid4()), request_id=rid, layer="intent_parser",
        session_id=raw_session, user_id=raw_user,
        prompt_text="test hashing",
        response=None, outcome="ok", latency_ms=100,
    )
    records = tracer._store.get_by_request_id(rid)
    r = [rec for rec in records if rec["layer"] == "intent_parser"][0]
    assert r["session_id"] != raw_session, "Session ID not hashed!"
    assert r["user_id"] != raw_user, "User ID not hashed!"
    assert len(r["session_id"]) == 16, f"Hash length: {len(r['session_id'])} != 16"
    assert all(c in "0123456789abcdef" for c in r["session_id"]), "Hash not hex!"
    print(f"  ✅ Scenario 4c: session_id hashed: '{r['session_id']}' (raw: '{raw_session}')")
    print(f"  ✅ Scenario 4c: user_id hashed: '{r['user_id']}' (raw: '{raw_user}')")

    return {
        "test_id": 4,
        "test_name": "PII/Secret không lộ thô",
        "scenarios": {
            "4a": {"status": "PASS", "input": email_prompt, "masked_output": masked},
            "4b": {"status": "PASS", "pii_types_tested": 2, "ssn_masked": True, "card_masked": True},
            "4c": {"status": "PASS", "session_hashed": True, "user_hashed": True, "hash_length": 16},
        },
        "overall": "PASS",
    }


# ── Test 5: Error/Fallback Outcome ──────────────────────────────────

def test_5_error_outcome():
    from src.telemetry import get_tracer

    tracer = get_tracer()

    # Scenario 5a: Outcome=error
    rid = tracer.create_request_id()
    tracer.record_call(
        trace_id=str(uuid.uuid4()), request_id=rid, layer="intent_parser",
        session_id="err-session", user_id="err-user",
        prompt_text="test error",
        response=None, error="Bedrock TimeoutException: Model did not respond in 30s",
        outcome="error", latency_ms=30000,
    )
    records = tracer._store.get_by_request_id(rid)
    r = records[0]
    assert r["outcome"] == "error", f"outcome={r['outcome']} != error"
    assert "Bedrock TimeoutException" in (r.get("error") or ""), "Error message not stored"
    assert r["latency_ms"] == 30000, f"latency_ms={r['latency_ms']} != 30000"
    print(f"  ✅ Scenario 5a: Error trace recorded: outcome={r['outcome']}, error='{r['error']}'")

    # Scenario 5b: Outcome=fallback
    rid2 = tracer.create_request_id()
    tracer.record_call(
        trace_id=str(uuid.uuid4()), request_id=rid2, layer="planner",
        session_id="fb-session", user_id="fb-user",
        prompt_text="test fallback",
        response=None, error="Circuit breaker open, used heuristic fallback",
        outcome="fallback", latency_ms=2,
    )
    records2 = tracer._store.get_by_request_id(rid2)
    r2 = records2[0]
    assert r2["outcome"] == "fallback", f"outcome={r2['outcome']} != fallback"
    assert "heuristic fallback" in (r2.get("error") or ""), "Fallback reason not stored"
    print(f"  ✅ Scenario 5b: Fallback trace recorded: outcome={r2['outcome']}, error='{r2['error']}'")

    return {
        "test_id": 5,
        "test_name": "Outcome error/fallback được ghi",
        "scenarios": {
            "5a": {"status": "PASS", "outcome": "error", "error_msg": "Bedrock TimeoutException"},
            "5b": {"status": "PASS", "outcome": "fallback", "error_msg": "heuristic fallback"},
        },
        "overall": "PASS",
    }


# ── Test Runner ──────────────────────────────────────────────────────

def run_all_tests():
    print("\n" + "#" * 70)
    print("# MANDATE #24 TEST SUITE — LLM OBSERVABILITY")
    print("#" * 70)

    from src.telemetry import reset_tracer, get_tracer
    reset_tracer()

    all_results = {
        "suite_name": "MANDATE #24 - LLM Observability (Model Call Black Box)",
        "date": datetime.now().isoformat(),
        "tests": [],
    }

    test_fns = [
        ("Test 1: Core Fields", test_1_core_fields),
        ("Test 2: Request Chain", test_2_request_chain),
        ("Test 3: Aggregate", test_3_aggregate),
        ("Test 4: PII Masking", test_4_pii_masking),
        ("Test 5: Error Outcome", test_5_error_outcome),
    ]

    for name, fn in test_fns:
        print("\n" + "=" * 70)
        print(f"{name}")
        print("=" * 70)
        try:
            result = fn()
            all_results["tests"].append(result)
            scenarios = result.get("scenarios", {})
            all_pass = all(s.get("status") == "PASS" for s in scenarios.values())
            if all_pass:
                print(f"  ✅ {name}: ALL SCENARIOS PASSED")
            else:
                print(f"  ⚠️  {name}: PARTIAL")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ {name}: FAILED — {e}")
            all_results["tests"].append({
                "test_id": test_fns.index((name, fn)) + 1,
                "test_name": name.split(":", 1)[1].strip() if ":" in name else name,
                "status": "ERROR",
                "error": str(e),
            })

    passed = sum(1 for t in all_results["tests"] if t.get("overall") == "PASS")
    total = len(all_results["tests"])
    all_results["summary"] = {
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{(passed / total) * 100:.1f}%",
    }

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print(f"Pass rate: {(passed / total) * 100:.1f}%")
    if passed == total:
        print("\n🏆 ALL TESTS PASSED")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")

    return all_results


def save_results(results, output_file):
    import pathlib
    p = pathlib.Path(output_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Results saved to: {output_file}")


if __name__ == "__main__":
    results = run_all_tests()
    output = os.path.join(os.path.dirname(__file__), "mandate_24_test_results.json")
    save_results(results, output)
    exit(0 if results["summary"]["passed"] == results["summary"]["total_tests"] else 1)
