#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Hybrid fidelity evaluation for AI review summaries.

Design goals:
1. Use real reviews from Postgres as the ground truth.
2. Call the live ProductReviewService over gRPC to obtain the candidate summary.
3. Combine deterministic rule-based checks with an LLM judge.
4. Split fidelity quality from output format quality.
5. Persist an artifact that is auditable case-by-case and in aggregate.
"""

import argparse
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None

import grpc
import psycopg2
from openai import OpenAI

PROTO_DIR = Path(__file__).resolve().parents[1] / "techx-corp-platform" / "src" / "product-reviews"
sys.path.append(str(PROTO_DIR))

try:
    import demo_pb2
    import demo_pb2_grpc
except ImportError as exc:
    raise SystemExit(
        "Unable to import demo_pb2/demo_pb2_grpc. Run protobuf generation first."
    ) from exc

DB_CONN = os.environ.get(
    "DB_CONNECTION_STRING",
    "Host=localhost;Username=otelu;Password=otelp;Database=otel;Port=5432",
)
PRODUCT_REVIEWS_ADDR = os.environ.get("PRODUCT_REVIEWS_ADDR", "localhost:8085")
JUDGE_PROVIDER = os.environ.get("JUDGE_PROVIDER", "openai").lower()
JUDGE_REGION = os.environ.get("JUDGE_REGION", os.environ.get("AWS_REGION", "us-east-1"))
JUDGE_API_KEY = os.environ.get("JUDGE_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "https://api.openai.com/v1")
DEFAULT_JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-4o-mini")

MIN_CLAIM_COUNT = 2
MIN_CLAIM_PRECISION = 0.80
MIN_ASPECT_COVERAGE = 0.60
MIN_OVERALL_SCORE = 4
MAX_SUMMARY_SENTENCES = 2
MAX_SUMMARY_WORDS = 80
RATING_MISMATCH_TOLERANCE = 0.05

NEGATIVE_SENTIMENT_PATTERNS = [
    r"mostly negative",
    r"many complaints",
    r"customers were disappointed",
    r"widely criticized",
    r"poor value",
    r"not recommended",
]
POSITIVE_SENTIMENT_PATTERNS = [
    r"overwhelmingly positive",
    r"highly recommended",
    r"must-have",
    r"excellent value",
    r"top-notch",
]
AGE_PATTERNS = [
    r"ages?\s+\d+",
    r"\d+\+\s*years?",
    r"years? old",
    r"recommended for ages?",
]
AVERAGE_RATING_PATTERNS = [
    r"average rating of\s*(\d+(?:\.\d+)?)",
    r"average of\s*(\d+(?:\.\d+)?)\s*out of\s*5",
    r"(\d+(?:\.\d+)?)\s*out of\s*5\s*stars",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate fidelity of AI review summaries.")
    parser.add_argument(
        "product_ids",
        nargs="*",
        help="One or more product ids to evaluate. Defaults to L9ECAV7KIM when omitted.",
    )
    parser.add_argument(
        "--product-file",
        default="",
        help="Optional file containing one product id per line.",
    )
    parser.add_argument(
        "--all-products",
        action="store_true",
        help="Evaluate every distinct product_id that has at least one review in the database.",
    )
    parser.add_argument(
        "--judge-provider",
        default=JUDGE_PROVIDER,
        choices=["openai", "bedrock"],
        help="Judge provider to use.",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help="Judge model id.",
    )
    parser.add_argument(
        "--judge-base-url",
        default=JUDGE_BASE_URL,
        help="OpenAI-compatible base URL for the judge model.",
    )
    parser.add_argument(
        "--judge-region",
        default=JUDGE_REGION,
        help="AWS region for Bedrock judge calls.",
    )
    parser.add_argument(
        "--grpc-timeout-seconds",
        type=int,
        default=20,
        help="Timeout for the ProductReviewService gRPC call.",
    )
    parser.add_argument(
        "--judge-timeout-seconds",
        type=int,
        default=45,
        help="Timeout for the LLM judge call.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional path for the JSON artifact. Defaults to repro/artifacts/fidelity_eval_<timestamp>.json",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any case is invalid or fails the overall pass gate.",
    )
    return parser.parse_args()


def parse_db_conn_string(conn_str: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    normalized = (conn_str or "").strip()
    if not normalized:
        return result

    if ";" in normalized:
        parts = normalized.split(";")
    else:
        parts = normalized.split()

    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip().lower()] = value.strip()
    return result


def open_db_connection():
    conn_dict = parse_db_conn_string(DB_CONN)
    return psycopg2.connect(
        host=conn_dict.get("host", "localhost"),
        user=conn_dict.get("username", conn_dict.get("user", "otelu")),
        password=conn_dict.get("password", "otelp"),
        database=conn_dict.get("database", conn_dict.get("dbname", "otel")),
        port=conn_dict.get("port", "5432"),
    )


def get_all_product_ids_from_db() -> List[str]:
    conn = open_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT product_id
                FROM reviews.productreviews
                WHERE product_id IS NOT NULL AND product_id <> ''
                ORDER BY product_id
                """
            )
            records = cur.fetchall()
    finally:
        conn.close()
    return [row[0] for row in records]


