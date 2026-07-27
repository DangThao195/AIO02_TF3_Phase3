#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation import TrustSafetyEvaluator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trust-and-safety evaluation cases from JSON and export reports")
    parser.add_argument("--input", required=True, help="Path to JSON file containing evaluation cases")
    parser.add_argument("--output-json", help="Path to save JSON report")
    parser.add_argument("--output-md", help="Path to save Markdown report")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    evaluator = TrustSafetyEvaluator()
    report = evaluator.run_suite_from_file(input_path)

    if args.output_json:
        evaluator.export_report(report, args.output_json)
    if args.output_md:
        evaluator.export_report(report, args.output_md)

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
