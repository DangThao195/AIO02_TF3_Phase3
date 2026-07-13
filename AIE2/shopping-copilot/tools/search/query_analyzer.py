# tools/search/query_analyzer.py
"""
Phân tích query tiếng Việt/Anh thành SearchQuery struct.
Phase 1: Regex parse (nhanh, $0)
Phase 2: LLM fallback (chỉ khi regex không bắt được intent/category phức tạp)
"""

import re
import json
import hashlib
from typing import Optional, Tuple, Dict
from tools.search.models import SearchQuery
from llm.llm import llm_model  # LLM client
from memory.cache import CacheStore


class RegexQueryAnalyzer:
    """Parse query dùng regex patterns — zero LLM cost."""

    # Price patterns: dưới X đô, từ X-Y đô, etc.
    PRICE_PATTERNS: list[tuple[re.Pattern, str]] = [
        # dưới/under/below X đô/usd/$
        (re.compile(
            r"(dưới|duoi|du?o[i̛]?i|d?uoi|below|under|<|nhỏ.?hơn|ít.?hơn)",
            re.IGNORECASE
        ), "max"),
        # trên/over/above X đô
        (re.compile(
            r"(trên|tren|over|above|>|lớn.?hơn|nhiêu.?hơn)",
            re.IGNORECASE
        ), "min"),
        # từ X đến Y đô / X-Y đô
        (re.compile(
            r"(từ|tu|from)\s*(\d+)\s*(đến|den|->|to|\-)\s*(\d+)",
            re.IGNORECASE
        ), "range"),
    ]

    SORT_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"rẻ.?nhất|giá.?thấp|cheapest|lowest", re.IGNORECASE), "price_asc"),
        (re.compile(r"mắc.?nhất|đắt.?nhất|giá.?cao|most.?expensive|highest", re.IGNORECASE), "price_desc"),
    ]

    # Category patterns
    CATEGORY_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"kính.?thiên.?văn|kính.?viễn|dòm.?sao|telescope", re.IGNORECASE), "telescopes"),
        (re.compile(r"ống.?nhòm|kiếng.?nhòm|binocular", re.IGNORECASE), "binoculars"),
        (re.compile(r"đèn.?pin|đèn|flashlight", re.IGNORECASE), "flashlights"),
        (re.compile(r"phụ.?kiện|accessor", re.IGNORECASE), "accessories"),
        (re.compile(r"sách|book", re.IGNORECASE), "books"),
        (re.compile(r"du.?lịch|travel", re.IGNORECASE), "travel"),
        (re.compile(r"ống.?kính|lens|assembly", re.IGNORECASE), "assembly"),
    ]

    STOP_WORDS = frozenset([
        "tìm", "tim", "kiếm", "kiem", "cho", "giúp", "giup", "hãy", "hay",
        "có", "muốn", "muon", "mua", "bán", "ban", "ở đâu", "o dau", "nào", "nao"
    ])

    def parse(self, raw: str) -> SearchQuery:
        """Parse query qua regex phase."""
        raw_clean = raw.strip().lower()
        sq = SearchQuery(raw=raw)

        # 1. Extract price
        price_min, price_max = self._extract_price(raw_clean)
        sq.price_min = price_min
        sq.price_max = price_max

        # 2. Extract sort
        sq.sort = self._extract_sort(raw_clean)

        # 3. Extract category
        sq.category = self._extract_category(raw_clean)

        # 4. Extract keywords
        keywords = self._tokenize(raw_clean)
        sq.keywords_vn = [kw for kw in keywords if self._is_vietnamese(kw)]
        sq.keywords_en = [kw for kw in keywords if not self._is_vietnamese(kw)]

        # 5. Detect intent
        if not raw_clean or len(raw_clean) < 2:
            sq.intent = "browse"
        elif sq.has_price_filter or sq.has_category:
            sq.intent = "search"
        else:
            sq.intent = "unknown"

        # 6. Complex query detection (multi-intent → trigger LLM rerank)
        sq.is_complex = (sq.has_price_filter and sq.has_category) or len(keywords) > 5

        return sq

    def _extract_price(self, text: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract price_min, price_max từ text."""
        price_min = None
        price_max = None

        # Range pattern: từ X đến Y
        range_match = re.search(r"(từ|tu|from)\s*(\d+)\s*(đến|den|->|to|\-)\s*(\d+)", text, re.IGNORECASE)
        if range_match:
            price_min = int(range_match.group(2))
            price_max = int(range_match.group(4))
            return price_min, price_max

        # Max price (dưới X)
        max_match = re.search(r"(dưới|duoi|below|under|<)\s*(\d+)", text, re.IGNORECASE)
        if max_match:
            price_max = int(max_match.group(2))

        # Min price (trên/từ X)
        min_match = re.search(r"(trên|tren|over|above|>|từ|tu)\s*(\d+)", text, re.IGNORECASE)
        if min_match:
            price_min = int(min_match.group(2))

        return price_min, price_max

    def _extract_sort(self, text: str) -> str:
        """Extract sort order."""
        for pattern, sort_type in self.SORT_PATTERNS:
            if pattern.search(text):
                return sort_type
        return "relevance"

    def _extract_category(self, text: str) -> Optional[str]:
        """Extract category slug."""
        for pattern, slug in self.CATEGORY_PATTERNS:
            if pattern.search(text):
                return slug
        return None

    def _tokenize(self, text: str) -> list[str]:
        """Tách từ, loại bỏ stop words."""
        # Tách từ (split by space, punct)
        tokens = re.findall(r"\w+", text, re.UNICODE)
        # Loại bỏ stop words
        return [t for t in tokens if t not in self.STOP_WORDS and len(t) > 1]

    def _is_vietnamese(self, word: str) -> bool:
        """Kiểm tra nếu từ có ký tự tiếng Việt."""
        vietnamese_chars = "àáạãảâầấậẫẩăằắặẵẳèéẹẽẻêềếệễểđìíịĩỉòóọõỏôồốộỗổơờớợỡửùúụũủưừứựữỳýỵỹỷ"
        return any(c in word for c in vietnamese_chars)


class QueryAnalyzerPipeline:
    """Pipeline: Regex → LLM parse fallback."""

    def __init__(self):
        self.regex_analyzer = RegexQueryAnalyzer()
        self.cache = CacheStore()
        self.llm = llm_model

    def parse(self, raw: str) -> SearchQuery:
        """
        Parse query qua pipeline:
        1. Regex parse
        2. Nếu cần (category = None hoặc is_complex = True), dùng LLM parse fallback
        """
        # Bước 1: Regex parse
        sq = self.regex_analyzer.parse(raw)

        # Bước 2: LLM parse fallback nếu cần
        needs_llm = (
            sq.category is None  # Regex không bắt được category
            or sq.is_complex  # Query phức tạp multi-intent
            or len(raw) > 50  # Query dài → có thể có intent ẩn
        )

        if needs_llm:
            llm_result = self._llm_parse_cached(raw)
            if llm_result:
                self._merge_llm_result(sq, llm_result)

        return sq

    def _llm_parse_cached(self, raw: str) -> Optional[Dict]:
        """
        LLM parse với cache 24h theo hash query.
        """
        cache_key = f"llm_parse:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
        cached = self.cache.get_raw(cache_key)
        if cached:
            return cached

        # LLM call
        response = self.llm.invoke(f"""
You are a shopping query parser for an astronomy equipment store.

Product categories: telescopes, binoculars, accessories, flashlights, books, travel, assembly
All product names are in English. Prices in USD.

Parse this Vietnamese or English shopping query.
Return ONLY a JSON object with these fields (or empty object if cannot parse):
- "category": one of the categories above, or null
- "intent": "search" | "browse" | "compare"
- "keywords_en": list of English keywords
- "price_max": integer or null
- "price_min": integer or null
- "sort": "relevance" | "price_asc" | "price_desc"

Query: "{raw}"
""")

        try:
            result = json.loads(response.content if hasattr(response, 'content') else response)
            # Cache 24h
            self.cache.set_raw(cache_key, result, ttl=86400)
            return result
        except (json.JSONDecodeError, AttributeError):
            return None

    def _merge_llm_result(self, sq: SearchQuery, llm_result: Dict) -> None:
        """Merge LLM parse result vào SearchQuery."""
        # Merge category (LLM override nếu regex miss)
        if llm_result.get("category") and not sq.category:
            sq.category = llm_result["category"]

        # Merge intent nếu LLM rõ ràng hơn
        if llm_result.get("intent"):
            sq.intent = llm_result["intent"]

        # Merge keywords
        if llm_result.get("keywords_en"):
            sq.keywords_en.extend(llm_result["keywords_en"])
            sq.keywords_en = list(set(sq.keywords_en))  # Dedup

        # Merge price (LLM chi tiết hơn)
        if llm_result.get("price_min") and not sq.price_min:
            sq.price_min = llm_result["price_min"]
        if llm_result.get("price_max") and not sq.price_max:
            sq.price_max = llm_result["price_max"]

        # Merge sort
        if llm_result.get("sort") and sq.sort == "relevance":
            sq.sort = llm_result["sort"]
