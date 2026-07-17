"""
Run the shopping-copilot benchmark end-to-end.

Usage:
    python tests/run_shopping_benchmark.py
    python tests/run_shopping_benchmark.py --ids easy_search_vn hard_multiturn_seed
    python tests/run_shopping_benchmark.py --delay 0.5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation import ShoppingBenchmarkEvaluator


DEFAULT_CASES = Path(__file__).with_name("test_evaluation") / "shopping_benchmark_cases.json"
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("test_evaluation")


async def _run_benchmark(cases_path: Path, output_dir: Path, ids: list[str] | None, delay: float) -> dict[str, Any]:
    evaluator = ShoppingBenchmarkEvaluator()
    cases = evaluator.load_cases_from_file(cases_path)

    if ids:
        wanted = set(ids)
        cases = [case for case in cases if case.id in wanted]

    try:
        from src.agent import CopilotAgent
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError(f"Unable to import CopilotAgent: {exc}") from exc

    agent = CopilotAgent()
    session_registry: dict[str, str] = {}

    async def responder(case, message):
        session_key = case.session_tag or case.id
        session_id = session_registry.setdefault(session_key, str(uuid.uuid4()))
        return await agent.chat(
            session_id=session_id,
            user_id=case.user_id,
            user_message=message,
        )

    results = []
    for case in cases:
        response = await responder(case, case.user_query)
        results.append(evaluator.score_case(case, response))
        if delay > 0:
            await asyncio.sleep(delay)

    report = evaluator.build_report(cases, results)
    report["passed_cases"] = sum(1 for result in results if result.passed)
    report["failed_cases"] = report["total_cases"] - report["passed_cases"]

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "shopping_benchmark_report.json"
    md_path = output_dir / "shopping_benchmark_report.md"
    evaluator.export_report(report, json_path)
    evaluator.export_report(report, md_path)

    return {
        "report": report,
        "json_path": json_path,
        "md_path": md_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Shopping Copilot benchmark runner")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="Path to benchmark cases JSON")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for reports")
    parser.add_argument("--ids", nargs="+", default=None, help="Run only specific case IDs")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between cases in seconds")
    parser.add_argument("--list", action="store_true", help="List cases and exit")
    args = parser.parse_args()

    evaluator = ShoppingBenchmarkEvaluator()
    cases = evaluator.load_cases_from_file(args.cases)

    if args.list:
        print(f"{'ID':35s} {'Difficulty':10s} {'Category':12s} Query")
        print("-" * 100)
        for case in cases:
            print(f"{case.id:35s} {case.difficulty:10s} {case.category:12s} {case.user_query[:70]}")
        return

    if args.ids:
        wanted = set(args.ids)
        cases = [case for case in cases if case.id in wanted]
        if not cases:
            raise SystemExit("No matching case IDs found.")

    result = asyncio.run(_run_benchmark(args.cases, args.output_dir, args.ids, args.delay))
    report = result["report"]

    print("=" * 80)
    print(f"Total cases: {report['total_cases']}")
    print(f"Passed cases: {report['passed_cases']}")
    print(f"Accuracy: {report['accuracy']}")
    print(f"JSON report: {result['json_path']}")
    print(f"Markdown report: {result['md_path']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
