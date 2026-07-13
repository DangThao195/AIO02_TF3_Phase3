# Đặc tả thiết kế — Multi-Strategy Search Tool

> **Phiên bản:** 1.0.0 | **Ngày:** 2026-07-10 | **Đội:** AIO02 — TF3  
> Tài liệu này mô tả chi tiết kiến trúc, luồng xử lý, và cách triển khai module search mới
> thay thế `search_products_tool` hiện tại. Thiết kế dựa trên constraint: **không vector storage,
> không embedding model**, query từ người dùng Việt, tên sản phẩm tiếng Anh.

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Chi tiết các module](#3-chi-tiết-các-module)
   - 3.1 [SearchQuery — Cấu trúc dữ liệu trung tâm](#31-searchquery--cấu-trúc-dữ-liệu-trung-tâm)
   - 3.2 [Query Analyzer](#32-query-analyzer)
   - 3.3 [Search Orchestrator](#33-search-orchestrator)
   - 3.4 [Các Strategy](#34-các-strategy)
   - 3.5 [Result Merger & Ranker](#35-result-merger--ranker)
   - 3.6 [LLM Rerank Trigger](#36-llm-rerank-trigger)
4. [Cache strategy](#4-cache-strategy)
5. [Synonym Cache](#5-synonym-cache)
6. [Cấu trúc thư mục & file mới](#6-cấu-trúc-thư-mục--file-mới)
7. [Tích hợp vào hệ thống hiện tại](#7-tích-hợp-vào-hệ-thống-hiện-tại)
8. [Kế hoạch triển khai](#8-kế-hoạch-triển-khai)
9. [Chi phí vận hành](#9-chi-phí-vận-hành)
10. [Definition of Done](#10-definition-of-done)

---

## 1. Tổng quan

### 1.1 Vấn đề

- **Search hiện tại:** `search_products_tool` gửi thẳng query → gRPC → `LIKE %query%` trên DB.
- **User Việt Nam** search tiếng Việt: `"kính thiên văn"` → `LIKE '%kính thiên văn%'` → **0 kết quả**.
- **Tên sản phẩm hoàn toàn tiếng Anh** (astronomy/outdoor equipment).
- **Không thể dùng embedding/vector** do chi phí.
- **Catalog có thể scale** lên hàng trăm sản phẩm trong tương lai.

### 1.2 Giải pháp

Xây dựng **Search Orchestrator** với multi-strategy pattern:

```
LLM Parse Query → Nhiều Strategy chạy song song → Merge + Dedup → Rule Rank → LLM Rerank (nếu cần) → Final
```

---

## 2. Kiến trúc tổng thể

### 2.1 Sơ đồ luồng xử lý

```
User query (str)
    │
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  1. QUERY ANALYZER                                                   │
│                                                                      │
│  ┌─────────────────────────┐   ┌──────────────────────────────┐     │
│  │ Regex Phase             │   │ LLM Parse (fallback)          │     │
│  │ • Price: /dưới (\d+)/  │──▶│ • Category detection          │     │
│  │ • Sort: /rẻ nhất/      │   │ • Intent classification       │     │
│  │ └──────┬────────────────┘   │ • Keyword extraction          │     │
│  │        │ regex fail         │ • Cached 24h theo hash query │     │
│  │        │ (query phức tạp)   └──────────────────────────────┘     │
│  ▼        ▼                                                          │
│  SearchQuery(simplified)  SearchQuery(full)                          │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2. SEARCH ORCHESTRATOR                                             │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Chạy song song (asyncio.gather, timeout mỗi strategy 3s)    │   │
│  │                                                              │   │
│  │  ┌──────────────────┐  ┌──────────────┐  ┌────────────────┐ │   │
│  │  │ Strategy A       │  │ Strategy B   │  │ Strategy C     │ │   │
│  │  │ Full Catalog     │  │ Direct DB    │  │ Synonym        │ │   │
│  │  │ In-memory filter │  │ gRPC variant │  │ VN→EN Expand   │ │   │
│  │  └──────┬───────────┘  └──────┬───────┘  └───────┬────────┘ │   │
│  │         └──────────┬──────────┘                  │           │   │
│  │                    ▼                             │           │   │
│  │         Pool A: 0~N items           Pool C: 0~N items        │   │
│  │                    └──────────┬──────────────────┘           │   │
│  │                               ▼                              │   │
│  │                    Pool hợp nhất (raw)                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  3. RESULT MERGER & RANKER                                          │
│                                                                      │
│  • Dedup theo product_id (giữ entry từ strategy có score cao nhất)  │
│  • Price filter (nếu có)                                            │
│  • Rule-based score:                                                 │
│      exact_name_match    = 100                                      │
│      keyword_in_name     =  50                                      │
│      keyword_in_cat      =  30                                      │
│      keyword_in_desc     =  20                                      │
│      fuzzy_name_match    =  40                                      │
│      sum all, apply price penalty                                   │
│  • Sort descending theo score                                       │
│  • Giữ top 15 (hoặc tất cả nếu ≤ 15)                               │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   │ pool > 5 AND query phức tạp?
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  4. LLM RERANK (conditional)                                         │
│                                                                      │
│  • Chỉ chạy khi: pool > 5 AND (query có multi-intent OR             │
│                   có LLM parse phase trước đó)                       │
│  • Prompt: "Given query '{query}', rank these products...           │
│             Consider: relevance, price fit, category match"          │
│  • Output: thứ tự ưu tiên mới                                       │
│  • Cost: ~200 tokens = ~$0.00001                                    │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  5. RESULT FORMATTER → LLM tổng hợp câu trả lời                     │
│                                                                      │
│  • Format: tiếng Việt, grounded, đề xuất sản phẩm kèm lý do         │
│  • Nếu 0 kết quả: trả toàn bộ catalog + "Không tìm thấy phù hợp"   │
│  • Nếu có kết quả: top 3-5, mỗi sản phẩm kèm giá + lý do đề xuất   │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Nguyên tắc thiết kế

| Nguyên tắc | Mô tả |
|---|---|
| **Multi-strategy** | Không phụ thuộc một phương án duy nhất — fallback chain |
| **Zero-cost path** | Regex + in-memory filter là path chính, LLM là fallback |
| **Cache mọi thứ** | Synonym map, LLM parse result, empty result session-level |
| **Song song hoá** | Các strategy chạy đồng thời, timeout mỗi strategy 3s |
| **Grounded** | Kết quả phải trace được từ DB / catalog thật |

---

## 3. Chi tiết các module

### 3.1 SearchQuery — Cấu trúc dữ liệu trung tâm

```python
# tools/search/models.py

@dataclass
class SearchQuery:
    """Cấu trúc query đã được parse, dùng cho mọi strategy."""
    raw: str                                    # Query gốc từ user
    keywords_en: list[str]                      # Từ khoá tiếng Anh đã extract
    keywords_vn: list[str]                      # Từ khoá tiếng Việt gốc
    price_min: int | None = None                # Lọc giá tối thiểu (USD)
    price_max: int | None = None                # Lọc giá tối đa (USD)
    category: str | None = None                 # Category slug (telescopes, ...)
    intent: Literal["search", "browse",         # Ý định người dùng
                     "compare", "unknown"] = "search"
    sort: Literal["relevance", "price_asc",     # Cách sắp xếp
                  "price_desc"] = "relevance"
    is_complex: bool = False                    # Có multi-intent? → trigger LLM rerank

    @property
    def has_price_filter(self) -> bool:
        return self.price_min is not None or self.price_max is not None

    @property
    def has_category(self) -> bool:
        return self.category is not None
```

### 3.2 Query Analyzer

**File:** `tools/search/query_analyzer.py`

Có 2 phase chạy tuần tự: **Regex Phase** (nhanh, rẻ) → **LLM Parse Phase** (chỉ khi regex không bắt được category/intent).

#### Phase 1: Regex Parse (cost: $0, latency: <1ms)

```python
class RegexQueryAnalyzer:
    """Parse query dùng regex patterns — zero LLM cost."""

    PRICE_PATTERNS: list[tuple[Pattern, str]] = [
        # dưới/under/below X đô/usd/$
        (re.compile(
            r"(dưới|duoi|du?o[i̛]?i|d?uoi|below|under|<|nhỏ.?hơn|ít.?hơn|it.?hon|nho.?hon)\s*(\d+)\s*(đô|usd|\$|dola|do la)",
            re.IGNORECASE
        ), "max"),
        # trên/over/above X đô
        (re.compile(
            r"(trên|tren|over|above|>|lớn.?hơn|lon.?hon|nhiêu.?hơn|nhieu.?hon)\s*(\d+)\s*(đô|usd|\$|dola|do la)",
            re.IGNORECASE
        ), "min"),
        # từ X đến Y đô / X-Y đô
        (re.compile(
            r"(từ|tu|from)\s*(\d+)\s*(đến|den|->|to|\-)\s*(\d+)\s*(đô|usd|\$|dola|do la)",
            re.IGNORECASE
        ), "range"),
        # X đô (đơn lẻ — coi là giá tham khảo)
        (re.compile(
            r"(\d+)\s*(đô|usd|\$|dola|do la)",
            re.IGNORECASE
        ), "approx"),
    ]

    SORT_PATTERNS: list[tuple[Pattern, str]] = [
        (re.compile(r"rẻ.?nhất|re.?nhat|giá.?thấp.?nhất|gia.?thap.?nhat|cheapest|lowest"), "price_asc"),
        (re.compile(r"mắc.?nhất|mac.?nhat|đắt.?nhất|dat.?nhat|giá.?cao.?nhất|gia.?cao.?nhat|most.?expensive|highest"), "price_desc"),
    ]

    # Category map: pattern VN → category slug
    CATEGORY_PATTERNS: list[tuple[Pattern, str]] = [
        (re.compile(r"kính.?thiên.?văn|kính.?viễn.?vọng|dòm.?sao|telescope|kinh.thien.van"), "telescopes"),
        (re.compile(r"ống.?nhòm|kiếng.?nhòm|ong.nhom|binocular"), "binoculars"),
        (re.compile(r"đèn.?pin|đèn|den.pin|flashlight|đèn.?đội|den.doi"), "flashlights"),
        (re.compile(r"phụ.?kiện|phu.kien|accessor"), "accessories"),
        (re.compile(r"sách|book|sach|sach."), "books"),
        (re.compile(r"du.?lịch|du.lich|travel|du.lich"), "travel"),
        (re.compile(r"ống.?kính|ong.kinh|lens|assembly"), "assembly"),
    ]

    KEYWORD_STOP_WORDS = frozenset({
        "tìm|tim|kiếm|kiem|cho|cho tôi|giúp|giup|hãy|hay|có|có không|"
        "muốn|muon|mua|bán|ban|ở đâu|o dau|nào|nao"
    })

    def parse(self, raw: str) -> SearchQuery:
        raw_clean = raw.strip().lower()
        sq = SearchQuery(raw=raw)

        # 1. Price
        sq.price_min, sq.price_max = self._extract_price(raw_clean)

        # 2. Sort
        sq.sort = self._extract_sort(raw_clean)

        # 3. Category
        sq.category = self._extract_category(raw_clean)

        # 4. Keywords — loại bỏ stop words, tách token
        keywords = self._tokenize(raw_clean)
        sq.keywords_vn = [kw for kw in keywords if self._is_vietnamese(kw)]
        sq.keywords_en = [kw for kw in keywords if not self._is_vietnamese(kw)]

        # 5. Intent heuristic
        if not raw_clean or len(raw_clean) < 2:
            sq.intent = "browse"
        elif sq.has_price_filter or sq.has_category:
            sq.intent = "search"
        else:
            sq.intent = "unknown"

        # 6. Complex query detection (multi-intent)
        sq.is_complex = (
            sq.has_price_filter and sq.has_category
        ) or len(keywords) > 5

        return sq

    def _extract_price(self, text: str) -> tuple[int | None, int | None]:
        # Triển khai matching với PRICE_PATTERNS
        # Trả về (price_min, price_max)
        ...

    def _extract_sort(self, text: str) -> str:
        ...

    def _extract_category(self, text: str) -> str | None:
        for pattern, slug in self.CATEGORY_PATTERNS:
            if pattern.search(text):
                return slug
        return None

    def _is_vietnamese(self, word: str) -> bool:
        """Kiểm tra nếu từ chứa ký tự tiếng Việt hoặc không phải ASCII word."""
        return bool(re.search(r'[àáạãảâầấậẫẩăằắặẵẳèéẹẽẻêềếệễểđìíịĩỉòóọõỏôồốộỗổơờớợỡỡởùúụũủưừứựữửỳýỵỹỷ]', word, re.IGNORECASE)) or not word.isascii()
```

#### Phase 2: LLM Parse (fallback, cost: ~$0.000003/cached)

Chỉ chạy khi:
- Regex không phát hiện được category (`sq.category is None`)
- Hoặc query có multi-intent (`is_complex = True`)
- Hoặc query dài > 50 ký tự

```python
def llm_parse_query(raw: str) -> dict | None:
    """Dùng LLM để parse category + intent từ query.
    Kết quả được cache 24h theo SHA256(query)[:16]."""

    cache_key = f"llm_parse:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
    cached = cache_store.get_raw(cache_key)
    if cached:
        return cached

    # Chỉ gọi LLM nếu cache miss
    response = llm_small.invoke(f"""
You are a shopping query parser for an astronomy equipment store.

Products categories: telescopes, binoculars, accessories, flashlights, books, travel, assembly
All product names are in English. Prices in USD.

Parse this Vietnamese or English shopping query.
Return ONLY a JSON object with these fields:
- "category": one of the categories above, or null if unclear
- "intent": "search" | "browse" | "compare"
- "keywords_en": list of English keywords extracted from the query
- "price_max": maximum price in USD, or null
- "price_min": minimum price in USD, or null
- "sort": "relevance" | "price_asc" | "price_desc"

Query: {raw}
""")

    result = json.loads(response.content)
    cache_store.set_raw(cache_key, result, ttl=86400)  # 24h
    return result
```

**Cache hit ratio dự kiến:** Sau 200-300 query đầu, >80% query pattern phổ biến đã được cache.

---

### 3.3 Search Orchestrator

**File:** `tools/search/orchestrator.py`

```python
class SearchOrchestrator:
    """
    Điều phối toàn bộ quy trình search:
    1. Parse query (regex → LLM fallback)
    2. Chạy strategies song song
    3. Merge + rank
    4. LLM rerank (conditional)
    5. Format kết quả
    """

    STRATEGY_TIMEOUT = 3.0  # seconds per strategy
    DEFAULT_TOP_K = 15      # Số lượng tối đa cho ranker phase
    RERANK_THRESHOLD = 5    # Chỉ rerank nếu pool > ngưỡng này

    def __init__(self):
        self.analyzer = QueryAnalyzerPipeline()        # Regex + LLM parse
        self.strategies: list[SearchStrategy] = [
            FullCatalogStrategy(),                     # Always
            DirectDBStrategy(),                        # Always
            SynonymExpansionStrategy(),                # Nếu query có VN keywords
        ]
        self.ranker = ResultRanker()
        self.reranker = LLMReranker()
        self.cache = SearchCache()

    async def search(self, raw_query: str) -> SearchResult:
        """Entry point cho toàn bộ search pipeline."""

        # Step 1: Kiểm tra session cache cho empty result
        cached_empty = self.cache.get_session_empty(raw_query)
        if cached_empty:
            return SearchResult.empty(f"Query '{raw_query}' không có kết quả (session cache)")

        # Step 2: Parse query
        sq = self.analyzer.parse(raw_query)

        # Step 3: Chạy strategies song song
        pool = await self._run_strategies_parallel(sq)

        # Step 4: Merge + dedup + rule rank
        merged = self.ranker.merge_and_rank(pool, sq)
        top_n = merged[:self.DEFAULT_TOP_K]

        # Step 5: LLM rerank nếu cần
        if len(top_n) > self.RERANK_THRESHOLD and (sq.is_complex or sq.intent == "compare"):
            top_n = await self.reranker.rerank(top_n, sq)

        # Step 6: Format + return
        if not top_n:
            # Cache empty result ở session level
            self.cache.set_session_empty(raw_query)
            return SearchResult.empty(
                "Không tìm thấy sản phẩm phù hợp. "
                "Đây là toàn bộ mặt hàng đang bán:\n" + self._format_products(all_products())
            )

        return SearchResult(
            query=sq,
            products=top_n,
            total=len(top_n),
            strategies_used=[s.name for s in self.strategies if s.was_used],
        )

    async def _run_strategies_parallel(self, sq: SearchQuery) -> list[ScoredProduct]:
        """Chạy tất cả strategies song song với timeout."""
        tasks = [
            asyncio.create_task(strategy.search(sq))
            for strategy in self.strategies
            if strategy.should_run(sq)
        ]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.STRATEGY_TIMEOUT
            )
        except asyncio.TimeoutError:
            results = [t.result() if t.done() else []
                       for t in tasks]

        # Gộp tất cả pool
        pool = []
        for r in results:
            if isinstance(r, list):
                pool.extend(r)
        return pool
```

### 3.4 Các Strategy

#### 3.4.1 Strategy Interface

```python
# tools/search/strategies.py

class SearchStrategy(ABC):
    """Interface cho mọi search strategy."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def should_run(self, sq: SearchQuery) -> bool:
        """Strategy có nên chạy với query này không?"""
        ...

    @abstractmethod
    async def search(self, sq: SearchQuery) -> list[ScoredProduct]:
        """Thực thi search, trả về danh sách có score."""
        ...

    @property
    def was_used(self) -> bool:
        return self._was_used
```

#### 3.4.2 Strategy A: FullCatalogStrategy (always run, $0)

```python
class FullCatalogStrategy(SearchStrategy):
    """
    Load toàn bộ catalog vào cache (ListProducts).
    Filter + score in-memory.
    Luôn chạy — là baseline nhanh nhất.
    """

    name = "full_catalog"
    CACHE_TTL = 300  # 5 phút

    async def search(self, sq: SearchQuery) -> list[ScoredProduct]:
        self._was_used = True
        products = await self._get_all_products()
        scored = []

        for p in products:
            score = self._score_product(p, sq)
            if score > 0:
                scored.append(ScoredProduct(p, score))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def _score_product(self, p: Product, sq: SearchQuery) -> float:
        """
        Rule-based scoring — dùng để rank sản phẩm theo relevance.

        Weight:
        - Exact name match:         100
        - Keyword in name:           50  (mỗi keyword)
        - Keyword in category:       30  (mỗi keyword)
        - Keyword in description:    20  (mỗi keyword)
        - Fuzzy name match >80%:     40
        - Category match:            60

        Penalty:
        - Price > max:               -1000 (loại)
        - Price < min:               -1000 (loại)
        """
        score = 0.0
        name_lower = p.name.lower()
        desc_lower = p.description.lower() if p.description else ""
        cats_lower = [c.lower() for c in p.categories]

        # Price penalty (loại bỏ nếu ngoài khoảng)
        if sq.has_price_filter:
            price = p.price_usd.units
            if sq.price_max is not None and price > sq.price_max:
                return -1
            if sq.price_min is not None and price < sq.price_min:
                return -1

        # Category match
        if sq.category and sq.category in cats_lower:
            score += 60

        # Name match
        if sq.raw.lower() == name_lower:
            score += 100
        elif sq.raw.lower() in name_lower:
            score += 80

        # Keyword matches
        for kw in sq.keywords_en:
            if kw in name_lower:
                score += 50
            if kw in desc_lower:
                score += 20
            for cat in cats_lower:
                if kw in cat:
                    score += 30

        # Fuzzy match cho misspell
        for kw in sq.keywords_en:
            if len(kw) > 3:
                from rapidfuzz import fuzz
                if fuzz.partial_ratio(kw, name_lower) > 80:
                    score += 40
                    break

        return score

    async def _get_all_products(self) -> list[Product]:
        """Lấy từ cache hoặc gọi ListProducts gRPC."""
        cached = cache_store.get_raw("full_catalog")
        if cached:
            return [Product.from_dict(d) for d in cached]

        # Gọi gRPC ListProducts
        products = await grpc_list_products()
        # Cache
        cache_store.set_raw("full_catalog",
                           [p.to_dict() for p in products],
                           ttl=self.CACHE_TTL)
        return products
```

#### 3.4.3 Strategy B: DirectDBStrategy (always run, $0)

```python
class DirectDBStrategy(SearchStrategy):
    """
    Gọi SearchProducts gRPC với nhiều query variant.
    Dùng cho query tiếng Anh khớp trực tiếp tên sản phẩm.
    """

    name = "direct_db"

    async def search(self, sq: SearchQuery) -> list[ScoredProduct]:
        self._was_used = True
        pool = []

        # Build variants
        variants = self._build_variants(sq)
        for variant in variants:
            try:
                results = await grpc_search_products(variant)
                for p in results:
                    pool.append(ScoredProduct(p, score=self._base_score(p, sq)))
            except Exception:
                continue

        return pool

    def _build_variants(self, sq: SearchQuery) -> list[str]:
        """Build nhiều query variant để tăng recall."""
        variants = [sq.raw]  # query gốc

        # Nếu có category, gửi category slug
        if sq.category:
            variants.append(sq.category)

        # Mỗi keyword riêng lẻ
        for kw in sq.keywords_en:
            if kw not in variants:
                variants.append(kw)

        return list(set(variants))

    def _base_score(self, p: Product, sq: SearchQuery) -> float:
        """Score cơ bản — sẽ được merge và rescore ở ranker."""
        name_lower = p.name.lower()
        if sq.raw.lower() in name_lower:
            return 50
        for kw in sq.keywords_en:
            if kw in name_lower:
                return 30
        return 10
```

#### 3.4.4 Strategy C: SynonymExpansionStrategy (chạy khi query có VN keywords)

```python
class SynonymExpansionStrategy(SearchStrategy):
    """
    Mở rộng query tiếng Việt sang tiếng Anh dùng synonym cache.
    Cache miss → LLM translate 1 lần → cache vĩnh viễn.
    """

    name = "synonym_expansion"

    def __init__(self):
        self.synonym_cache = SynonymCache()

    def should_run(self, sq: SearchQuery) -> bool:
        # Chỉ chạy khi query có từ khoá tiếng Việt
        return len(sq.keywords_vn) > 0

    async def search(self, sq: SearchQuery) -> list[ScoredProduct]:
        self._was_used = True
        en_keywords = self.synonym_cache.expand(sq.keywords_vn)

        if not en_keywords:
            return []

        # Dùng DB strategy để search với từng keyword
        pool = []
        for kw in en_keywords:
            try:
                results = await grpc_search_products(kw)
                for p in results:
                    pool.append(ScoredProduct(p, score=35))  # Synonym match base score
            except Exception:
                continue

        return pool
```

### 3.5 Result Merger & Ranker

**File:** `tools/search/ranker.py`

```python
@dataclass
class ScoredProduct:
    """Sản phẩm kèm score từ strategy."""
    product: Product
    score: float
    strategy_name: str = ""

class ResultRanker:
    """Merge kết quả từ nhiều strategy, dedup, rescore, rank."""

    def merge_and_rank(
        self,
        pools: list[list[ScoredProduct]],
        sq: SearchQuery
    ) -> list[ScoredProduct]:
        """Merge nhiều pool, dedup theo product_id, rescore, sort."""
        merged: dict[str, ScoredProduct] = {}

        for pool in pools:
            for sp in pool:
                pid = sp.product.id
                # Dedup: giữ entry có score cao nhất
                if pid not in merged or sp.score > merged[pid].score:
                    merged[pid] = sp

        scored = list(merged.values())

        # Rescore với price/sort adjustment
        for sp in scored:
            sp.score = self._adjust_score(sp, sq)

        # Sort
        reverse = sq.sort != "price_asc"
        scored.sort(key=lambda x: (
            x.score,
            -x.product.price_usd.units if sq.sort == "price_desc"
            else x.product.price_usd.units if sq.sort == "price_asc"
            else 0
        ), reverse=reverse)

        return scored

    def _adjust_score(self, sp: ScoredProduct, sq: SearchQuery) -> float:
        """Điều chỉnh score dựa trên price và sort."""
        score = sp.score

        # Price proximity bonus (nếu có price filter)
        if sq.has_price_filter:
            price = sp.product.price_usd.units
            if sq.price_max:
                # Sản phẩm gần price_max nhất được bonus nhẹ (không phải rẻ nhất)
                proximity = 1.0 - (sq.price_max - min(price, sq.price_max)) / max(sq.price_max, 1)
                score += proximity * 10

        return score
```

### 3.6 LLM Rerank Trigger

**File:** `tools/search/reranker.py`

Chỉ chạy khi:
- Pool > 5 sản phẩm
- Query phức tạp (multi-intent: vừa category vừa price, hoặc so sánh)

```python
class LLMReranker:
    """Dùng LLM để rerank top products dựa trên query intent."""

    async def rerank(
        self,
        products: list[ScoredProduct],
        sq: SearchQuery
    ) -> list[ScoredProduct]:
        """Rerank top products. Input: max 15 products. Output: same list reordered."""

        if len(products) <= 1:
            return products

        product_lines = [
            f"{i+1}. {p.product.name} — ${p.product.price_usd.units} — "
            f"Categories: {', '.join(p.product.categories)}"
            for i, p in enumerate(products)
        ]

        response = await llm_small.ainvoke(f"""
You are a product ranking assistant. Given a user's shopping query and a list of products,
re-rank the products by relevance to the query.

Rules:
- Consider: keyword match, price fit, category match, user intent
- Output ONLY a comma-separated list of the original product numbers in new order
- If no clear ranking difference, keep original order
- Max 15 products

User query: "{sq.raw}"
Price range: {f'${sq.price_min} - ${sq.price_max}' if sq.has_price_filter else 'no filter'}
Category: {sq.category or 'any'}

Products:
{chr(10).join(product_lines)}

New order (comma-separated numbers):
""")

        try:
            indices = [
                int(x.strip()) - 1
                for x in response.content.strip().split(",")
                if x.strip().isdigit()
            ]
            # Filter valid indices, preserve original for invalid
            reranked = []
            seen = set()
            for idx in indices:
                if 0 <= idx < len(products) and idx not in seen:
                    reranked.append(products[idx])
                    seen.add(idx)
            # Append any missing products
            for i, p in enumerate(products):
                if i not in seen:
                    reranked.append(p)
            return reranked
        except (ValueError, json.JSONDecodeError):
            # Fallback: giữ nguyên thứ tự
            return products
```

---

## 4. Cache Strategy

### 4.1 Cache layers

| Layer | Scope | TTL | Dữ liệu | Xoá khi |
|---|---|---|---|---|
| **Full catalog** | Global | 300s | `ListProducts()` response | TTL expire |
| **LLM parse result** | Global | 86400s (24h) | Query → structured parse | TTL expire |
| **Synonym map** | Global | ∞ | VN word → EN keyword | Không — tri thức vĩnh viễn |
| **Empty result** | Session | 1800s (session) | `query_hash → empty` | Hết session |
| **gRPC search result** | Global | 300s | `search_products_tool` calls | TTL expire |

### 4.2 Cache key design

```python
# CacheStore mở rộng thêm 2 method:

def get_raw(self, key: str) -> Any | None:
    """Get by raw key (không hash params). Dùng cho full catalog, LLM parse, etc."""
    entry = self._store.get(key)
    if entry and _now_ts() > entry["expires_at_ts"]:
        del self._store[key]
        return None
    return entry["result"] if entry else None

def set_raw(self, key: str, value: Any, ttl: int = 300) -> None:
    """Set by raw key."""
    expires_ts = _now_ts() + ttl
    self._store[key] = {
        "result": value,
        "expires_at_ts": expires_ts,
        "hit_count": 0,
    }
    self._store.move_to_end(key)
```

### 4.3 Session-level empty result cache

```python
# memory/store.py — thêm vào SessionStore

def set_search_empty(self, session_id: str, query: str) -> None:
    """Đánh dấu query này không có kết quả trong session hiện tại."""
    session = self._store.get(session_id)
    if session is None:
        return
    if "empty_searches" not in session:
        session["empty_searches"] = {}
    query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
    session["empty_searches"][query_hash] = _now_ts()

def is_search_empty_cached(self, session_id: str, query: str) -> bool:
    """Kiểm tra query đã từng empty trong session này chưa (trong vòng 30 phút)."""
    session = self._store.get(session_id)
    if session is None:
        return False
    query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
    cached_ts = session.get("empty_searches", {}).get(query_hash)
    if cached_ts is None:
        return False
    if _now_ts() - cached_ts > 1800:  # 30 phút
        del session["empty_searches"][query_hash]
        return False
    return True
```

---

## 5. Synonym Cache

**File:** `tools/search/synonym_cache.py`

### 5.1 Seed data (one-time)

Dùng LLM sinh mapping 1 lần khi triển khai:

```python
class SynonymCache:
    """
    Bản đồ VN→EN keyword mapping.
    Seed bằng LLM 1 lần, tự học khi gặp từ mới.
    Lưu trong memory/cache.json (persist qua restart nếu cần).
    """

    # Seed map — được sinh bởi LLM 1 lần, hardcode sau khi review
    _SEED_MAP: dict[str, str] = {
        # Category keywords
        "kính thiên văn": "telescope",
        "kính viễn vọng": "telescope",
        "dòm sao": "telescope",
        "ống nhòm": "binoculars",
        "kiếng nhòm": "binoculars",
        "đèn pin": "flashlight",
        "đèn": "flashlight",
        "phụ kiện": "accessory",
        "sách": "book",
        "du lịch": "travel",
        "ống kính": "lens",

        # Price-related (trả về empty string — xử lý ở price filter)
        "giá rẻ": "",
        "rẻ": "",
        "đắt": "",
        "miễn phí": "",

        # Common English words VN users might type
        "telescope": "telescope",
        "kính": "telescope",
        "solar": "solar",
        "flashlight": "flashlight",
        "book": "book",
        "comet": "comet",
        "assembly": "assembly",
        "cleaning": "cleaning",
        "kit": "kit",
        "filter": "filter",
    }

    def __init__(self):
        self._map: dict[str, str] = dict(self._SEED_MAP)
        self._pending_llm: set[str] = set()  # Từ đang chờ LLM translate

    def expand(self, vn_keywords: list[str]) -> list[str]:
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
                need_llm.append(kw)

        # LLM translate cho từ mới — gọi batch 1 lần
        if need_llm:
            translations = self._llm_translate_batch(need_llm)
            for vn, en in translations.items():
                self._map[vn] = en
                if en:
                    en_keywords.add(en)

        return list(en_keywords)

    def _llm_translate_batch(self, vn_words: list[str]) -> dict[str, str]:
        """Translate batch VN→EN bằng Groq 8b-instant."""
        response = llm_small.invoke(f"""
Translate these Vietnamese shopping keywords to English.
Only return valid product-related translations. If the word is not product-related, return empty string.

Format: JSON object {{"vi_word": "en_translation", ...}}

Words: {json.dumps(vn_words, ensure_ascii=False)}
""")
        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, AttributeError):
            return {w: "" for w in vn_words}
```

### 5.2 Tổng hợp seed bằng LLM (chạy 1 lần)

```bash
# scripts/seed_synonym_cache.py
# Chạy 1 lần khi deploy:
# python scripts/seed_synonym_cache.py

"""
Dùng LLM sinh VN→EN mapping từ catalog thật.
Output: dict lưu vào SynonymCache._SEED_MAP (hardcode sau review).
"""
categories = ["telescopes", "binoculars", "accessories",
              "flashlights", "books", "travel", "assembly"]

products = [
    "National Park Foundation Explorascope",
    "Starsense Explorer Refractor Telescope",
    "Eclipsmart Travel Refractor Telescope",
    "Lens Cleaning Kit",
    "Roof Binoculars",
    "Solar System Color Imager",
    "Red Flashlight",
    "Optical Tube Assembly",
    "Solar Filter",
    "The Comet Book",
]

response = llm_small.invoke(f"""
An astronomy equipment store has these product categories:
{', '.join(categories)}

Products:
{chr(10).join(f'- {p}' for p in products)}

Generate a comprehensive Vietnamese→English keyword mapping for product search.
Include common Vietnamese words for each category and product type.
Also include common misspellings and variations.

Return JSON: {{"vi_word_or_phrase": "english_keyword"}}
Focus on words that Vietnamese customers would use to search.
""")
```

---

## 6. Cấu trúc thư mục & file mới

```
shopping-copilot/
├── tools/
│   ├── __init__.py                   # [SỬA] Thay search_products_tool → search_products_v2
│   ├── catalog_tool.py               # [GIỮ] search_products_tool (gRPC wrapper cũ)
│   ├── cart_tool.py
│   ├── review_tool.py
│   ├── recommendation_tool.py
│   ├── currency_tool.py
│   ├── shipping_tool.py
│   │
│   └── search/                       # [MỚI] Multi-strategy search module
│       ├── __init__.py               # Export search_products_v2
│       ├── models.py                 # SearchQuery, ScoredProduct, SearchResult
│       ├── query_analyzer.py         # RegexQueryAnalyzer + LLMQueryAnalyzer
│       ├── orchestrator.py           # SearchOrchestrator
│       ├── strategies.py             # FullCatalog, DirectDB, SynonymExpansion
│       ├── ranker.py                 # ResultRanker + merge/dedup
│       ├── reranker.py               # LLMReranker (conditional)
│       ├── synonym_cache.py          # VN→EN mapping + self-learning
│       └── cache.py                  # Search-specific cache (empty result, etc.)
│
├── spec/
│   └── search_design.md              # [MỚI] Tài liệu này
│
└── memory/
    └── store.py                      # [SỬA] Thêm set_search_empty, is_search_empty_cached
```

---

## 7. Tích hợp vào hệ thống hiện tại

### 7.1 Thay đổi trong `tools/__init__.py`

```python
# tools/__init__.py

from tools.catalog_tool import search_products_tool   # Giữ nguyên (gRPC wrapper)
from tools.search import search_products_v2           # MỚI: multi-strategy

from tools.cart_tool import add_to_cart_tool, get_cart_tool
from tools.review_tool import get_product_reviews_tool
from tools.recommendation_tool import get_recommendations_tool
from tools.currency_tool import convert_currency_tool
from tools.shipping_tool import get_shipping_quote_tool

# Danh sách đầy đủ tất cả các công cụ bàn giao cho AI Agent
all_shopping_tools = [
    # NHÓM SEARCH (thay thế)
    search_products_v2,               # MỚI: multi-strategy search
    
    # Nhóm Core (giữ nguyên)
    get_product_reviews_tool,
    add_to_cart_tool,
    get_cart_tool,
    
    # Nhóm Mở rộng (giữ nguyên)
    get_recommendations_tool,
    convert_currency_tool,
    get_shipping_quote_tool,
]
```

### 7.2 Thay đổi trong `agent/prompts.py`

Cập nhật mô tả tool cho LLM:

```python
# Trong SYSTEM_PROMPT, cập nhật mô tả tool:
"""
- `search_products_v2`: Tìm kiếm sản phẩm thông minh bằng tiếng Việt hoặc tiếng Anh.
  Hỗ trợ: tìm theo tên, danh mục, khoảng giá (vd: "dưới 50 đô", "từ 100-200 USD").
  Tự động gợi ý sản phẩm phù hợp nhất. KHÔNG dùng tool cũ search_products_tool nữa.
  Có thể gọi với query tự nhiên bất kỳ.
"""
```

### 7.3 Sửa `agent/copilot_agent.py`

Trong `CopilotAgent.chat()`, search tool không cần qua confirmation gate (read-only). Logic hiện tại đã đúng:
- `add_to_cart_tool` → confirmation gate
- Các tool còn lại → read → cache

Chỉ cần đảm bảo cache cho `search_products_v2` được enable trong `CacheStore`:

```python
# memory/store.py — thêm dòng:
_CACHE_TTL_MAP = {
    "search_products_v2":          300,   # 5 phút (thay thế search_products_tool)
    "get_product_reviews_tool":    300,
    "get_recommendations_tool":    300,
    "convert_currency_tool":        60,
}
```

### 7.4 Async support cho CopilotAgent

Tool mới sử dụng `async/await` (chạy strategies song song). Cần đảm bảo agent gọi đúng:

```python
# agent/copilot_agent.py

# Trong _react_loop, thay đổi chỗ gọi tool:
if tool_name == "search_products_v2":
    # Tool async — chạy qua event loop
    tool_output = await tool_fn.ainvoke(tool_args)
else:
    # Tool sync — chạy bình thường
    tool_output = tool_fn.invoke(tool_args)
```

---

## 8. Kế hoạch triển khai

### Phase 1 — Core (Buổi 1-2)

| Bước | File | Mô tả | Verification |
|---|---|---|---|
| 1 | `tools/search/models.py` | `SearchQuery`, `ScoredProduct`, `SearchResult` dataclasses | Pytest import |
| 2 | `tools/search/query_analyzer.py` | Regex phase: price, category, sort patterns + tests | `pytest -k query_analyzer` |
| 3 | `tools/search/synonym_cache.py` | Seed map + `expand()` method | Test với 10 query VN mẫu |
| 4 | `tools/search/strategies.py` | `FullCatalogStrategy` (in-memory filter + score) | Verify filter đúng catalog thật |
| 5 | `tools/search/ranker.py` | `ResultRanker.merge_and_rank()` | Test dedup + rescore |

### Phase 2 — Orchestrator (Buổi 2-3)

| Bước | File | Mô tả | Verification |
|---|---|---|---|
| 6 | `tools/search/orchestrator.py` | `SearchOrchestrator` với parallel strategies | End-to-end test |
| 7 | `tools/search/__init__.py` | Export `search_products_v2` (LangChain tool wrapper) | Agent gọi được |
| 8 | `tools/search/strategies.py` | `DirectDBStrategy` (gRPC variants) | Test với port-forward |
| 9 | `tools/search/cache.py` | Empty result cache, LLM parse cache | Hit/miss test |

### Phase 3 — LLM Integration (Buổi 3-4)

| Bước | File | Mô tả | Verification |
|---|---|---|---|
| 10 | `tools/search/query_analyzer.py` | LLM parse phase (fallback) + cache | Test query phức tạp |
| 11 | `tools/search/reranker.py` | `LLMReranker` (conditional) | Test multi-intent query |
| 12 | `tools/search/synonym_cache.py` | `_llm_translate_batch` (tự học) | Test từ mới |

### Phase 4 — Integration (Buổi 4-5)

| Bước | File | Mô tả | Verification |
|---|---|---|---|
| 13 | `tools/__init__.py` | Thay `search_products_tool` → `search_products_v2` | Agent dùng tool mới |
| 14 | `agent/prompts.py` | Cập nhật mô tả tool + system prompt | LLM biết dùng search V2 |
| 15 | `memory/store.py` | Thêm session empty cache | Session test |
| 16 | `tests/test_search.py` | Write integration tests | `pytest tests/test_search.py -v` |

### Phase 5 — Seed & Tune (Buổi 5)

| Bước | Mô tả | Verification |
|---|---|---|
| 17 | Chạy seed synonym cache bằng LLM 1 lần | Review mapping output |
| 18 | Test với 20 query VN mẫu thực tế | Hit rate > 80% |
| 19 | Tune score weights nếu cần | Precision/recall OK |

---

## 9. Chi phí vận hành

### 9.1 Chi phí một lần

| Item | Tokens | Model | Cost |
|---|---|---|---|
| Seed synonym cache | ~800 | 8b-instant | ~$0.00004 |
| Seed catalog tag (option) | ~2000 | 8b-instant | ~$0.00010 |
| **Total one-time** | | | **~$0.00014** |

### 9.2 Chi phí vận hành mỗi query

| Path | LLM calls | Tokens | Cost | Latency |
|---|---|---|---|---|
| **Regex-only** (query đơn giản, cache hit) | 0 | 0 | **$0** | <50ms |
| **Regex + strategy** (thường gặp) | 0 | 0 | **$0** | ~200ms |
| **Regex + LLM parse miss** (query mới) | 1 (8b, cached 24h) | ~100 | ~$0.000005 | ~500ms |
| **Regex + synonym miss** (từ mới) | 1 (8b, cached ∞) | ~150 | ~$0.000008 | ~500ms |
| **Regex + strategy + rerank** (query phức tạp) | 2 (parse + rerank) | ~300 | ~$0.000015 | ~1.2s |
| **Worst case** (cache hoàn toàn miss) | 3 | ~500 | ~$0.000025 | ~2s |

### 9.3 Dự kiến sau warm-up

Giả sử 1000 query/ngày, với hit rate 85% cho LLM parse cache, 70% cho synonym cache:

| Loại | % query | Giá/query | Cost/ngày |
|---|---|---|---|
| Regex-only (simple) | 40% | $0 | $0 |
| Regex + cache hit | 45% | $0 | $0 |
| LLM parse miss | 10% | $0.000005 | $0.0005 |
| Synonym miss | 4% | $0.000008 | $0.00032 |
| Worst case (rerank) | 1% | $0.000015 | $0.00015 |
| **Total** | **100%** | | **~$0.001/ngày** |

---

## 10. Definition of Done

| # | Kiểm tra | Phương pháp verify |
|---|---|---|
| 1 | Regex parse bắt được price (`dưới 50 đô`, `từ 100-200 USD`) | `pytest -k test_regex_price` |
| 2 | Regex parse bắt được category (`kính thiên văn`, `ống nhòm`) | `pytest -k test_regex_category` |
| 3 | FullCatalogStrategy filter đúng price range | `pytest -k test_full_catalog_price` |
| 4 | FullCatalogStrategy filter đúng category | `pytest -k test_full_catalog_category` |
| 5 | DirectDBStrategy gọi gRPC variant thành công | Integration test với port-forward |
| 6 | SynonymCache expand VN→EN đúng 10 mẫu | `pytest -k test_synonym_basic` |
| 7 | SynonymCache tự học từ mới qua LLM | `pytest -k test_synonym_llm_learn` |
| 8 | Orcherstator merge + dedup không trùng product_id | `pytest -k test_merge_dedup` |
| 9 | Rerank chỉ chạy khi pool > 5 và query phức tạp | `pytest -k test_rerank_conditional` |
| 10 | Empty result được cache ở session level | `pytest -k test_empty_cache` |
| 11 | LLM parse result cache 24h hoạt động | `pytest -k test_llm_parse_cache` |
| 12 | Agent gọi được `search_products_v2` thay vì tool cũ | Integration test với agent |
| 13 | Search VN trả về grounded kết quả từ catalog thật | Manual test 10 query mẫu |
| 14 | `search_products_tool` cũ vẫn hoạt động (fallback) | `pytest -k test_legacy_tool` |
| 15 | P95 latency < 2s cho query phức tạp | Load test 50 query |
| 16 | Chi phí trung bình < $0.00001/query | Tính từ log latency + LLM tokens |

---

> **Tác giả:** AIO02 — TF3 | **Ngày:** 2026-07-10  
> **Tham chiếu:** `agentic_design.md`, `spec/flow.md`  
> Cập nhật tài liệu này khi có thay đổi kiến trúc hoặc thêm strategy mới.
