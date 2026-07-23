"""
graph/nodes/hallucination_guard.py — HallucinationGuard

Chỉ chạy khi complexity_score > 0.5.
6 exact deterministic checks → groundedness_score.
score >= 0.8 → PASS; < 0.8 → FAIL → FallbackGenerator.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger("graph.hallucination_guard")

# ── Metrics ──
_hallucination_metrics: dict = {"passed": 0, "failed": 0}

# Vietnamese + English stop words for entity extraction
_STOP_WORDS = {
    "và", "hoặc", "của", "này", "đó", "là", "có", "không", "được", "trong",
    "với", "cho", "từ", "đến", "một", "các", "những", "bạn", "tôi", "sản",
    "phẩm", "giá", "tiền", "the", "a", "an", "of", "in", "is", "are", "was",
    "to", "for", "with", "and", "or", "not", "it", "this", "that", "has",
    "have", "be", "been", "at", "on", "by", "from", "as", "but", "if",
}


def _build_known_set(tool_results: dict) -> set[str]:
    """Build known entity set from tool results."""
    known: set[str] = set()
    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        # Products
        for p in r.get("products", []):
            if p.get("name"):
                known.add(p["name"].lower())
            for cat in (p.get("categories") or []):
                known.add(cat.lower())
        # Cart items
        for item in r.get("items", []):
            if item.get("name"):
                known.add(item["name"].lower())
        # Recommendations
        for rec in r.get("recommendations", []):
            if rec.get("name"):
                known.add(rec["name"].lower())
    return known


def _extract_candidate_tokens(text: str) -> list[str]:
    """Extract noun-like tokens ≥3 chars, excluding stop words."""
    words = re.findall(r"[a-zA-ZÀ-ỹ]{3,}", text)
    return [w.lower() for w in words if w.lower() not in _STOP_WORDS]


def _check_prices(answer: str, tool_results: dict) -> float:
    """Check price mentions in answer against tool results. Returns penalty."""
    price_pat = re.compile(r'\$\d+(?:\.\d{2})?')
    answer_prices = set(price_pat.findall(answer))
    if not answer_prices:
        return 0.0

    known_prices: set[str] = set()
    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        # Direct price fields
        if r.get("price"):
            known_prices.add(str(r["price"]))
        # Products
        for p in r.get("products", []) + r.get("items", []) + r.get("recommendations", []):
            if p.get("price"):
                known_prices.add(str(p["price"]))
        # Subtotal
        if r.get("subtotal"):
            known_prices.add(str(r["subtotal"]))
        if r.get("cost"):
            known_prices.add(str(r["cost"]))
        if r.get("converted") is not None:
            val = r["converted"]
            if isinstance(val, (int, float)):
                known_prices.add(f"${float(val):.2f}")
            else:
                known_prices.add(str(val))

    violations = answer_prices - known_prices
    return len(violations) * 0.15


def _check_counts(answer: str, tool_results: dict) -> float:
    """Check count mentions match tool results."""
    count_pat = re.compile(r'(\d+)\s*(sản phẩm|kết quả|đánh giá|món|item|product|review)', re.I)
    matches = count_pat.findall(answer)
    if not matches:
        return 0.0

    known_counts: set[int] = set()
    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        for key in ("total", "total_reviews", "item_count"):
            if r.get(key) is not None:
                known_counts.add(int(r[key]))

    penalty = 0.0
    for count_str, _ in matches:
        c = int(count_str)
        if known_counts and c not in known_counts:
            penalty += 0.15
    return min(penalty, 0.30)


def _check_scores(answer: str, tool_results: dict) -> float:
    """Check star rating mentions."""
    score_pat = re.compile(r'(\d+\.?\d*)\s*/?\s*5')
    matches = score_pat.findall(answer)
    if not matches:
        return 0.0

    known_scores: set[float] = set()
    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        if r.get("average_score") is not None:
            known_scores.add(float(r["average_score"]))

    penalty = 0.0
    for s in matches:
        score = float(s)
        if known_scores and not any(abs(score - k) <= 0.1 for k in known_scores):
            penalty += 0.15
    return min(penalty, 0.15)


def _check_action_confirm(answer: str, state: dict) -> float:
    """Check action confirm claims only when actually confirmed."""
    action_pat = re.compile(r'(đã thêm|đã xoá|đã cập nhật|đã thực hiện)', re.I)
    if not action_pat.search(answer):
        return 0.0
    confirmed = state.get("confirmed", False)
    pending = state.get("pending_action")
    # If claiming action done but not actually confirmed → penalty
    if pending and not confirmed:
        return 0.15
    return 0.0


def _check_entity_list(answer: str, tool_results: dict) -> float:
    """Check entity violations using known_set intersection."""
    known = _build_known_set(tool_results)
    if not known:
        return 0.0

    # Check for zero-result case
    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        if r.get("total") == 0 and r.get("status") in ("success", "empty"):
            # Any entity claim in answer is a violation
            tokens = _extract_candidate_tokens(answer)
            if tokens:
                return 0.50

    tokens = _extract_candidate_tokens(answer)
    if not tokens:
        return 0.0

    violations = [t for t in tokens if len(t) > 4 and t not in known]
    if len(violations) > len(tokens) * 0.6:
        return 0.40
    return 0.0


async def hallucination_guard_node(state: dict) -> dict:
    """
    HallucinationGuard: 6 exact deterministic checks.
    Output: {groundedness_score, hallucination_detected, fallback_used, node_durations}
    """
    t0 = time.time()
    complexity = state.get("complexity_score", 0.0)

    errors = state.get("errors") or []
    # Only run for complex responses; template path → auto PASS
    if complexity <= 0.5 and not errors:
        return {
            "groundedness_score": 1.0,
            "hallucination_detected": False,
            "fallback_used": False,
            "node_durations": {"hallucination_guard": int((time.time() - t0) * 1000)},
        }

    answer = state.get("final_answer", "")
    tool_results = state.get("tool_results") or {}

    if not answer:
        return {
            "groundedness_score": 1.0,
            "hallucination_detected": False,
            "fallback_used": False,
            "node_durations": {"hallucination_guard": int((time.time() - t0) * 1000)},
        }

    score = 1.0

    # Run all 6 checks
    score -= _check_prices(answer, tool_results)
    score -= _check_entity_list(answer, tool_results)
    score -= _check_counts(answer, tool_results)
    score -= _check_scores(answer, tool_results)
    score -= _check_action_confirm(answer, state)
    score = max(0.0, min(1.0, score))

    hallucination_detected = score < 0.8

    if hallucination_detected:
        _hallucination_metrics["failed"] += 1
    else:
        _hallucination_metrics["passed"] += 1

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[hallucination_guard] score=%.2f detected=%s (%dms)",
                score, hallucination_detected, duration_ms)

    result = {
        "groundedness_score": score,
        "hallucination_detected": hallucination_detected,
        "fallback_used": False,
        "node_durations": {"hallucination_guard": duration_ms},
    }

    # Phase 4.1: Nếu PASS và còn claims, gọi semantic_hallucination_gate per-claim
    if not hallucination_detected:
        answer = state.get("final_answer", "")
        if answer:
            from src.graph.gates.semantic_hallucination_gate import _extract_claims
            claims = _extract_claims(answer)
            if claims:
                from src.graph.gates.semantic_hallucination_gate import semantic_hallucination_gate_node
                sem_result = await semantic_hallucination_gate_node(state)
                result["semantic_hallucination_detected"] = sem_result.get("semantic_hallucination_detected", False)
                if sem_result.get("semantic_hallucination_detected"):
                    result["hallucination_detected"] = True
                    result["fallback_used"] = True

    return result
