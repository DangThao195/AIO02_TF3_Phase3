import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval


class RuntimeAcceptanceContractTests(unittest.TestCase):
    def test_dataset_is_mandated_size_and_multi_product(self):
        cases = run_eval.load_dataset(Path(__file__).with_name("dataset.jsonl"))
        self.assertEqual(len(cases), 200)
        self.assertGreaterEqual(len({case["product_id"] for case in cases}), 5)
        self.assertTrue(all(case["expected_behavior"] != "fallback" for case in cases))

    def test_usage_summary_reports_percentiles_tokens_and_cost(self):
        log = (
            "AI_USAGE role=candidate provider=bedrock model=amazon.nova-micro-v1:0 "
            "input_tokens=100 output_tokens=20 total_tokens=120 latency_ms=10\n"
            "AI_USAGE role=candidate provider=bedrock model=amazon.nova-micro-v1:0 "
            "input_tokens=200 output_tokens=30 total_tokens=230 latency_ms=30\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.log"
            path.write_text(log, encoding="utf-8")
            report = run_eval.summarize_usage(
                str(path),
                {"amazon.nova-micro-v1:0": {"input_per_million_usd": 0.035, "output_per_million_usd": 0.14}},
            )
        group = report["groups"][0]
        self.assertEqual(group["total_tokens"], 350)
        self.assertEqual(group["latency_ms"]["p50"], 20.0)
        self.assertEqual(group["latency_ms"]["p95"], 29.0)
        self.assertGreater(group["estimated_cost_usd"], 0)


if __name__ == "__main__":
    unittest.main()
