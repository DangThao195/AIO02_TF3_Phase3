from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import boto3
from openai import OpenAI


JUDGE_SYSTEM_PROMPT = """You are a strict factuality judge for product-review summaries.
Your only job is to detect hallucinations.
Compare the candidate summary against the provided raw reviews.
Return JSON only with these fields:
{
  \"approved\": true | false,
  \"unsupported_claims\": integer,
  \"contradicted_claims\": integer,
  \"reason\": string
}

Rules:
- approved=true only if unsupported_claims == 0 and contradicted_claims == 0.
- Count unsupported claims when the summary states something not supported by any review.
- Count contradicted claims when the summary clearly conflicts with the reviews.
- Ignore style. Focus only on factual support.
"""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_json_payload(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}

    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _build_prompt(product_id: str, raw_reviews: List[Dict[str, Any]], summary_text: str) -> str:
    review_lines = []
    for index, review in enumerate(raw_reviews, start=1):
        review_lines.append(
            f"{index}. reviewer={review.get('username', '')} | score={review.get('score', '')} | review={review.get('description', '')}"
        )

    reviews_block = "\n".join(review_lines)
    return f"""
PRODUCT_ID: {product_id}

RAW_REVIEWS:
{reviews_block}

CANDIDATE_SUMMARY:
{summary_text}

Return JSON only.
""".strip()


def evaluate_summary_fidelity(
    product_id: str,
    raw_reviews: List[Dict[str, Any]],
    summary_text: str,
    judge_model: str,
    judge_provider: str = "openai",
    judge_base_url: str = "",
    judge_api_key: str = "",
    judge_region: str = "us-east-1",
    timeout_seconds: float = 3.0,
) -> Dict[str, Any]:
    normalized_summary = (summary_text or "").strip()
    if not normalized_summary:
        return {
            "approved": False,
            "unsupported_claims": 1,
            "contradicted_claims": 0,
            "reason": "empty_summary",
            "raw_payload": {},
        }

    if not raw_reviews:
        return {
            "approved": False,
            "unsupported_claims": 1,
            "contradicted_claims": 0,
            "reason": "no_reviews_available_for_judge",
            "raw_payload": {},
        }

    judge_prompt = _build_prompt(product_id, raw_reviews, normalized_summary)
    if judge_provider == "bedrock":
        client = boto3.client("bedrock-runtime", region_name=judge_region)
        response = client.converse(
            modelId=judge_model,
            system=[{"text": JUDGE_SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": judge_prompt}],
                }
            ],
            inferenceConfig={"temperature": 0.0, "maxTokens": 300},
        )
        response_text = response["output"]["message"]["content"][0]["text"]
    else:
        client = OpenAI(base_url=judge_base_url, api_key=judge_api_key)
        response = client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": judge_prompt},
            ],
            temperature=0,
            timeout=timeout_seconds,
        )
        response_text = response.choices[0].message.content

    payload = _parse_json_payload(response_text)
    unsupported_claims = _safe_int(payload.get("unsupported_claims"), 0)
    contradicted_claims = _safe_int(payload.get("contradicted_claims"), 0)
    approved = bool(payload.get("approved", unsupported_claims == 0 and contradicted_claims == 0))
    if unsupported_claims > 0 or contradicted_claims > 0:
        approved = False

    return {
        "approved": approved,
        "unsupported_claims": unsupported_claims,
        "contradicted_claims": contradicted_claims,
        "reason": str(payload.get("reason", "")).strip(),
        "raw_payload": payload,
    }