def parse_product_ids(args: argparse.Namespace) -> List[str]:
    product_ids: List[str] = []

    if args.all_products:
        product_ids.extend(get_all_product_ids_from_db())

    product_ids.extend(args.product_ids)

    if args.product_file:
        file_path = Path(args.product_file)
        for line in file_path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value:
                product_ids.append(value)

    if not product_ids:
        product_ids = ["L9ECAV7KIM"]

    return list(dict.fromkeys(product_ids))


def get_raw_reviews_from_db(product_id: str) -> List[Dict[str, Any]]:
    conn = open_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, description, score FROM reviews.productreviews WHERE product_id = %s",
                (product_id,),
            )
            records = cur.fetchall()
    finally:
        conn.close()

    return [
        {"username": row[0], "description": row[1], "score": float(row[2])}
        for row in records
    ]


def get_ai_summary_via_grpc(product_id: str, timeout_seconds: int) -> str:
    channel = grpc.insecure_channel(PRODUCT_REVIEWS_ADDR)
    stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
    request = demo_pb2.AskProductAIAssistantRequest(
        product_id=product_id,
        question="Can you summarize the product reviews?",
    )
    response = stub.AskProductAIAssistant(request, timeout=timeout_seconds)
    return response.response.strip()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def count_sentences(text: str) -> int:
    pieces = [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalize_whitespace(text)) if part.strip()]
    return len(pieces)


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def extract_average_rating_mentions(summary: str) -> List[float]:
    values: List[float] = []
    for pattern in AVERAGE_RATING_PATTERNS:
        for match in re.finditer(pattern, summary, re.IGNORECASE):
            try:
                values.append(float(match.group(1)))
            except (TypeError, ValueError):
                continue
    return values


