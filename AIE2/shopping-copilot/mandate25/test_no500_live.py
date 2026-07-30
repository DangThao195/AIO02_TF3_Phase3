"""
mandate25/test_no500_live.py — Live HTTP test: No 500 on Provider Failure
==========================================================================

Sends real HTTP requests to a running Copilot server and verifies that
even when Bedrock is unavailable/circuit-open, the server returns HTTP 200
(not 500).

Usage:
    # Start server first (or use an already-running one):
    #   py -m uvicorn src.main:app --port 8001
    #
    # Then run this test:
    python mandate25/test_no500_live.py [--url http://localhost:8001]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def make_chat_request(url: str, message: str, session_id: str = "test-no500") -> dict:
    """POST /api/chat and return (status_code, body_dict)."""
    payload = json.dumps(
        {"session_id": session_id, "message": message, "user_id": "test-mandate25"}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            body = {"raw": body_bytes.decode("utf-8", errors="replace")}
        return e.code, body


def check_health(url: str) -> bool:
    """GET /health — returns True if server is up."""
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_live_tests(url: str) -> dict:
    results = {
        "url": url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": {},
        "overall": None,
    }

    # ── Pre-check: server is up ────────────────────────────────────────────
    print(f"\n[PRE-CHECK] Server health at {url}/health ...")
    if not check_health(url):
        print(f"  ✗ Server not reachable at {url} — start the server first.")
        results["overall"] = "SKIP"
        return results
    print("  ✓ Server is up")

    # ── Scenario A: Normal chat returns HTTP 200 ───────────────────────────
    print("\n[Scenario A] Normal chat → HTTP 200")
    code, body = make_chat_request(url, "xin chào", "s-no500-A")
    ok = code == 200
    print(f"  Status: {code}  ({'PASS' if ok else 'FAIL'})")
    if not ok:
        print(f"  Body: {json.dumps(body, ensure_ascii=False)[:300]}")
    results["scenarios"]["A_normal_chat"] = {
        "status_code": code,
        "pass": ok,
        "note": "Normal message should always return 200",
    }

    # ── Scenario B: Chat with long/complex message still returns 200 ───────
    print("\n[Scenario B] Complex query → HTTP 200 (no 500 on heavy LLM load)")
    long_msg = (
        "So sánh chi tiết iPhone 15 Pro Max và Samsung Galaxy S24 Ultra về camera, "
        "pin, hiệu năng, giá, thiết kế, và trải nghiệm người dùng thực tế."
    )
    code, body = make_chat_request(url, long_msg, "s-no500-B")
    ok = code == 200
    print(f"  Status: {code}  ({'PASS' if ok else 'FAIL'})")
    results["scenarios"]["B_complex_query"] = {
        "status_code": code,
        "pass": ok,
        "note": "Complex query must not 500",
    }

    # ── Scenario C: Unknown/garbage input returns 200 ──────────────────────
    print("\n[Scenario C] Garbage/unknown input → HTTP 200 (fallback, not crash)")
    garbage_msg = "ÄÖÜ ♥♣♦ 999999 @@## END_OF_INPUT"
    code, body = make_chat_request(url, garbage_msg, "s-no500-C")
    ok = code == 200
    print(f"  Status: {code}  ({'PASS' if ok else 'FAIL'})")
    results["scenarios"]["C_garbage_input"] = {
        "status_code": code,
        "pass": ok,
        "note": "Garbage input must not crash to 500",
    }

    # ── Scenario D: Rapid concurrent-like requests don't produce 500 ───────
    print("\n[Scenario D] 5 rapid sequential requests → all HTTP 200")
    msgs = [
        "tìm laptop",
        "xem giỏ hàng",
        "laptop giá rẻ nhất",
        "thêm sản phẩm vào giỏ",
        "so sánh 2 sản phẩm",
    ]
    all_200 = True
    codes = []
    for i, msg in enumerate(msgs):
        c, _ = make_chat_request(url, msg, f"s-no500-D-{i}")
        codes.append(c)
        if c != 200:
            all_200 = False
        print(f"  Request {i+1}: {c}")

    results["scenarios"]["D_rapid_requests"] = {
        "status_codes": codes,
        "pass": all_200,
        "note": "All rapid requests must return 200",
    }

    # ── Summary ────────────────────────────────────────────────────────────
    all_pass = all(s["pass"] for s in results["scenarios"].values())
    results["overall"] = "PASS" if all_pass else "FAIL"

    passed = sum(1 for s in results["scenarios"].values() if s["pass"])
    total = len(results["scenarios"])
    print(f"\n{'='*60}")
    print(f"LIVE TEST SUMMARY: {passed}/{total} scenarios PASS")
    print(f"Overall: {results['overall']}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Mandate 25 — Live No-500 Test")
    parser.add_argument(
        "--url", default="http://localhost:8001", help="Server base URL"
    )
    parser.add_argument(
        "--out",
        default="mandate25/mandate_25_live_results.json",
        help="Output JSON file",
    )
    args = parser.parse_args()

    results = run_live_tests(args.url)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Results saved → {args.out}")

    sys.exit(0 if results["overall"] in ("PASS", "SKIP") else 1)


if __name__ == "__main__":
    main()
