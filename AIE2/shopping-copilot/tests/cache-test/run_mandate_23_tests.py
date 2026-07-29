"""
tests/cache-test/run_mandate_23_tests.py — Test Runner cho MANDATE #23 (Enterprise Edition)

Chạy toàn bộ test suite với ma trận kiểm thử đầy đủ:
1. GenAI Cache hit/miss & Semantic Cache matching
2. Short-term Memory (10 testcases, 1 user -> 5 turns/session)
3. Long-term Memory (3 testcases, 3 users -> 3 sessions/user -> 5 turns/session)
4. Cross-user Isolation (5 testcases, 3 users -> 2 sessions/user -> 2 turns/session)
5. Cache Invalidation & Entity Tagging

Kiểm tra 100% cờ expected_cache (hit/miss) và xuất báo cáo chỉ số đầy đủ:
Hit-rate, Latency, Token Usage, Cost Savings & Pass/Fail per testcase.

Usage:
    python tests/cache-test/run_mandate_23_tests.py --api-url http://localhost:8001
"""

import sys
import os
import json
import time
import argparse
import statistics
from typing import List, Dict, Any
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

try:
    import requests
except ImportError:
    print("❌ Cần cài đặt: pip install requests")
    sys.exit(1)


class Mandate23TestRunner:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")
        self.results = {
            "test_run_timestamp": datetime.now().isoformat(),
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "test_details": [],
            "metrics": {
                "total_requests": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "hit_rate_percent": 0.0,
                "latencies_hit_ms": [],
                "latencies_miss_ms": [],
                "avg_latency_hit_ms": 0.0,
                "avg_latency_miss_ms": 0.0,
                "latency_improvement_percent": 0.0,
                "estimated_tokens_consumed": 0,
                "estimated_tokens_saved": 0,
                "estimated_cost_savings_usd": 0.0,
            },
        }

    def load_testcases(self, filepath: str) -> Dict[str, Any]:
        """Load test cases from JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def call_api_chat(
        self, user_id: str, session_id: str, message: str
    ) -> Dict[str, Any]:
        """Call /api/chat endpoint."""
        url = f"{self.api_url}/api/chat"
        start_time = time.time()

        try:
            response = requests.post(
                url,
                json={"user_id": user_id, "session_id": session_id, "message": message},
                timeout=60,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                data = response.json()
                cache_flag = data.get("cache", "miss")

                # Estimate tokens (approx 4 chars = 1 token for prompt + completion)
                est_tokens = len(message) // 4 + len(data.get("reply", "")) // 4 + 150

                self.results["metrics"]["total_requests"] += 1
                if cache_flag == "hit":
                    self.results["metrics"]["cache_hits"] += 1
                    self.results["metrics"]["latencies_hit_ms"].append(latency_ms)
                    self.results["metrics"]["estimated_tokens_saved"] += est_tokens
                else:
                    self.results["metrics"]["cache_misses"] += 1
                    self.results["metrics"]["latencies_miss_ms"].append(latency_ms)
                    self.results["metrics"]["estimated_tokens_consumed"] += est_tokens

                return {
                    "status": "ok",
                    "data": data,
                    "latency_ms": latency_ms,
                    "cache": cache_flag,
                    "tokens": est_tokens,
                }
            else:
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "latency_ms": latency_ms,
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "latency_ms": int((time.time() - start_time) * 1000),
            }

    def call_api_clear_cache(self) -> Dict[str, Any]:
        """Call /api/v1/cache/clear to reset cache before testing."""
        url = f"{self.api_url}/api/v1/cache/clear"
        try:
            response = requests.post(url, timeout=10)
            if response.status_code == 200:
                return {"status": "ok", "data": response.json()}
            else:
                return {"status": "error", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def call_api_invalidate(self, entity_type: str, entity_id: str) -> Dict[str, Any]:
        """Call /api/v1/cache/invalidate endpoint."""
        url = f"{self.api_url}/api/v1/cache/invalidate"

        try:
            response = requests.post(
                url,
                json={"entity_type": entity_type, "entity_id": entity_id},
                timeout=10,
            )

            if response.status_code == 200:
                return {"status": "ok", "data": response.json()}
            else:
                return {"status": "error", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def run_short_term_memory_tests(self, testcases: List[Dict]) -> None:
        """Run in-session memory tests (Group 1)."""
        print("\n" + "=" * 80)
        print("📝 GROUP 1: SHORT-TERM MEMORY (In-session Context)")
        print("=" * 80)

        for tc in testcases:
            test_id = tc["test_id"]
            user_id = tc["user_id"]
            session_id = tc["session_id"]
            turns = tc["turns"]

            print(f"\n🧪 Test {test_id}: {len(turns)} turns (User: {user_id})")
            test_result = {
                "test_id": test_id,
                "group": "short_term_memory",
                "turns": [],
                "passed": True,
                "errors": [],
            }

            for turn_data in turns:
                turn_num = turn_data["turn"]
                request = turn_data["request"]
                expected_cache = turn_data.get("expected_cache", "miss")

                print(f"  Turn {turn_num}: {request[:55]}...")
                result = self.call_api_chat(user_id, session_id, request)

                turn_result = {
                    "turn": turn_num,
                    "request": request,
                    "status": result["status"],
                    "latency_ms": result["latency_ms"],
                    "cache": result.get("cache", "unknown"),
                    "expected_cache": expected_cache,
                }

                if result["status"] == "ok":
                    reply = result["data"].get("reply", "")
                    turn_result["reply"] = reply[:100]
                    cache_flag = result.get("cache", "miss")

                    # Validate expected cache
                    if expected_cache and cache_flag != expected_cache:
                        test_result["passed"] = False
                        test_result["errors"].append(
                            f"Turn {turn_num}: Expected cache '{expected_cache}', got '{cache_flag}'"
                        )
                        print(
                            f"    ❌ CACHE MISMATCH: Expected '{expected_cache}', got '{cache_flag}' | {result['latency_ms']}ms"
                        )
                    else:
                        print(
                            f"    ✅ OK | cache={cache_flag} | {result['latency_ms']}ms"
                        )
                else:
                    turn_result["error"] = result.get("error")
                    test_result["passed"] = False
                    test_result["errors"].append(
                        f"Turn {turn_num}: {result.get('error')}"
                    )
                    print(f"    ❌ FAIL: {result.get('error')}")

                test_result["turns"].append(turn_result)
                time.sleep(0.3)

            self.results["test_details"].append(test_result)
            self.results["total_tests"] += 1

            if test_result["passed"]:
                self.results["passed"] += 1
                print(f"  ✅ {test_id} PASSED")
            else:
                self.results["failed"] += 1
                print(f"  ❌ {test_id} FAILED")

    def run_long_term_memory_tests(self, testcases: List[Dict]) -> None:
        """Run cross-session memory tests (Group 2)."""
        print("\n" + "=" * 80)
        print("🧠 GROUP 2: LONG-TERM MEMORY (Cross-session Persistence)")
        print("=" * 80)

        for tc in testcases:
            test_id = tc["test_id"]
            users = tc.get("users", [])

            print(f"\n🧪 Test {test_id}: {len(users)} users matrix")
            test_result = {
                "test_id": test_id,
                "group": "long_term_memory",
                "users": [],
                "passed": True,
                "errors": [],
            }

            for user_data in users:
                user_id = user_data["user_id"]
                sessions = user_data["sessions"]
                print(f"\n  👤 User {user_id} ({len(sessions)} sessions):")

                user_res = {"user_id": user_id, "sessions": []}

                for sess_data in sessions:
                    session_id = sess_data["session_id"]
                    turns = sess_data["turns"]

                    print(f"    📂 Session {session_id}:")
                    session_result = {"session_id": session_id, "turns": []}

                    for turn_data in turns:
                        turn_num = turn_data["turn"]
                        request = turn_data["request"]
                        expected_cache = turn_data.get("expected_cache", "miss")

                        print(f"      Turn {turn_num}: {request[:45]}...")
                        result = self.call_api_chat(user_id, session_id, request)

                        turn_result = {
                            "turn": turn_num,
                            "request": request,
                            "status": result["status"],
                            "latency_ms": result["latency_ms"],
                            "cache": result.get("cache", "unknown"),
                            "expected_cache": expected_cache,
                        }

                        if result["status"] == "ok":
                            cache_flag = result.get("cache", "miss")
                            turn_result["reply"] = result["data"].get("reply", "")[:100]

                            if expected_cache and cache_flag != expected_cache:
                                test_result["passed"] = False
                                test_result["errors"].append(
                                    f"{user_id}/{session_id} Turn {turn_num}: Expected '{expected_cache}', got '{cache_flag}'"
                                )
                                print(
                                    f"        ❌ MISMATCH: Expected '{expected_cache}', got '{cache_flag}' | {result['latency_ms']}ms"
                                )
                            else:
                                print(
                                    f"        ✅ OK | cache={cache_flag} | {result['latency_ms']}ms"
                                )
                        else:
                            turn_result["error"] = result.get("error")
                            test_result["passed"] = False
                            test_result["errors"].append(
                                f"{user_id}/{session_id} Turn {turn_num}: {result.get('error')}"
                            )
                            print(f"        ❌ FAIL: {result.get('error')}")

                        session_result["turns"].append(turn_result)
                        time.sleep(0.3)

                    user_res["sessions"].append(session_result)
                    time.sleep(0.5)

                test_result["users"].append(user_res)

            self.results["test_details"].append(test_result)
            self.results["total_tests"] += 1

            if test_result["passed"]:
                self.results["passed"] += 1
                print(f"  ✅ {test_id} PASSED")
            else:
                self.results["failed"] += 1
                print(f"  ❌ {test_id} FAILED")

    def run_isolation_tests(self, testcases: List[Dict]) -> None:
        """Run cross-user isolation tests (Group 3)."""
        print("\n" + "=" * 80)
        print("🔒 GROUP 3: CROSS-USER ISOLATION (Leak Prevention)")
        print("=" * 80)

        for tc in testcases:
            test_id = tc["test_id"]
            description = tc.get("description", "")
            users = tc["users"]

            print(f"\n🧪 Test {test_id}: {description}")
            test_result = {
                "test_id": test_id,
                "group": "isolation",
                "users": [],
                "passed": True,
                "errors": [],
            }

            for user_data in users:
                user_id = user_data["user_id"]
                sessions = user_data.get("sessions", [])

                print(f"\n  👤 User {user_id}:")
                user_result = {"user_id": user_id, "sessions": []}

                for sess_data in sessions:
                    session_id = sess_data["session_id"]
                    turns = sess_data["turns"]

                    session_res = {"session_id": session_id, "turns": []}

                    for turn_data in turns:
                        turn_num = turn_data["turn"]
                        request = turn_data["request"]
                        expected_cache = turn_data.get("expected_cache")

                        print(f"    [{session_id}] Turn {turn_num}: {request[:45]}...")
                        result = self.call_api_chat(user_id, session_id, request)

                        turn_result = {
                            "turn": turn_num,
                            "request": request,
                            "status": result["status"],
                            "cache": result.get("cache", "unknown"),
                            "expected_cache": expected_cache,
                            "latency_ms": result["latency_ms"],
                        }

                        if result["status"] == "ok":
                            cache_flag = result.get("cache", "miss")
                            turn_result["reply"] = result["data"].get("reply", "")[:100]

                            if expected_cache and cache_flag != expected_cache:
                                test_result["passed"] = False
                                test_result["errors"].append(
                                    f"{user_id}/{session_id} Turn {turn_num}: Expected '{expected_cache}', got '{cache_flag}'"
                                )
                                print(
                                    f"      ❌ ISOLATION LEAK / MISMATCH: Expected '{expected_cache}', got '{cache_flag}'"
                                )
                            else:
                                print(
                                    f"      ✅ OK | cache={cache_flag} | {result['latency_ms']}ms"
                                )
                        else:
                            turn_result["error"] = result.get("error")
                            test_result["passed"] = False
                            test_result["errors"].append(
                                f"{user_id} Turn {turn_num}: {result.get('error')}"
                            )
                            print(f"      ❌ FAIL: {result.get('error')}")

                        session_res["turns"].append(turn_result)
                        time.sleep(0.3)

                    user_result["sessions"].append(session_res)

                test_result["users"].append(user_result)
                time.sleep(0.5)

            self.results["test_details"].append(test_result)
            self.results["total_tests"] += 1

            if test_result["passed"]:
                self.results["passed"] += 1
                print(f"  ✅ {test_id} PASSED (No leakage detected)")
            else:
                self.results["failed"] += 1
                print(f"  ❌ {test_id} FAILED (Leakage or mismatch)")

    def run_cache_tests(self, testcases: List[Dict]) -> None:
        """Run cache hit/miss, semantic match & invalidation tests (Group 4)."""
        print("\n" + "=" * 80)
        print("💾 GROUP 4: CACHE HIT/MISS & INVALIDATION")
        print("=" * 80)

        for tc in testcases:
            test_id = tc["test_id"]
            description = tc.get("description", "")

            print(f"\n🧪 Test {test_id}: {description}")
            test_result = {
                "test_id": test_id,
                "group": "cache",
                "steps": [],
                "passed": True,
                "errors": [],
            }

            if "turns" in tc:
                user_id = tc["user_id"]
                session_id = tc["session_id"]
                turns = tc["turns"]

                for turn_data in turns:
                    turn_num = turn_data["turn"]
                    request = turn_data["request"]
                    expected_cache = turn_data.get("expected_cache", "miss")

                    print(f"  Turn {turn_num}: {request[:50]}...")
                    result = self.call_api_chat(user_id, session_id, request)

                    step_result = {
                        "turn": turn_num,
                        "request": request,
                        "status": result["status"],
                        "cache": result.get("cache", "unknown"),
                        "expected_cache": expected_cache,
                        "latency_ms": result["latency_ms"],
                    }

                    if result["status"] == "ok":
                        cache_flag = result.get("cache", "miss")

                        if cache_flag != expected_cache:
                            test_result["passed"] = False
                            test_result["errors"].append(
                                f"Turn {turn_num}: Expected '{expected_cache}', got '{cache_flag}'"
                            )
                            print(
                                f"    ❌ FAIL: Expected '{expected_cache}', got '{cache_flag}'"
                            )
                        else:
                            print(
                                f"    ✅ OK | cache={cache_flag} | {result['latency_ms']}ms"
                            )
                    else:
                        step_result["error"] = result.get("error")
                        test_result["passed"] = False
                        test_result["errors"].append(
                            f"Turn {turn_num}: {result.get('error')}"
                        )
                        print(f"    ❌ FAIL: {result.get('error')}")

                    test_result["steps"].append(step_result)
                    time.sleep(0.3)

            elif "steps" in tc:
                user_id = tc["user_id"]
                session_id = tc["session_id"]
                steps = tc["steps"]

                for step_data in steps:
                    step_num = step_data["step"]
                    action = step_data["action"]

                    if action == "query":
                        request = step_data["request"]
                        expected_cache = step_data.get("expected_cache", "miss")
                        print(f"  Step {step_num} (query): {request[:50]}...")
                        result = self.call_api_chat(user_id, session_id, request)

                        step_result = {
                            "step": step_num,
                            "action": "query",
                            "request": request,
                            "status": result["status"],
                            "cache": result.get("cache", "unknown"),
                            "expected_cache": expected_cache,
                            "latency_ms": result["latency_ms"],
                        }

                        if result["status"] == "ok":
                            cache_flag = result.get("cache", "miss")

                            if cache_flag != expected_cache:
                                test_result["passed"] = False
                                test_result["errors"].append(
                                    f"Step {step_num}: Expected '{expected_cache}', got '{cache_flag}'"
                                )
                                print(
                                    f"    ❌ Expected '{expected_cache}', got '{cache_flag}'"
                                )
                            else:
                                print(
                                    f"    ✅ cache={cache_flag} | {result['latency_ms']}ms"
                                )
                        else:
                            step_result["error"] = result.get("error")
                            test_result["passed"] = False
                            print(f"    ❌ {result.get('error')}")

                        test_result["steps"].append(step_result)

                    elif action == "invalidate":
                        entity_type = step_data["entity_type"]
                        entity_id = step_data["entity_id"]
                        print(
                            f"  Step {step_num} (invalidate): {entity_type}:{entity_id}"
                        )
                        result = self.call_api_invalidate(entity_type, entity_id)

                        step_result = {
                            "step": step_num,
                            "action": "invalidate",
                            "entity": f"{entity_type}:{entity_id}",
                            "status": result["status"],
                        }

                        if result["status"] == "ok":
                            print(f"    ✅ Invalidated")
                        else:
                            step_result["error"] = result.get("error")
                            test_result["passed"] = False
                            print(f"    ❌ {result.get('error')}")

                        test_result["steps"].append(step_result)

                    time.sleep(0.3)

            self.results["test_details"].append(test_result)
            self.results["total_tests"] += 1

            if test_result["passed"]:
                self.results["passed"] += 1
                print(f"  ✅ {test_id} PASSED")
            else:
                self.results["failed"] += 1
                print(f"  ❌ {test_id} FAILED")

    def calculate_final_metrics(self) -> None:
        """Calculate aggregate metrics and fetch server-side cache stats."""
        metrics = self.results["metrics"]

        total_requests = metrics["total_requests"]
        if total_requests > 0:
            metrics["hit_rate_percent"] = round(
                (metrics["cache_hits"] / total_requests) * 100, 2
            )

        if metrics["latencies_hit_ms"]:
            metrics["avg_latency_hit_ms"] = round(
                statistics.mean(metrics["latencies_hit_ms"]), 1
            )
            metrics["p50_latency_hit_ms"] = round(
                statistics.median(metrics["latencies_hit_ms"]), 1
            )
            metrics["p95_latency_hit_ms"] = round(
                sorted(metrics["latencies_hit_ms"])[
                    int(len(metrics["latencies_hit_ms"]) * 0.95)
                ], 1
            ) if len(metrics["latencies_hit_ms"]) >= 2 else metrics["avg_latency_hit_ms"]

        if metrics["latencies_miss_ms"]:
            metrics["avg_latency_miss_ms"] = round(
                statistics.mean(metrics["latencies_miss_ms"]), 1
            )
            metrics["p50_latency_miss_ms"] = round(
                statistics.median(metrics["latencies_miss_ms"]), 1
            )
            metrics["p95_latency_miss_ms"] = round(
                sorted(metrics["latencies_miss_ms"])[
                    int(len(metrics["latencies_miss_ms"]) * 0.95)
                ], 1
            ) if len(metrics["latencies_miss_ms"]) >= 2 else metrics["avg_latency_miss_ms"]

        if metrics["avg_latency_miss_ms"] > 0 and metrics["avg_latency_hit_ms"] > 0:
            improvement = (
                (metrics["avg_latency_miss_ms"] - metrics["avg_latency_hit_ms"])
                / metrics["avg_latency_miss_ms"]
            ) * 100
            metrics["latency_improvement_percent"] = round(improvement, 1)

        # Estimate cost savings (assuming $0.0005 per 1k tokens)
        cost_per_1k_tokens = 0.001
        metrics["estimated_cost_savings_usd"] = round(
            (metrics["estimated_tokens_saved"] / 1000) * cost_per_1k_tokens, 4
        )

        # Fetch server-side cache metrics for the report
        try:
            resp = requests.get(f"{self.api_url}/api/v1/cache/metrics", timeout=10)
            if resp.status_code == 200:
                self.results["server_cache_metrics"] = resp.json()
        except Exception as e:
            self.results["server_cache_metrics"] = {"error": str(e)}

    def print_summary(self) -> None:
        """Print detailed test summary & metrics report."""
        print("\n" + "=" * 80)
        print("📊 MANDATE #23 ENTERPRISE TEST REPORT SUMMARY")
        print("=" * 80)

        print(f"\n🧪 Tests Run: {self.results['total_tests']}")
        print(f"✅ Passed: {self.results['passed']}")
        print(f"❌ Failed: {self.results['failed']}")
        pass_rate = (
            round((self.results["passed"] / self.results["total_tests"]) * 100, 1)
            if self.results["total_tests"] > 0
            else 0.0
        )
        print(f"📈 Overall Pass Rate: {pass_rate}%")

        metrics = self.results["metrics"]
        print(f"\n💾 Cache Metrics:")
        print(f"  • Total Requests: {metrics['total_requests']}")
        print(f"  • Cache Hits: {metrics['cache_hits']}")
        print(f"  • Cache Misses: {metrics['cache_misses']}")
        print(f"  • Hit Rate: {metrics['hit_rate_percent']}%")

        if metrics["avg_latency_hit_ms"] > 0:
            print(f"\n⚡ Latency Metrics:")
            print(f"  • Avg Latency (Cache Hit):  {metrics['avg_latency_hit_ms']}ms")
            print(f"  • Avg Latency (Cache Miss): {metrics['avg_latency_miss_ms']}ms")
            print(f"  • P50 Hit / Miss: {metrics.get('p50_latency_hit_ms', '-')}ms / {metrics.get('p50_latency_miss_ms', '-')}ms")
            print(f"  • P95 Hit / Miss: {metrics.get('p95_latency_hit_ms', '-')}ms / {metrics.get('p95_latency_miss_ms', '-')}ms")
            print(f"  • Improvement: {metrics['latency_improvement_percent']}%")

        print(f"\n🔤 Token & Cost Metrics:")
        print(f"  • Tokens Consumed: {metrics['estimated_tokens_consumed']} tokens")
        print(f"  • Tokens Saved: {metrics['estimated_tokens_saved']} tokens")
        print(f"  • Estimated Savings: ${metrics['estimated_cost_savings_usd']} USD")

        print(f"\n📋 Detailed Pass/Fail Table:")
        print("-" * 80)
        print(f"{'Test ID':<12} | {'Group':<22} | {'Status':<10} | {'Details'}")
        print("-" * 80)
        for td in self.results["test_details"]:
            status_str = "✅ PASS" if td["passed"] else "❌ FAIL"
            group_name = td.get("group", "")
            err_msg = (
                ", ".join(td.get("errors", []))[:30] if td.get("errors") else "All OK"
            )
            print(
                f"{td['test_id']:<12} | {group_name:<22} | {status_str:<10} | {err_msg}"
            )
        print("-" * 80)

        # Server-side GenAI cache stats
        server_metrics = self.results.get("server_cache_metrics", {})
        summary = server_metrics.get("summary", {})
        if summary:
            print(f"\n🖥️  Server-side GenAI Cache Stats:")
            print(f"  • Exact Hits: {summary.get('genai_hits_exact', 0)}")
            print(f"  • Semantic Hits: {summary.get('genai_hits_semantic', 0)}")
            print(f"  • Global Pool Hits: {summary.get('genai_hits_global', 0)}")
            print(f"  • Misses: {summary.get('genai_misses', 0)}")
            print(f"  • Server Hit Rate: {summary.get('genai_hit_rate_pct', 0)}%")
            print(f"  • Backend: {summary.get('backend', 'unknown')}")
            print(f"  • TTL: {summary.get('cache_ttl_seconds', 0)}s")

        print(f"\n⏰ Test Run Time: {self.results['test_run_timestamp']}")

    def save_results(self, output_file: str) -> None:
        """Save detailed results to JSON file."""
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Results saved to: {output_file}")

    def run_all_tests(self, testcases_file: str, output_file: str) -> None:
        """Run all test groups."""
        print("\n" + "=" * 80)
        print("🚀 MANDATE #23 ENTERPRISE TEST RUNNER")
        print("=" * 80)
        print(f"API URL: {self.api_url}")
        print(f"Test Cases: {testcases_file}")

        # Reset cache for a clean state before running benchmark
        clear_res = self.call_api_clear_cache()
        if clear_res.get("status") == "ok":
            print(f"🧹 {clear_res['data'].get('message', 'Cache cleared for clean test run')}")

        testcases = self.load_testcases(testcases_file)

        for group in testcases.get("test_groups", []):
            group_name = group["group_name"]

            if "In-session" in group_name:
                self.run_short_term_memory_tests(group["testcases"])
            elif "Cross-session" in group_name:
                self.run_long_term_memory_tests(group["testcases"])
            elif "Isolation" in group_name:
                self.run_isolation_tests(group["testcases"])
            elif "Cache" in group_name:
                self.run_cache_tests(group["testcases"])

        self.calculate_final_metrics()
        self.print_summary()
        self.save_results(output_file)


def main():
    parser = argparse.ArgumentParser(description="Run MANDATE #23 Tests")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8001",
        help="Shopping Copilot API base URL",
    )
    parser.add_argument(
        "--testcases",
        default="tests/cache-test/mandate_23_testcases.json",
        help="Path to test cases JSON file",
    )
    parser.add_argument(
        "--output",
        default="tests/cache-test/mandate_23_test_results.json",
        help="Path to output results JSON file",
    )

    args = parser.parse_args()

    runner = Mandate23TestRunner(args.api_url)
    runner.run_all_tests(args.testcases, args.output)


if __name__ == "__main__":
    main()
