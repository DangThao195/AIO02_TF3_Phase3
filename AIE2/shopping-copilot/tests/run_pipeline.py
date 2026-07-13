"""
run_pipeline.py — Shopping Copilot Pipeline Test Runner

Chạy từng test query qua toàn bộ pipeline (guardrails -> ReAct loop -> tools),
ghi chi tiết từng bước xử lý và lưu kết quả ra file JSON.

Cách chạy:
    cd shopping-copilot
    python tests/run_pipeline.py

    # hoặc từ thư mục tests:
    cd shopping-copilot/tests
    python run_pipeline.py

Output: shopping-copilot/tests/test_results.json
"""

import sys
import os
import json
import time
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Path setup ──────────────────────────────────────────────
_THIS_DIR = Path(__file__).parent.resolve()
_SHOPPING_COPILOT = _THIS_DIR.parent.resolve()
_PROJECT_ROOT = _SHOPPING_COPILOT.parent.resolve()

if str(_SHOPPING_COPILOT) not in sys.path:
    sys.path.insert(0, str(_SHOPPING_COPILOT))

# ── Config ──────────────────────────────────────────────────
TEST_QUERIES_PATH = _THIS_DIR / "test_queries.json"
RESULTS_PATH = _THIS_DIR / "test_results.json"
DEFAULT_DELAY_SECONDS = 8.0
RATE_LIMIT_RETRY_DELAY = 20.0
MAX_RETRIES_PER_TEST = 2
TEST_RUNNER_LOG = _THIS_DIR / "test_runner.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(str(TEST_RUNNER_LOG), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("run_pipeline")

# ── Load env ────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(str(_SHOPPING_COPILOT / ".env"))


# ══════════════════════════════════════════════════════════════
# TestPipelineRunner
# ══════════════════════════════════════════════════════════════

