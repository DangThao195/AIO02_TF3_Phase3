from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from src.tools.search.flow1.entity_extractor import EntityExtractor
from src.tools.search.flow1.sql_builder import SQLBuilder
from src.tools.search.models import SearchQuery
from src.tools.search.synonym_cache import SynonymCache


@dataclass
class QueryAnalyzerPipeline:
    """Convert a natural-language shopping query into structured search state."""

    entity_extractor: EntityExtractor = None  # type: ignore[assignment]
    sql_builder: SQLBuilder = None  # type: ignore[assignment]
    synonym_cache: SynonymCache = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.entity_extractor is None:
            self.entity_extractor = EntityExtractor()
        if self.sql_builder is None:
            self.sql_builder = SQLBuilder()
        if self.synonym_cache is None:
            self.synonym_cache = SynonymCache()

    def parse(self, query: str) -> SearchQuery:
        query = (query or "").strip()
        if not query:
            sql = self.sql_builder.build({})
            return SearchQuery(
                raw="",
                keywords_en=[],
                keywords_vn=[],
                sort="relevance",
                intent="general",
                is_complex=False,
                sql=sql,
            )

        extracted = self.entity_extractor.extract(query)
        category = extracted.get("category")
        intent = extracted.get("intent", "product_search")
        price_min = extracted.get("price_min")
        price_max = extracted.get("price_max")
        sort = extracted.get("sort", "relevance") or "relevance"

        keywords_vn = self._extract_vn_keywords(query)
        if not keywords_vn:
            keywords_vn = list(extracted.get("keywords", []))

        keywords_en = self.synonym_cache.expand(keywords_vn)
        if not keywords_en:
            keywords_en = self.synonym_cache.expand_text(query)

        if category and category not in keywords_en:
            keywords_en.append(category)

        is_complex = self._is_complex_query(query, extracted)
        sql = self.sql_builder.build({
            "intent": intent,
            "category": category,
            "price_min": price_min,
            "price_max": price_max,
            "keywords": keywords_en or extracted.get("keywords", []),
            "sort": sort,
        })

        return SearchQuery(
            raw=query,
            category=category,
            keywords_en=self._unique(keywords_en),
            keywords_vn=self._unique(keywords_vn),
            price_min=price_min,
            price_max=price_max,
            sort=sort,
            intent=intent,
            is_complex=is_complex,
            sql=sql,
        )

    def _extract_vn_keywords(self, query: str) -> List[str]:
        phrases = self.synonym_cache.canonical_phrases(query)
        if phrases:
            return phrases

        tokens = re.findall(r"[\wÀ-ỹ0-9]+", query.lower())
        stop_words = {
            "tìm", "tim", "cho", "mình", "toi", "tôi", "cần", "muốn", "muon",
            "cái", "cai", "nào", "nao", "và", "va", "là", "la", "giá", "gia",
            "rẻ", "re", "nhất", "nhat", "đắt", "dat", "sản", "san", "phẩm", "pham",
        }
        return [token for token in tokens if token not in stop_words and len(token) > 1]

    def _is_complex_query(self, query: str, extracted: dict) -> bool:
        lowered = query.lower()
        has_many_filters = sum(
            1
            for key in ("category", "price_min", "price_max")
            if extracted.get(key) not in (None, "")
        ) >= 2
        has_multi_intent_marker = any(token in lowered for token in (" và ", " then ", " rồi ", " sau đó ", " with ", " cùng "))
        has_multi_terms = len(self._extract_vn_keywords(query)) >= 3
        return has_many_filters or has_multi_intent_marker or has_multi_terms

    @staticmethod
    def _unique(values: List[str]) -> List[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
