#!/usr/bin/env python3
"""Summarize structured runtime AI usage logs and estimate Bedrock cost."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


USAGE_RE = re.compile(
    r"AI_USAGE role=(?P<role>\S+) provider=(?P<provider>\S+) model=(?P<model>\S+) "
    r"input_tokens=(?P<input>\d+) output_tokens=(?P<output>\d+) "
    r"total_tokens=(?P<total>\d+) latency_ms=(?P<latency>[0-9.]+)"
)

# Standard on-demand text pricing in USD per 1M tokens, checked 2026-07-17.
# Source: https://aws.amazon.com/bedrock/pricing/
DEFAULT_PRICING = {
    "amazon.nova-lite-v1:0": {"input_per_million_usd": 0.06, "output_per_million_usd": 0.24},
    "amazon.nova-micro-v1:0": {"input_per_million_usd": 0.035, "output_per_million_usd": 0.14},
}


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def read_logs(path: str, container: str) -> str:
    if container:
        completed = subprocess.run(
            ["docker", "logs", container],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return completed.stdout + "\n" + completed.stderr
    return Path(path).read_text(encoding="utf-8", errors="replace")


def summarize(log_text: str, pricing: dict) -> dict:
    groups = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "total": 0, "latencies": []})
    for match in USAGE_RE.finditer(log_text):
        key = (match["role"], match["provider"], match["model"])
        group = groups[key]
        group["calls"] += 1
        group["input"] += int(match["input"])
        group["output"] += int(match["output"])
        group["total"] += int(match["total"])
        group["latencies"].append(float(match["latency"]))

    entries = []
    aggregate_cost = 0.0
    for (role, provider, model), group in sorted(groups.items()):
        rates = pricing.get(model)
        cost = None
        if rates:
            cost = (
                group["input"] * rates["input_per_million_usd"]
                + group["output"] * rates["output_per_million_usd"]
            ) / 1_000_000
            aggregate_cost += cost
        latencies = group.pop("latencies")
        entries.append(
            {
                "role": role,
                "provider": provider,
                "model": model,
                "calls": group["calls"],
                "input_tokens": group["input"],
                "output_tokens": group["output"],
                "total_tokens": group["total"],
                "latency_ms": {
                    "mean": round(statistics.fmean(latencies), 2),
                    "p50": round(percentile(latencies, 0.50), 2),
                    "p95": round(percentile(latencies, 0.95), 2),
                    "max": round(max(latencies), 2),
                },
                "estimated_cost_usd": round(cost, 8) if cost is not None else None,
            }
        )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pricing": {
            "currency": "USD",
            "unit": "per_1m_tokens",
            "service_tier": "standard_on_demand",
            "region": "us-east-1",
            "checked_date": "2026-07-17",
            "source": "https://aws.amazon.com/bedrock/pricing/",
            "models": pricing,
        },
        "groups": entries,
        "aggregate": {
            "calls": sum(item["calls"] for item in entries),
            "input_tokens": sum(item["input_tokens"] for item in entries),
            "output_tokens": sum(item["output_tokens"] for item in entries),
            "total_tokens": sum(item["total_tokens"] for item in entries),
            "estimated_cost_usd": round(aggregate_cost, 8),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--log", help="Runtime log file")
    source.add_argument("--docker-container", help="Read logs directly from this container")
    parser.add_argument("--out", required=True, help="Output JSON artifact")
    parser.add_argument("--pricing-json", help="Optional model pricing override")
    args = parser.parse_args()

    pricing = DEFAULT_PRICING
    if args.pricing_json:
        pricing = json.loads(Path(args.pricing_json).read_text(encoding="utf-8"))
    result = summarize(read_logs(args.log, args.docker_container), pricing)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["aggregate"], indent=2))
    if not result["groups"]:
        raise SystemExit("No AI_USAGE records found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
