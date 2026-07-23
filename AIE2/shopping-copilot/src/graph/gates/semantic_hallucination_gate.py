"""graph/gates/semantic_hallucination_gate.py — Semantic Hallucination Gate"""

from __future__ import annotations
import asyncio
import json
import re
import time
from src.graph.gates.gate_node import gate_node


def _extract_claims(text: str) -> list[str]:
    """Extract factual claims from answer text (price/product/count mentions)."""
    claims = []
    # Price claims
    for m in re.finditer(r'\$[\d,]+(?:\.\d{2})?', text):
        claims.append(f"price: {m.group()}")
    # Score claims
    for m in re.finditer(r'\d+(?:\.\d+)?/5', text):
        claims.append(f"score: {m.group()}")
    # Count claims
    for m in re.finditer(r'\d+\s+(?:sản phẩm|kết quả|đánh giá|item|product)', text, re.I):
        claims.append(f"count: {m.group()}")
    return claims[:5]  # max 5 claims to check


async def semantic_hallucination_gate_node(state: dict) -> dict:
    t0 = time.time()
    final_answer = state.get("final_answer", "")
    tool_results = state.get("tool_results") or {}

    if not final_answer or not tool_results:
        return {
            "semantic_hallucination_detected": False,
            "node_durations": {"semantic_hallucination_gate": int((time.time() - t0) * 1000)},
        }

    claims = _extract_claims(final_answer)
    if not claims:
        return {
            "semantic_hallucination_detected": False,
            "node_durations": {"semantic_hallucination_gate": int((time.time() - t0) * 1000)},
        }

    from src.llm.prompt import GATE_QUESTIONS
    evidence = json.dumps(tool_results, ensure_ascii=False)[:500]

    async def check_claim(claim: str) -> bool:
        question = GATE_QUESTIONS["semantic_hallucination_gate"].format(
            claim=claim, evidence=evidence
        )
        result = await gate_node(question=question, gate_name="semantic_hallucination_gate",
                                  want_reason=True, timeout=2.0)
        return result.decision  # True = claim is grounded

    results = await asyncio.gather(*[check_claim(c) for c in claims], return_exceptions=True)

    # If any claim is NOT grounded → semantic hallucination detected
    any_fail = any(
        (isinstance(r, bool) and not r) or isinstance(r, Exception)
        for r in results
    )

    return {
        "semantic_hallucination_detected": any_fail,
        "node_durations": {"semantic_hallucination_gate": int((time.time() - t0) * 1000)},
    }