def clamp01(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_fact_sheet(product_id: str, raw_reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = [review["score"] for review in raw_reviews]
    average_score = round(statistics.mean(scores), 2) if scores else None
    sorted_reviews = sorted(raw_reviews, key=lambda item: item["score"], reverse=True)
    top_positive = sorted_reviews[:3]
    top_negative = sorted(raw_reviews, key=lambda item: item["score"])[:3]

    has_age_signal = any(
        re.search(r"\bage\b|\byears? old\b|\bkids?\b|\bchildren\b", review["description"], re.IGNORECASE)
        for review in raw_reviews
    )

    rating_distribution: Dict[str, int] = {}
    for score in scores:
        bucket = f"{int(math.floor(score))}"
        rating_distribution[bucket] = rating_distribution.get(bucket, 0) + 1

    return {
        "product_id": product_id,
        "review_count": len(raw_reviews),
        "average_score": average_score,
        "rating_distribution": rating_distribution,
        "top_positive_reviews": [
            {
                "username": review["username"],
                "score": review["score"],
                "description": review["description"],
            }
            for review in top_positive
        ],
        "top_negative_reviews": [
            {
                "username": review["username"],
                "score": review["score"],
                "description": review["description"],
            }
            for review in top_negative
        ],
        "constraints": {
            "has_explicit_age_signal": has_age_signal,
        },
    }


def run_rule_checks(raw_reviews: List[Dict[str, Any]], ai_summary: str, fact_sheet: Dict[str, Any]) -> Dict[str, Any]:
    normalized_summary = normalize_whitespace(ai_summary)
    sentence_count = count_sentences(normalized_summary)
    word_count = count_words(normalized_summary)
    summary_lower = normalized_summary.lower()
    average_score = fact_sheet.get("average_score")

    hard_fail_reasons: List[str] = []
    warnings: List[str] = []
    fidelity_findings: List[str] = []
    format_findings: List[str] = []

    if not normalized_summary:
        hard_fail_reasons.append("empty_summary")

    format_passed = True
    if sentence_count > MAX_SUMMARY_SENTENCES:
        warnings.append("summary_exceeds_prompt_length")
        format_findings.append("too_many_sentences")
        format_passed = False
    if word_count > MAX_SUMMARY_WORDS:
        warnings.append("summary_exceeds_word_budget")
        format_findings.append("too_many_words")
        format_passed = False

    unsupported_age_claim = False
    if not fact_sheet["constraints"]["has_explicit_age_signal"]:
        unsupported_age_claim = any(re.search(pattern, summary_lower) for pattern in AGE_PATTERNS)
        if unsupported_age_claim:
            fidelity_findings.append("unsupported_age_claim")

    average_rating_mentions = extract_average_rating_mentions(normalized_summary)
    average_rating_mismatch = False
    if average_score is not None and average_rating_mentions:
        average_rating_mismatch = any(abs(value - average_score) > RATING_MISMATCH_TOLERANCE for value in average_rating_mentions)
        if average_rating_mismatch:
            fidelity_findings.append("average_rating_mismatch")

    negative_sentiment_conflict = False
    positive_sentiment_conflict = False
    if average_score is not None:
        if average_score >= 4.0 and any(re.search(pattern, summary_lower) for pattern in NEGATIVE_SENTIMENT_PATTERNS):
            negative_sentiment_conflict = True
            fidelity_findings.append("negative_sentiment_conflict")
        if average_score <= 2.5 and any(re.search(pattern, summary_lower) for pattern in POSITIVE_SENTIMENT_PATTERNS):
            positive_sentiment_conflict = True
            fidelity_findings.append("positive_sentiment_conflict")

    product_id_echo = fact_sheet["product_id"].lower() in summary_lower
    if product_id_echo:
        warnings.append("product_id_echoed_in_summary")

    return {
        "summary_length_chars": len(normalized_summary),
        "sentence_count": sentence_count,
        "word_count": word_count,
        "warnings": warnings,
        "hard_fail_reasons": hard_fail_reasons,
        "hard_fail": bool(hard_fail_reasons),
        "format_passed": format_passed,
        "format_findings": format_findings,
        "fidelity_findings": fidelity_findings,
        "unsupported_age_claim": unsupported_age_claim,
        "average_rating_mentions": average_rating_mentions,
        "average_rating_mismatch": average_rating_mismatch,
        "negative_sentiment_conflict": negative_sentiment_conflict,
        "positive_sentiment_conflict": positive_sentiment_conflict,
        "product_id_echo": product_id_echo,
    }


def build_judge_prompt(product_id: str, raw_reviews: List[Dict[str, Any]], fact_sheet: Dict[str, Any], ai_summary: str) -> str:
    review_lines = [
        f"- reviewer={review['username']} | score={review['score']} | review={review['description']}"
        for review in raw_reviews
    ]
    review_block = "\n".join(review_lines)
    fact_sheet_block = json.dumps(fact_sheet, ensure_ascii=False, indent=2)

    return f"""
You are a strict factual auditor for AI-generated product-review summaries.

Task:
Evaluate whether the candidate summary is faithful to the original reviews.
Use the raw reviews and fact sheet as the only ground truth.
Do not reward style. Focus on factual support, contradiction, omission, and groundedness.

PRODUCT_ID:
{product_id}

RAW_REVIEWS:
{review_block}

FACT_SHEET:
{fact_sheet_block}

CANDIDATE_SUMMARY:
{ai_summary}

Scoring rubric:
- overall_score = 5 only if the summary is strongly grounded, accurate, and covers the main points.
- overall_score = 4 if it is mostly grounded with only small omissions.
- overall_score <= 3 if it misses key points, exaggerates, or weakens factual support.
- A contradicted claim must be labeled contradicted, not supported.
- An unsupported claim must be labeled unsupported, not supported.
- If the summary has fewer than 2 meaningful claims, set claim_count accordingly and lower coverage.
- aspect_coverage should reflect how well the summary covers the major positive and negative aspects in the reviews.
- sentiment_alignment = 1 only if the overall tone matches the review set.
- Do not use sentence count as a pass/fail criterion here. Format is handled separately.

Return JSON only with this schema:
{{
  "overall_score": <integer 1-5>,
  "claims": [
    {{
      "text": "<claim text>",
      "label": "supported|unsupported|contradicted",
      "evidence": ["<short supporting quote or reason>"]
    }}
  ],
  "summary_metrics": {{
    "supported_claims": <integer>,
    "unsupported_claims": <integer>,
    "contradicted_claims": <integer>,
    "claim_count": <integer>,
    "claim_precision": <float 0-1>,
    "aspect_coverage": <float 0-1>,
    "sentiment_alignment": <0 or 1>
  }},
  "reason": "<brief justification>"
}}
""".strip()


def parse_judge_payload(raw_content: str) -> Dict[str, Any]:
    content = (raw_content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def judge_fidelity(
    product_id: str,
    raw_reviews: List[Dict[str, Any]],
    fact_sheet: Dict[str, Any],
    ai_summary: str,
    judge_model: str,
    judge_base_url: str,
    judge_timeout_seconds: int,
    judge_provider: str,
    judge_region: str,
) -> Dict[str, Any]:
    prompt = build_judge_prompt(product_id, raw_reviews, fact_sheet, ai_summary)

    if judge_provider == "bedrock":
        if boto3 is None:
            raise RuntimeError("boto3 is required for judge_provider=bedrock. Install boto3 before running the evaluator.")
        client = boto3.client("bedrock-runtime", region_name=judge_region)
        response = client.converse(
            modelId=judge_model,
            system=[{"text": "You are a strict factual auditor for AI-generated product-review summaries. Return JSON only."}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.0, "maxTokens": 1200},
        )
        response_text = response["output"]["message"]["content"][0]["text"]
    else:
        if not JUDGE_API_KEY:
            raise RuntimeError("JUDGE_API_KEY or OPENAI_API_KEY is required for OpenAI-compatible judge evaluation.")
        client = OpenAI(api_key=JUDGE_API_KEY, base_url=judge_base_url)
        response = client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=judge_timeout_seconds,
        )
        response_text = response.choices[0].message.content

    payload = parse_judge_payload(response_text)
    metrics = payload.get("summary_metrics", {})
    claims = payload.get("claims", [])

    claim_count = safe_int(metrics.get("claim_count", len(claims)))
    supported_claims = safe_int(metrics.get("supported_claims", 0))
    unsupported_claims = safe_int(metrics.get("unsupported_claims", 0))
    contradicted_claims = safe_int(metrics.get("contradicted_claims", 0))

    if claim_count <= 0:
        claim_count = len(claims)
    if claim_count <= 0:
        claim_count = supported_claims + unsupported_claims + contradicted_claims

    claim_precision = safe_float(metrics.get("claim_precision", 0.0))
    if claim_count > 0 and claim_precision == 0.0 and supported_claims > 0:
        claim_precision = supported_claims / claim_count

    return {
        "overall_score": safe_int(payload.get("overall_score", 0)),
        "claims": claims,
        "supported_claims": supported_claims,
        "unsupported_claims": unsupported_claims,
        "contradicted_claims": contradicted_claims,
        "claim_count": claim_count,
        "claim_precision": round(clamp01(claim_precision), 4),
        "aspect_coverage": round(clamp01(metrics.get("aspect_coverage", 0.0)), 4),
        "sentiment_alignment": 1 if safe_int(metrics.get("sentiment_alignment", 0)) else 0,
        "reason": payload.get("reason", ""),
    }


def compute_fidelity_pass(judge_result: Dict[str, Any], rule_checks: Dict[str, Any]) -> tuple[bool, List[str]]:
    failures: List[str] = []

    if judge_result.get("overall_score", 0) < MIN_OVERALL_SCORE:
        failures.append("overall_score_below_threshold")
    if judge_result.get("unsupported_claims", 0) > 0:
        failures.append("unsupported_claims_present")
    if judge_result.get("contradicted_claims", 0) > 0:
        failures.append("contradicted_claims_present")
    if judge_result.get("claim_count", 0) < MIN_CLAIM_COUNT:
        failures.append("too_few_claims")
    if judge_result.get("claim_precision", 0.0) < MIN_CLAIM_PRECISION:
        failures.append("claim_precision_below_threshold")
    if judge_result.get("aspect_coverage", 0.0) < MIN_ASPECT_COVERAGE:
        failures.append("aspect_coverage_below_threshold")
    if judge_result.get("sentiment_alignment", 0) != 1:
        failures.append("sentiment_not_aligned")

    if rule_checks.get("unsupported_age_claim"):
        failures.append("unsupported_age_claim")
    if rule_checks.get("average_rating_mismatch"):
        failures.append("average_rating_mismatch")
    if rule_checks.get("negative_sentiment_conflict"):
        failures.append("negative_sentiment_conflict")
    if rule_checks.get("positive_sentiment_conflict"):
        failures.append("positive_sentiment_conflict")

    return (len(failures) == 0, failures)


def aggregate_case_result(
    product_id: str,
    raw_reviews: List[Dict[str, Any]],
    ai_summary: str,
    fact_sheet: Dict[str, Any],
    rule_checks: Dict[str, Any],
    judge_result: Dict[str, Any] | None,
    error: str = "",
) -> Dict[str, Any]:
    if error:
        format_passed = bool(rule_checks.get("format_passed", False))
        failure_reasons = ["invalid_run"]
        if not format_passed:
            failure_reasons.extend(rule_checks.get("format_findings", []))
        return {
            "product_id": product_id,
            "status": "invalid_run",
            "error": error,
            "raw_reviews_count": len(raw_reviews),
            "ai_summary": ai_summary,
            "fact_sheet": fact_sheet,
            "rule_checks": rule_checks,
            "judge_result": None,
            "fidelity_passed": False,
            "format_passed": format_passed,
            "passed": False,
            "failure_reasons": failure_reasons,
        }

    if rule_checks["hard_fail"]:
        return {
            "product_id": product_id,
            "status": "rule_failed",
            "error": "",
            "raw_reviews_count": len(raw_reviews),
            "ai_summary": ai_summary,
            "fact_sheet": fact_sheet,
            "rule_checks": rule_checks,
            "judge_result": None,
            "fidelity_passed": False,
            "format_passed": rule_checks.get("format_passed", False),
            "passed": False,
            "failure_reasons": list(rule_checks.get("hard_fail_reasons", [])),
        }

    judge_result = judge_result or {}
    fidelity_passed, fidelity_failures = compute_fidelity_pass(judge_result, rule_checks)
    format_passed = bool(rule_checks.get("format_passed", False))
    failure_reasons = list(fidelity_failures)
    if not format_passed:
        failure_reasons.extend(rule_checks.get("format_findings", []))

    return {
        "product_id": product_id,
        "status": "ok",
        "error": "",
        "raw_reviews_count": len(raw_reviews),
        "ai_summary": ai_summary,
        "fact_sheet": fact_sheet,
        "rule_checks": rule_checks,
        "judge_result": judge_result,
        "fidelity_passed": fidelity_passed,
        "format_passed": format_passed,
        "passed": fidelity_passed and format_passed,
        "failure_reasons": failure_reasons,
    }


def summarize_suite(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(cases)
    invalid = [case for case in cases if case["status"] == "invalid_run"]
    rule_failed = [case for case in cases if case["status"] == "rule_failed"]
    ok_cases = [case for case in cases if case["status"] == "ok"]
    passed_cases = [case for case in ok_cases if case["passed"]]
    fidelity_passed_cases = [case for case in ok_cases if case.get("fidelity_passed")]
    format_passed_cases = [case for case in ok_cases if case.get("format_passed")]

    def avg_metric(metric_name: str) -> float:
        values = [case["judge_result"][metric_name] for case in ok_cases if case.get("judge_result")]
        return round(sum(values) / len(values), 4) if values else 0.0

    total_supported = sum(case["judge_result"].get("supported_claims", 0) for case in ok_cases if case.get("judge_result"))
    total_unsupported = sum(case["judge_result"].get("unsupported_claims", 0) for case in ok_cases if case.get("judge_result"))
    total_contradicted = sum(case["judge_result"].get("contradicted_claims", 0) for case in ok_cases if case.get("judge_result"))
    total_claims = total_supported + total_unsupported + total_contradicted

    return {
        "total_cases": total,
        "ok_cases": len(ok_cases),
        "passed_cases": len(passed_cases),
        "fidelity_passed_cases": len(fidelity_passed_cases),
        "format_passed_cases": len(format_passed_cases),
        "rule_failed_cases": len(rule_failed),
        "invalid_run_cases": len(invalid),
        "overall_pass_rate": round(len(passed_cases) / total, 4) if total else 0.0,
        "fidelity_pass_rate": round(len(fidelity_passed_cases) / total, 4) if total else 0.0,
        "format_pass_rate": round(len(format_passed_cases) / total, 4) if total else 0.0,
        "invalid_run_rate": round(len(invalid) / total, 4) if total else 0.0,
        "rule_failed_rate": round(len(rule_failed) / total, 4) if total else 0.0,
        "avg_fidelity_score": avg_metric("overall_score"),
        "avg_claim_precision": avg_metric("claim_precision"),
        "avg_claim_count": avg_metric("claim_count"),
        "unsupported_claim_rate": round(total_unsupported / total_claims, 4) if total_claims else 0.0,
        "contradiction_rate": round(total_contradicted / total_claims, 4) if total_claims else 0.0,
        "aspect_coverage_avg": avg_metric("aspect_coverage"),
        "sentiment_alignment_rate": round(
            sum(case["judge_result"].get("sentiment_alignment", 0) for case in ok_cases if case.get("judge_result")) / len(ok_cases),
            4,
        ) if ok_cases else 0.0,
    }


def evaluate_one_product(
    product_id: str,
    judge_model: str,
    judge_base_url: str,
    judge_provider: str,
    judge_region: str,
    grpc_timeout_seconds: int,
    judge_timeout_seconds: int,
) -> Dict[str, Any]:
    raw_reviews: List[Dict[str, Any]] = []
    ai_summary = ""
    fact_sheet: Dict[str, Any] = {}
    rule_checks: Dict[str, Any] = {
        "summary_length_chars": 0,
        "sentence_count": 0,
        "word_count": 0,
        "warnings": [],
        "hard_fail_reasons": [],
        "hard_fail": False,
        "format_passed": False,
        "format_findings": [],
        "fidelity_findings": [],
        "unsupported_age_claim": False,
        "average_rating_mentions": [],
        "average_rating_mismatch": False,
        "negative_sentiment_conflict": False,
        "positive_sentiment_conflict": False,
        "product_id_echo": False,
    }

    try:
        raw_reviews = get_raw_reviews_from_db(product_id)
        if not raw_reviews:
            return aggregate_case_result(
                product_id=product_id,
                raw_reviews=[],
                ai_summary="",
                fact_sheet={"product_id": product_id, "review_count": 0},
                rule_checks=rule_checks,
                judge_result=None,
                error="No reviews found for product_id.",
            )

        ai_summary = get_ai_summary_via_grpc(product_id, grpc_timeout_seconds)
        fact_sheet = build_fact_sheet(product_id, raw_reviews)
        rule_checks = run_rule_checks(raw_reviews, ai_summary, fact_sheet)

        judge_result = None
        if not rule_checks["hard_fail"]:
            judge_result = judge_fidelity(
                product_id=product_id,
                raw_reviews=raw_reviews,
                fact_sheet=fact_sheet,
                ai_summary=ai_summary,
                judge_model=judge_model,
                judge_base_url=judge_base_url,
                judge_timeout_seconds=judge_timeout_seconds,
                judge_provider=judge_provider,
                judge_region=judge_region,
            )

        return aggregate_case_result(
            product_id=product_id,
            raw_reviews=raw_reviews,
            ai_summary=ai_summary,
            fact_sheet=fact_sheet,
            rule_checks=rule_checks,
            judge_result=judge_result,
        )
    except Exception as exc:
        return aggregate_case_result(
            product_id=product_id,
            raw_reviews=raw_reviews,
            ai_summary=ai_summary,
            fact_sheet=fact_sheet or {"product_id": product_id},
            rule_checks=rule_checks,
            judge_result=None,
            error=str(exc),
        )


def default_output_path() -> Path:
    artifacts_dir = Path(__file__).resolve().parent / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return artifacts_dir / f"fidelity_eval_{timestamp}.json"


def save_artifact(report: Dict[str, Any], out_path: str) -> Path:
    path = Path(out_path) if out_path else default_output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    product_ids = parse_product_ids(args)

    cases = [
        evaluate_one_product(
            product_id=product_id,
            judge_model=args.judge_model,
            judge_base_url=args.judge_base_url,
            judge_provider=args.judge_provider,
            judge_region=args.judge_region,
            grpc_timeout_seconds=args.grpc_timeout_seconds,
            judge_timeout_seconds=args.judge_timeout_seconds,
        )
        for product_id in product_ids
    ]

    report = {
        "run_id": datetime.now(timezone.utc).isoformat(),
        "candidate_source": f"grpc://{PRODUCT_REVIEWS_ADDR}",
        "judge_provider": args.judge_provider,
        "judge_base_url": args.judge_base_url if args.judge_provider == "openai" else "",
        "judge_region": args.judge_region if args.judge_provider == "bedrock" else "",
        "judge_model": args.judge_model,
        "selection": {
            "all_products": args.all_products,
            "product_count": len(product_ids),
            "product_ids": product_ids,
        },
        "thresholds": {
            "min_claim_count": MIN_CLAIM_COUNT,
            "min_claim_precision": MIN_CLAIM_PRECISION,
            "min_aspect_coverage": MIN_ASPECT_COVERAGE,
            "min_overall_score": MIN_OVERALL_SCORE,
            "max_summary_sentences": MAX_SUMMARY_SENTENCES,
            "max_summary_words": MAX_SUMMARY_WORDS,
        },
        "cases": cases,
        "aggregate": summarize_suite(cases),
    }

    artifact_path = save_artifact(report, args.out)
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(f"Saved artifact to: {artifact_path}")

    if args.strict and any(case["status"] != "ok" or not case["passed"] for case in cases):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())