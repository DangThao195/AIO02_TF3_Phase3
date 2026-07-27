"""
graph/nodes/hallucination_guard.py — HallucinationGuard (simplified)

4 deterministic checks, threshold 0.5.
Auto-PASS nếu response mode là "template" (template format tool data, không hallucinate).
score >= 0.5 → PASS; < 0.5 → FAIL → response_generator safe mode.
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger("graph.hallucination_guard")

# ── Metrics ──
_hallucination_metrics: dict = {"passed": 0, "failed": 0}


def _known_values(tool_results: dict) -> dict:
    """Build lookup sets from tool results for validation."""
    prices: set[str] = set()
    names: set[str] = set()
    scores: set[float] = set()
    counts: set[int] = set()

    for result in tool_results.values():
        r = result if isinstance(result, dict) else {}
        if r.get("price"):
            prices.add(str(r["price"]))
        if r.get("subtotal"):
            prices.add(str(r["subtotal"]))
        if r.get("cost"):
            prices.add(str(r["cost"]))
        if r.get("converted") is not None:
            v = r["converted"]
            if isinstance(v, (int, float)):
                prices.add(f"${float(v):.2f}")
            else:
                prices.add(str(v))
        if r.get("average_score") is not None:
            scores.add(float(r["average_score"]))
        for key in ("total", "total_reviews", "item_count"):
            if r.get(key) is not None:
                counts.add(int(r[key]))

        for p in r.get("products", []) + r.get("items", []) + r.get("recommendations", []):
            if p.get("name"):
                names.add(p["name"].lower())
                names.update(w.lower() for w in p["name"].split())
            if p.get("price"):
                prices.add(str(p["price"]))

    return {"prices": prices, "names": names, "scores": scores, "counts": counts}


def _check_prices(answer: str, known: dict) -> float:
    """Check every $price in answer exists in tool results."""
    matches = set(re.findall(r'\$\d+(?:\.\d{2})?', answer))
    if not matches:
        return 0.0
    violations = matches - known["prices"]
    if violations:
        for v in violations:
            # Allow if the price appears as substring of a known price
            if not any(v in kp for kp in known["prices"]):
                return 0.30
    return 0.0


def _check_empty_evidence(answer: str, tool_results: dict) -> float:
    """If all tool results empty but answer claims specifics → penalty."""
    has_data = any(
        bool(r.get("products") or r.get("items") or r.get("total", 0) > 0)
        for r in tool_results.values() if isinstance(r, dict)
    )
    if has_data:
        return 0.0

    if re.search(r'\$\d+', answer) or re.search(r'\*\*[^*]{3,}\*\*', answer):
        return 0.50
    return 0.0


def _check_action_confirm(answer: str, state: dict) -> float:
    """Check action confirm claims only when actually confirmed."""
    if not re.search(r'(đã thêm|đã xoá|đã cập nhật|đã thực hiện)', answer, re.I):
        return 0.0
    if state.get("pending_action") and not state.get("confirmed"):
        return 0.30
    return 0.0


def _check_entity_list(answer: str, known: dict) -> float:
    """Check if named entities in answer appear in tool results (substring match)."""
    bold_names = re.findall(r'\*\*([^*]+)\*\*', answer)
    if not bold_names:
        return 0.0

    violations = 0
    for name in bold_names:
        name_lower = name.strip().lower()
        if not name_lower:
            continue
        found = any(name_lower in kn for kn in known["names"])
        if not found:
            violations += 1

    if violations > 0 and violations >= len(bold_names) * 0.5:
        return 0.40
    return 0.0


async def hallucination_guard_node(state: dict) -> dict:
    """
    HallucinationGuard (simplified): 4 checks, threshold 0.5.
    Template mode → auto PASS (templates only format tool data, never fabricate).
    Output: {groundedness_score, hallucination_detected, node_durations}
    """
    t0 = time.time()

    mode = state.get("response_mode", "llm")
    answer = state.get("final_answer", "")
    tool_results = state.get("tool_results") or {}

    # Template mode always passes — templates just format existing tool data
    if mode == "template":
        return {
            "groundedness_score": 1.0,
            "hallucination_detected": False,
            "node_durations": {"hallucination_guard": int((time.time() - t0) * 1000)},
        }

    if not answer or not tool_results:
        return {
            "groundedness_score": 1.0,
            "hallucination_detected": False,
            "node_durations": {"hallucination_guard": int((time.time() - t0) * 1000)},
        }

    known = _known_values(tool_results)
    score = 1.0

    score -= _check_prices(answer, known)
    score -= _check_entity_list(answer, known)
    score -= _check_action_confirm(answer, state)
    score -= _check_empty_evidence(answer, tool_results)
    score = max(0.0, min(1.0, score))

    hallucination_detected = score < 0.5

    if hallucination_detected:
        _hallucination_metrics["failed"] += 1
    else:
        _hallucination_metrics["passed"] += 1

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[hallucination_guard] mode=%s score=%.2f detected=%s (%dms)",
                mode, score, hallucination_detected, duration_ms)

    result = {
        "groundedness_score": score,
        "hallucination_detected": hallucination_detected,
        "node_durations": {"hallucination_guard": duration_ms},
    }
    if hallucination_detected:
        result["safe_mode"] = True
    return result
