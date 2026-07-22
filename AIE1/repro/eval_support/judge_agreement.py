"""Evaluate LLM-as-a-judge agreement against human-labeled benchmark cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_REVIEWS_SRC = REPO_ROOT / "techx-corp-platform" / "src" / "product-reviews"
if str(PRODUCT_REVIEWS_SRC) not in sys.path:
    sys.path.insert(0, str(PRODUCT_REVIEWS_SRC))

from guardrails.evaluator import evaluate_summary_fidelity  # noqa: E402


REPRO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPRO_ROOT / "datasets" / "judge_benchmark.jsonl"
DEFAULT_ARTIFACT_DIR = REPRO_ROOT / "artifacts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default="")
    parser.add_argument("--judge-provider", default=os.getenv("JUDGE_PROVIDER", "bedrock"))
    parser.add_argument("--judge-model", default=os.getenv("JUDGE_MODEL", "amazon.nova-micro-v1:0"))
    parser.add_argument("--judge-region", default=os.getenv("JUDGE_REGION", os.getenv("AWS_REGION", "us-east-1")))
    parser.add_argument("--judge-base-url", default=os.getenv("JUDGE_BASE_URL", ""))
    parser.add_argument("--judge-api-key", default=os.getenv("JUDGE_API_KEY", ""))
    parser.add_argument("--judge-timeout-seconds", type=float, default=float(os.getenv("JUDGE_TIMEOUT_SECONDS", "60.0")))
    parser.add_argument("--min-agreement-rate", type=float, default=0.80)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def default_output_path() -> Path:
    DEFAULT_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_ARTIFACT_DIR / f"judge_human_agreement_{stamp}.json"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("human_label") not in {"pass", "fail"}:
            raise ValueError(f"Case line {line_number} must use human_label pass/fail.")
        if not row.get("candidate_answer"):
            raise ValueError(f"Case line {line_number} is missing candidate_answer.")
        cases.append(row)
    return cases


def judge_label(result: Dict[str, Any]) -> str:
    return "pass" if result.get("approved") else "fail"


def confusion_counts(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter()
    for item in results:
        human = item["human_label"]
        judge = item["judge_label"]
        if human == "pass" and judge == "pass":
            counts["true_pass"] += 1
        elif human == "pass" and judge == "fail":
            counts["false_reject"] += 1
        elif human == "fail" and judge == "fail":
            counts["true_fail"] += 1
        elif human == "fail" and judge == "pass":
            counts["false_accept"] += 1
    return dict(counts)


def evaluate_case(case: Dict[str, Any], args: argparse.Namespace) -> Tuple[Dict[str, Any], float]:
    started = time.perf_counter()
    result = evaluate_summary_fidelity(
        product_id=str(case["product_id"]),
        raw_reviews=list(case.get("raw_reviews", [])),
        summary_text=str(case["candidate_answer"]),
        question=str(case.get("question", "")),
        product_info=case.get("product_info", ""),
        judge_provider=args.judge_provider,
        judge_model=args.judge_model,
        judge_region=args.judge_region,
        judge_base_url=args.judge_base_url,
        judge_api_key=args.judge_api_key,
        timeout_seconds=args.judge_timeout_seconds,
    )
    return result, round(time.perf_counter() - started, 4)


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset).resolve()
    cases = load_jsonl(dataset_path)
    results: List[Dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        judge_result, latency = evaluate_case(case, args)
        label = judge_label(judge_result)
        agreed = label == case["human_label"]
        results.append(
            {
                "id": case["id"],
                "product_id": case["product_id"],
                "question": case.get("question", ""),
                "human_label": case["human_label"],
                "judge_label": label,
                "agreement": agreed,
                "failure_type": case.get("failure_type", ""),
                "latency_seconds": latency,
                "judge_result": judge_result,
            }
        )
        print(f"case_progress={index}/{len(cases)} id={case['id']} human={case['human_label']} judge={label} agreement={agreed}", flush=True)

    agreed_count = sum(bool(item["agreement"]) for item in results)
    agreement_rate = round(agreed_count / len(results), 4) if results else 0.0
    summary = {
        "total_cases": len(results),
        "human_labeled_cases": len(results),
        "agreed_cases": agreed_count,
        "disagreed_cases": len(results) - agreed_count,
        "agreement_rate": agreement_rate,
        "confusion": confusion_counts(results),
        "quality_gate_passed": agreement_rate >= args.min_agreement_rate,
        "quality_gate_failures": [] if agreement_rate >= args.min_agreement_rate else ["judge_human_agreement_below_threshold"],
    }
    report = {
        "run_id": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "judge_provider": args.judge_provider,
        "judge_model": args.judge_model,
        "judge_region": args.judge_region,
        "thresholds": {"min_agreement_rate": args.min_agreement_rate},
        "summary": summary,
        "results": results,
    }
    output_path = Path(args.out).resolve() if args.out else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"artifact={output_path}")
    if args.strict and not summary["quality_gate_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