class TestPipelineRunner:
    """
    Chạy toàn bộ test queries qua CopilotAgent pipeline async.
    """

    def __init__(self, delay: float = DEFAULT_DELAY_SECONDS):
        self.delay = delay
        self._agent: Optional[Any] = None
        self._session_registry: Dict[str, str] = {}
        self._results: List[Dict[str, Any]] = []
        self._start_ts: float = 0.0
        self._consecutive_rate_limits = 0

    # ── Agent lazy init ──

    def _get_agent(self):
        if self._agent is None:
            logger.info("[SETUP] Initializing CopilotAgent...")
            from agent.copilot_agent import CopilotAgent
            self._agent = CopilotAgent()
            logger.info("[SETUP] CopilotAgent ready")
        return self._agent

    # ── Load test data ──

    def load_queries(self) -> List[Dict[str, Any]]:
        if not TEST_QUERIES_PATH.exists():
            logger.error(f"Test queries file not found: {TEST_QUERIES_PATH}")
            sys.exit(1)
        with open(TEST_QUERIES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"[DATA] Loaded {len(data)} test cases from {TEST_QUERIES_PATH}")
        return data

    # ── Session management ──

    def _resolve_session(self, test_case: Dict[str, Any]) -> str:
        tag = test_case.get("session_tag")
        if tag:
            if tag not in self._session_registry:
                self._session_registry[tag] = str(uuid.uuid4())
            return self._session_registry[tag]
        return str(uuid.uuid4())

    # ── Rate limit backoff ──

    async def _handle_rate_limit(self, test_id: str, attempt: int):
        self._consecutive_rate_limits += 1
        backoff = RATE_LIMIT_RETRY_DELAY * (self._consecutive_rate_limits ** 0.5)
        wait = max(RATE_LIMIT_RETRY_DELAY, backoff)
        logger.warning(
            f"[BACKOFF] [{test_id}] 429 rate limit, "
            f"waiting {wait:.0f}s (consecutive={self._consecutive_rate_limits}, "
            f"attempt={attempt + 1}/{MAX_RETRIES_PER_TEST})"
        )
        await asyncio.sleep(wait)

    def _is_rate_limited(self, result: Dict[str, Any]) -> bool:
        err = result.get("error") or ""
        if "RateLimitError" in err or "429" in err:
            return True
        for s in result.get("steps", []):
            detail = s.get("detail", "")
            if "RateLimitError" in detail or "429" in detail:
                return True
        return False

    # ── Single test runner (async) ──

    async def _run_single(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        test_id = test_case["id"]
        user_query = test_case["user_query"]
        user_id = test_case.get("user_id", "test_anonymous")
        session_id = self._resolve_session(test_case)

        logger.info(f"[TEST] [{test_id}] ---> \"{user_query[:80]}\"")

        result: Dict[str, Any] = {
            "test_id": test_id,
            "description": test_case.get("description", ""),
            "category": test_case.get("category", ""),
            "user_query": user_query,
            "user_id": user_id,
            "session_id": session_id,
            "status": "error",
            "error": None,
            "steps": [],
            "final_reply": "",
            "final_reply_preview": "",
            "has_token": False,
            "duration_ms": 0,
            "expected_status": test_case.get("expected_status", "ok"),
        }

        start = time.time()
        agent = self._get_agent()

        try:
            response = await agent.chat(
                session_id=session_id,
                user_id=user_id,
                user_message=user_query,
            )

            result["status"] = response.get("status", "error")
            final_reply = response.get("reply", "")
            result["final_reply"] = final_reply
            result["final_reply_preview"] = final_reply[:200]
            result["has_token"] = bool(response.get("token"))
            result["steps"] = response.get("steps", [])

        except ImportError as e:
            result["error"] = f"ImportError: {e}"
            logger.error(f"[TEST] [{test_id}] IMPORT ERROR: {e}")
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)[:300]}"
            result["error"] = err_msg
            if agent:
                result["steps"] = getattr(agent, "_steps", [])
            logger.error(f"[TEST] [{test_id}] ERROR: {err_msg[:120]}")

        result["duration_ms"] = int((time.time() - start) * 1000)
        logger.info(
            f"[TEST] [{test_id}] <--- {result['status']} | "
            f"{len(result['steps'])} steps | {result['duration_ms']}ms"
        )
        return result

    # ── Full test run (async) ──

    async def run(self, test_ids: Optional[List[str]] = None):
        self._start_ts = time.time()
        all_queries = self.load_queries()

        if test_ids:
            id_set = set(test_ids)
            queries = [q for q in all_queries if q["id"] in id_set]
            skipped = [q["id"] for q in all_queries if q["id"] not in id_set]
            if skipped:
                logger.info(f"[RUN] Skipping {len(skipped)} tests: {skipped}")
        else:
            queries = all_queries

        logger.info(f"[RUN] Starting pipeline test: {len(queries)} cases")
        logger.info(f"[RUN] Delay between tests: {self.delay}s")
        logger.info(f"[RUN] GROQ model: {os.environ.get('GROQ_MODEL', 'default')}")
        logger.info(f"[RUN] GROQ key set: {bool(os.environ.get('GROQ_API_KEY'))}")
        logger.info("=" * 80)

        self._results = []
        total_rate_limits = 0
        self._consecutive_rate_limits = 0

        for i, test_case in enumerate(queries, 1):
            test_id = test_case["id"]
            succeeded = False

            for attempt in range(1 + MAX_RETRIES_PER_TEST):
                result = await self._run_single(test_case)

                if self._is_rate_limited(result):
                    total_rate_limits += 1
                    if attempt < MAX_RETRIES_PER_TEST:
                        await self._handle_rate_limit(test_id, attempt)
                        continue
                    else:
                        self._results.append(result)
                        succeeded = True
                        self._consecutive_rate_limits = max(0, self._consecutive_rate_limits - 1)
                else:
                    self._results.append(result)
                    succeeded = True
                    self._consecutive_rate_limits = max(0, self._consecutive_rate_limits - 1)
                    break

            if not succeeded:
                logger.error(f"[TEST] [{test_id}] SKIPPED after {MAX_RETRIES_PER_TEST + 1} attempts")

            # Delay between tests (except after last)
            if i < len(queries):
                logger.info(f"[WAIT] Sleeping {self.delay}s before next test...")
                await asyncio.sleep(self.delay)

        self._save_results(queries)

    def _save_results(self, queries: List[Dict]):
        total_duration = int((time.time() - self._start_ts) * 1000)
        total_tests = len(self._results)
        status_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        for r in self._results:
            s = r["status"]
            status_counts[s] = status_counts.get(s, 0) + 1
            cat = r.get("category", "unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        output = {
            "test_run": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_tests": total_tests,
                "total_duration_ms": total_duration,
                "delay_between_tests_s": self.delay,
                "config": {
                    "groq_model": os.environ.get("GROQ_MODEL", "not_set"),
                    "groq_api_key_set": bool(os.environ.get("GROQ_API_KEY")),
                },
                "summary": {
                    "by_status": status_counts,
                    "by_category": category_counts,
                    "tests": [r["test_id"] for r in self._results],
                },
            },
            "results": self._results,
        }

        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info("=" * 80)
        logger.info(f"[DONE] Results saved to {RESULTS_PATH}")
        logger.info(f"[DONE] {total_tests} tests | {total_duration // 1000}s total")
        logger.info(f"[DONE] Status: {status_counts}")
        logger.info("=" * 80)


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Shopping Copilot — Pipeline Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tests/run_pipeline.py                                    # run all
  python tests/run_pipeline.py --ids search_vietnamese            # run one
  python tests/run_pipeline.py --delay 12.0                       # custom delay
  python tests/run_pipeline.py --ids search_vietnamese reviews    # run multiple
  python tests/run_pipeline.py --list                             # list IDs
  python tests/run_pipeline.py --dry-run                          # preview
        """,
    )
    parser.add_argument(
        "--ids", nargs="+", default=None,
        help="Chi chay cac test co ID cu the"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_SECONDS,
        help=f"Delay giua cac test (s, default={DEFAULT_DELAY_SECONDS})"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Liet ke tat ca test IDs va thoat"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Chi load va hien thi test cases, khong chay"
    )

    args = parser.parse_args()

    def _print_safe(text: str):
        try:
            print(text)
        except UnicodeEncodeError:
            safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            )
            print(safe)

    if not TEST_QUERIES_PATH.exists():
        logger.error(f"File not found: {TEST_QUERIES_PATH}")
        sys.exit(1)

    with open(TEST_QUERIES_PATH, encoding="utf-8") as f:
        all_queries = json.load(f)

    if args.list:
        _print_safe(f"\n{'ID':30s} {'Category':20s} {'Expected Status':15s} Query Preview")
        _print_safe("-" * 100)
        for q in all_queries:
            preview = q["user_query"][:50].replace("\n", "\\n")
            _print_safe(
                f"{q['id']:30s} {q.get('category', ''):20s} "
                f"{q.get('expected_status', 'ok'):15s} {preview}"
            )
        _print_safe(f"\nTotal: {len(all_queries)} test cases")
        return

    if args.dry_run:
        _print_safe(f"\n=== DRY RUN: {len(all_queries)} test cases ===\n")
        for q in all_queries:
            tag = f" [session_tag={q['session_tag']}]" if q.get("session_tag") else ""
            _print_safe(f"  [{q['id']:35s}] {q['user_query'][:80]}{tag}")
        _print_safe(f"\nDelay: {args.delay}s | Retries: {MAX_RETRIES_PER_TEST}")
        return

    # ── Run async main ──
    runner = TestPipelineRunner(delay=args.delay)
    asyncio.run(runner.run(test_ids=args.ids))


if __name__ == "__main__":
    main()
