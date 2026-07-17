from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


@dataclass
class SynonymCache:
    """Small local synonym cache for shopping search queries."""

    phrase_map: dict[str, list[str]] = field(default_factory=lambda: {
        "kính thiên văn": ["telescope", "astronomy telescope", "stargazing"],
        "ống nhòm": ["binoculars", "field binoculars"],
        "đèn pin": ["flashlight", "torch"],
        "máy ảnh": ["camera", "digital camera"],
        "máy đánh chữ": ["typewriter", "vintage typewriter"],
        "sách": ["book", "books"],
        "đồ chơi": ["toy", "toys"],
        "tai nghe": ["headphones", "earbuds"],
        "loa": ["speaker", "audio speaker"],
        "cắm trại": ["camping", "outdoor camping"],
        "du lịch": ["travel", "touring"],
        "giá rẻ": ["affordable", "cheap"],
        "rẻ nhất": ["cheapest", "lowest price"],
        "đắt nhất": ["most expensive", "highest price"],
    })

    word_map: dict[str, list[str]] = field(default_factory=lambda: {
        "kính": ["telescope"],
        "thiên": ["astronomy"],
        "văn": ["stargazing"],
        "ống": ["binoculars"],
        "nhòm": ["binoculars"],
        "đèn": ["flashlight"],
        "pin": ["battery"],
        "cổ": ["vintage"],
        "điển": ["classic"],
        "sách": ["book"],
        "review": ["review", "rating"],
        "đánh": ["review"],
        "giá": ["review"],
        "ship": ["shipping"],
        "giao": ["shipping"],
        "hàng": ["shipping"],
        "mua": ["buy"],
        "kèm": ["bundle", "cross sell"],
        "giỏ": ["cart"],
        "cart": ["cart"],
        "tiền": ["price", "currency"],
    })

    def expand(self, keywords: Iterable[str]) -> List[str]:
        expanded: list[str] = []
        for keyword in keywords:
            normalized = _normalize(str(keyword))
            if not normalized:
                continue
            if normalized in self.phrase_map:
                expanded.extend(self.phrase_map[normalized])
            elif normalized in self.word_map:
                expanded.extend(self.word_map[normalized])
            else:
                expanded.append(normalized)
        return self._unique(expanded)

    def expand_text(self, text: str) -> List[str]:
        text = _normalize(text)
        if not text:
            return []

        terms: list[str] = []
        for phrase in sorted(self.phrase_map.keys(), key=len, reverse=True):
            if phrase in text:
                terms.append(phrase)

        tokens = re.findall(r"[\wÀ-ỹ0-9]+", text)
        terms.extend(token for token in tokens if token not in terms)
        return self.expand(terms)

    def canonical_phrases(self, text: str) -> List[str]:
        text = _normalize(text)
        return [phrase for phrase in self.phrase_map if phrase in text]

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
