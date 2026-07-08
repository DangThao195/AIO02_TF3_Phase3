"""Faithfulness guardrail (C4, hard SLO "no misleading summary shown").

Two-tier by cost (NLI faithfulness best practice, 2025): a cheap rule-based tier runs on
every request; an optional LLM-as-judge tier runs only when tier-1 is uncertain or on a
periodic sample. Fail-CLOSED: any error => BLOCK (hide summary). "Thà thiếu còn hơn sai."

Grounding truth = the real reviews from Postgres (product-reviews.fetch_product_reviews_from_db),
NOT the summary text alone. The BTC fault `llmInaccurateResponse` flips a positive product
(L9ECAV7KIM, real avg ~4.6, all 4-5★) into a negative summary ("disappointed, damaged,
poor value, score 1.8") — a sentiment inversion the tier-1 check catches deterministically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..common.metrics import GUARDRAIL_BLOCK


_NEGATIVE = {
    "disappointed", "ineffective", "residue", "sticky", "harsh", "scratches", "scratch",
    "poor", "damaged", "damage", "broke", "broken", "useless", "waste", "avoid", "worst",
    "terrible", "defective", "refund", "unhappy", "unreliable", "flaw",
}
_POSITIVE = {
    "praised", "effective", "essential", "versatile", "value", "clean", "clear", "clarity",
    "recommend", "excellent", "great", "perfect", "lifesaver", "quality", "gentle",
    "pristine", "safely", "love", "best", "reliable",
}


@dataclass
class Verdict:
    passed: bool
    reason: str = ""


def _avg_score(reviews: list[dict]) -> float | None:
    scores = [float(r["score"]) for r in reviews if r.get("score") not in (None, "")]
    return sum(scores) / len(scores) if scores else None


def _tone(text: str) -> tuple[int, int]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return len(words & _POSITIVE), len(words & _NEGATIVE)


class FaithfulnessGuardrail:
    """check(summary, reviews) -> Verdict. Reviews are the source of truth."""

    def __init__(self, sentiment_gap_score: float = 3.5, judge=None):

        self._gap = sentiment_gap_score
        self._judge = judge

    def check(self, summary: str, reviews: list[dict]) -> Verdict:
        if not summary or not summary.strip():
            return self._block("empty_summary")
        if not reviews:

            return self._block("no_reviews_to_verify")

        avg = _avg_score(reviews)
        pos, neg = _tone(summary)


        if avg is not None and avg >= self._gap and neg > pos:
            return self._block(f"sentiment_mismatch(avg={avg:.1f},pos={pos},neg={neg})")


        review_blob = " ".join(r.get("description", "") for r in reviews).lower()
        for defect in ("residue", "scratches", "damaged", "sticky"):
            if defect in summary.lower() and defect not in review_blob:
                return self._block(f"claim_unsupported({defect})")


        if self._judge is not None:
            ok, reason = self._judge(summary, reviews)
            if not ok:
                return self._block(f"judge:{reason}")

        return Verdict(passed=True)

    def _block(self, reason: str) -> Verdict:

        label = reason.split("(")[0]
        GUARDRAIL_BLOCK.labels(reason=label).inc()
        return Verdict(passed=False, reason=reason)
