from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


@dataclass
class BenchmarkCase:
    id: str
    category: str
    difficulty: str
    turn: int
    user_query: str
    expected_status: str = "ok"
    expected_tools: List[str] = field(default_factory=list)
    expected_contains: List[str] = field(default_factory=list)
    expected_not_contains: List[str] = field(default_factory=list)
    session_tag: Optional[str] = None
    user_id: str = "benchmark_user"
    notes: str = ""


@dataclass
class BenchmarkResult:
    case_id: str
    passed: bool
    expected_status: str
    actual_status: str
    checks: Dict[str, Any]
    reply_preview: str


class ShoppingBenchmarkEvaluator:
    """Load, score, and summarize shopping-copilot benchmark cases."""

    def load_cases_from_file(self, path: str | Path) -> List[BenchmarkCase]:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Benchmark file not found: {file_path}")

        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Benchmark file must contain a list of cases")

        cases: list[BenchmarkCase] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            cases.append(
                BenchmarkCase(
                    id=str(item.get("id", "")),
                    category=str(item.get("category", "")),
                    difficulty=str(item.get("difficulty", "easy")),
                    turn=int(item.get("turn", 1)),
                    user_query=str(item.get("user_query", "")),
                    expected_status=str(item.get("expected_status", "ok")),
                    expected_tools=list(item.get("expected_tools", [])),
                    expected_contains=list(item.get("expected_contains", [])),
                    expected_not_contains=list(item.get("expected_not_contains", [])),
                    session_tag=item.get("session_tag"),
                    user_id=str(item.get("user_id", "benchmark_user")),
                    notes=str(item.get("notes", "")),
                )
            )
        return cases

    def score_case(self, case: BenchmarkCase, response: Dict[str, Any] | None) -> BenchmarkResult:
        response = response or {}
        actual_status = str(response.get("status", "error"))
        reply = str(response.get("reply", ""))
        reply_l = reply.lower()

        steps = response.get("steps", []) or []
        step_actions = [self._step_action(step) for step in steps]
        step_text = " ".join(step_actions).lower()

        status_ok = actual_status == case.expected_status
        contains_ok = all(fragment.lower() in reply_l for fragment in case.expected_contains)
        not_contains_ok = all(fragment.lower() not in reply_l for fragment in case.expected_not_contains)
        tools_ok = all(tool.lower() in step_text for tool in case.expected_tools)
        token_ok = case.expected_status != "pending" or bool(response.get("token"))

        passed = status_ok and contains_ok and not_contains_ok and tools_ok and token_ok

        return BenchmarkResult(
            case_id=case.id,
            passed=passed,
            expected_status=case.expected_status,
            actual_status=actual_status,
            checks={
                "status_ok": status_ok,
                "contains_ok": contains_ok,
                "not_contains_ok": not_contains_ok,
                "tools_ok": tools_ok,
                "token_ok": token_ok,
                "expected_tools": case.expected_tools,
                "step_actions": step_actions,
            },
            reply_preview=reply[:240],
        )

    async def run_cases(
        self,
        cases: Iterable[BenchmarkCase],
        responder: Callable[[BenchmarkCase, str], Any],
    ) -> List[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for case in cases:
            response = await responder(case, case.user_query)
            results.append(self.score_case(case, response))
        return results

    def build_report(self, cases: List[BenchmarkCase], results: List[BenchmarkResult]) -> Dict[str, Any]:
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        by_category: Dict[str, Dict[str, int]] = {}
        by_difficulty: Dict[str, Dict[str, int]] = {}

        case_map = {case.id: case for case in cases}
        for result in results:
            case = case_map.get(result.case_id)
            if case is None:
                continue

            cat = case.category
            diff = case.difficulty

            by_category.setdefault(cat, {"total": 0, "passed": 0})
            by_difficulty.setdefault(diff, {"total": 0, "passed": 0})

            by_category[cat]["total"] += 1
            by_difficulty[diff]["total"] += 1
            if result.passed:
                by_category[cat]["passed"] += 1
                by_difficulty[diff]["passed"] += 1

        return {
            "total_cases": total,
            "passed_cases": passed,
            "accuracy": round(passed / total, 3) if total else 0.0,
            "by_category": {
                category: {
                    "total": data["total"],
                    "passed": data["passed"],
                    "accuracy": round(data["passed"] / data["total"], 3) if data["total"] else 0.0,
                }
                for category, data in by_category.items()
            },
            "by_difficulty": {
                difficulty: {
                    "total": data["total"],
                    "passed": data["passed"],
                    "accuracy": round(data["passed"] / data["total"], 3) if data["total"] else 0.0,
                }
                for difficulty, data in by_difficulty.items()
            },
            "results": [
                {
                    "case_id": result.case_id,
                    "passed": result.passed,
                    "expected_status": result.expected_status,
                    "actual_status": result.actual_status,
                    "checks": result.checks,
                    "reply_preview": result.reply_preview,
                }
                for result in results
            ],
        }

    def export_report(self, report: Dict[str, Any], destination: str | Path) -> Path:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        suffix = destination_path.suffix.lower()
        if suffix == ".json":
            destination_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        elif suffix in {".md", ".markdown"}:
            lines = [
                "# Shopping Copilot Benchmark Report",
                "",
                f"- Total cases: {report.get('total_cases', 0)}",
                f"- Passed cases: {report.get('passed_cases', report.get('passed', 0))}",
                f"- Accuracy: {report.get('accuracy', 0.0)}",
                "",
                "## By Category",
            ]
            for category, data in report.get("by_category", {}).items():
                lines.append(f"- {category}: {data['passed']}/{data['total']} ({data['accuracy']})")

            lines.append("")
            lines.append("## By Difficulty")
            for difficulty, data in report.get("by_difficulty", {}).items():
                lines.append(f"- {difficulty}: {data['passed']}/{data['total']} ({data['accuracy']})")

            lines.append("")
            lines.append("## Results")
            for item in report.get("results", []):
                lines.append(
                    f"- {item.get('case_id')}: passed={item.get('passed')} "
                    f"status={item.get('actual_status')} tools={item.get('checks', {}).get('expected_tools', [])}"
                )

            destination_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            raise ValueError(f"Unsupported report format: {suffix}")

        return destination_path

    @staticmethod
    def _step_action(step: Any) -> str:
        if isinstance(step, dict):
            return str(step.get("action", ""))
        return str(getattr(step, "action", step))
