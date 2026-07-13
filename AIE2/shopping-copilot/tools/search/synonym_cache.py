# tools/search/synonym_cache.py
"""
VN→EN keyword mapping với tự học qua LLM.
"""

import json
from typing import Dict, List, Optional
from llm.llm import llm_model


class SynonymCache:
    """
    Bản đồ VN→EN keyword mapping.
    Seed bằng LLM 1 lần, tự học khi gặp từ mới.
    """

    # Seed map — được sinh bởi LLM 1 lần, hardcode sau khi review
    _SEED_MAP: Dict[str, str] = {
        # === CATEGORY KEYWORDS ===
        # Telescopes
        "kính thiên văn": "telescope",
        "kính viễn vọng": "telescope",
        "dòm sao": "telescope",
        "kính": "telescope",
        "telescope": "telescope",

        # Binoculars
        "ống nhòm": "binoculars",
        "kiếng nhòm": "binoculars",
        "nhòm": "binoculars",
        "roof binoculars": "binoculars",

        # Flashlights
        "đèn pin": "flashlight",
        "đèn": "flashlight",
        "flashlight": "flashlight",
        "red flashlight": "flashlight",

        # Accessories
        "phụ kiện": "accessories",
        "accessories": "accessories",
        "lens cleaning kit": "accessories",
        "cleaning kit": "accessories",

        # Books
        "sách": "book",
        "book": "book",
        "comet book": "book",

        # Travel
        "du lịch": "travel",
        "travel": "travel",

        # Assembly
        "ống kính": "lens",
        "lens": "lens",
        "optical tube assembly": "assembly",
        "assembly": "assembly",

        # === PRODUCT KEYWORDS ===
        "solar": "solar",
        "filter": "filter",
        "solar filter": "solar",
        "comet": "comet",
        "explorascope": "explorascope",
        "starsense": "starsense",
        "eclipsmart": "eclipsmart",
        "refractor": "refractor",

        # === PRICE KEYWORDS (empty string = không search) ===
        "giá rẻ": "",
        "rẻ": "",
        "đắt": "",
        "miễn phí": "",
        "giá thấp": "",
        "giá cao": "",
    }

    def __init__(self):
        self._map: Dict[str, str] = dict(self._SEED_MAP)
        self._pending_llm: set[str] = set()  # Từ đang chờ LLM translate

    def expand(self, vn_keywords: List[str]) -> List[str]:
        """
        Mở rộng danh sách từ khoá VN → EN.
        Cache miss → gọi LLM translate → cache vĩnh viễn.
        """
        en_keywords = set()
        need_llm = []

        for kw in vn_keywords:
            if kw in self._map:
                en = self._map[kw]
                if en:  # Skip empty string (price keywords)
                    en_keywords.add(en)
            else:
                # Từ mới — cần LLM translate
                need_llm.append(kw)

        # LLM translate cho từ mới — gọi batch 1 lần
        if need_llm:
            translations = self._llm_translate_batch(need_llm)
            for vn, en in translations.items():
                self._map[vn] = en
                if en:
                    en_keywords.add(en)

        return list(en_keywords)

    def _llm_translate_batch(self, vn_words: List[str]) -> Dict[str, str]:
        """Translate batch VN→EN bằng LLM."""
        if not vn_words:
            return {}

        words_json = json.dumps(vn_words, ensure_ascii=False)
        response = llm_model.invoke(f"""
Translate these Vietnamese shopping keywords to English.
Only return valid product-related translations. If not product-related or ambiguous, return empty string.

Return ONLY a JSON object like {{"từ_việt": "english_keyword", ...}}
No explanations, just the JSON.

Words: {words_json}
""")

        try:
            result = json.loads(response.content if hasattr(response, 'content') else response)
            return result
        except (json.JSONDecodeError, AttributeError):
            # Fallback: empty translation
            return {w: "" for w in vn_words}

    def get_map(self) -> Dict[str, str]:
        """Return toàn bộ map (debug/audit)."""
        return dict(self._map)

    def update_seed(self, updates: Dict[str, str]) -> None:
        """Update seed map (dùng khi tuning)."""
        self._map.update(updates)

    def seed_from_llm(self, categories: List[str], products: List[str]) -> None:
        """
        Chạy 1 lần khi triển khai để seed map từ catalog thật.
        """
        response = llm_model.invoke(f"""
An astronomy equipment store has these product categories:
{', '.join(categories)}

Products:
{json.dumps(products, ensure_ascii=False, indent=2)}

Generate a comprehensive Vietnamese→English keyword mapping for product search.
Include common Vietnamese words for each category and product type.
Also include common misspellings and variations.

Return JSON ONLY: {{"vi_word": "english_keyword", ...}}
Focus on words that Vietnamese customers would use to search.
If a word is a price-related filter, return empty string as value.
""")

        try:
            new_seeds = json.loads(response.content if hasattr(response, 'content') else response)
            # Merge vào seed map
            self._map.update(new_seeds)
        except (json.JSONDecodeError, AttributeError):
            pass
