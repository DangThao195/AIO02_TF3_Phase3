# tools/search/README.md

# Multi-Strategy Search Module

Mô-đun tìm kiếm thông minh cho storefront với hỗ trợ **tiếng Việt + tiếng Anh**, sử dụng kiến trúc multi-strategy không cần vector database.

## Tóm tắt kiến trúc

```
Input Query (Tiếng Việt/Anh)
    ↓
┌─────────────────────────────┐
│ Phase 1: Query Analyzer     │
│ - Regex parse (price, sort) │
│ - LLM fallback (category)   │
└────────────┬────────────────┘
             ↓
      SearchQuery object
             ↓
┌─────────────────────────────────────────────┐
│ Phase 2: Strategy Orchestrator (song song) │
│                                             │
│ ┌──────────────┐  ┌──────────┐  ┌────────┐│
│ │Full Catalog  │  │Direct DB │  │Synonym││
│ │In-memory     │  │gRPC      │  │Expand ││
│ │Filter        │  │          │  │VN→EN  ││
│ └──────────────┘  └──────────┘  └────────┘│
└────────────┬────────────────────────────────┘
             ↓
      Pools merged
             ↓
┌─────────────────────────────┐
│ Phase 3: Merge & Rank       │
│ - Dedup (product_id)        │
│ - Rule-based score          │
│ - Sort by relevance/price   │
└────────────┬────────────────┘
             ↓
      Top K results
             ↓
┌─────────────────────────────┐
│ Phase 4: LLM Rerank         │
│ (conditional, pool > 5)     │
└────────────┬────────────────┘
             ↓
      Final results → LLM
```

## File Structure

```
tools/search/
├── __init__.py              # Export search_products_v2
├── models.py                # SearchQuery, Product, ScoredProduct, SearchResult
├── query_analyzer.py        # Regex + LLM parse
├── strategies.py            # 3 strategies: FullCatalog, DirectDB, SynonymExpansion
├── ranker.py                # Merge + dedup + rule-based rank
├── reranker.py              # LLM rerank (conditional)
├── synonym_cache.py         # VN→EN keyword mapping
├── cache.py                 # Search cache logic (empty result cache)
├── orchestrator.py          # Main orchestrator + search_products_v2 tool
└── README.md                # This file
```

## Cách dùng

### 1. Import tool

```python
from tools import search_products_v2

# Dùng trong LangChain agent
agent_tools = [search_products_v2, ...]
```

### 2. Gọi tool

```python
# Synchronous wrapper (trong LangChain)
result = search_products_v2.invoke({"query": "kính thiên văn dưới 100 đô"})
print(result)
```

### 3. Ví dụ queries

- **Tiếng Việt**: "kính thiên văn rẻ nhất", "ống nhòm từ 50-100 đô", "sách về sao chổi"
- **Tiếng Anh**: "cheapest telescope", "binoculars under 50 dollars", "comet book"
- **Mixed**: "solar filter rẻ nhất", "book about telescopes"

## Chi tiết các Strategy

### Strategy A: FullCatalogStrategy
- **Khi**: Luôn chạy
- **Làm gì**: Load toàn bộ catalog, filter in-memory
- **Cost**: $0 (cache 5 phút)
- **Ưu điểm**: Cực nhanh, toàn bộ dữ liệu

### Strategy B: DirectDBStrategy
- **Khi**: Luôn chạy
- **Làm gì**: Gọi gRPC SearchProducts với nhiều query variant
- **Cost**: $0 (DB call)
- **Ưu điểm**: Tìm exact match, fallback cho query phức tạp

### Strategy C: SynonymExpansionStrategy
- **Khi**: Query có từ khoá tiếng Việt
- **Làm gì**: Dịch VN→EN (cache vĩnh viễn), search EN keywords
- **Cost**: ~$0.000008 (LLM translate, 1 lần cache miss)
- **Ưu điểm**: Giải quyết "kính thiên văn" → "telescope"

## Scoring Rules

**Weights**:
- Exact name match: 100
- Keyword in name: 50 (mỗi keyword)
- Keyword in category: 30 (mỗi keyword)
- Keyword in description: 20 (mỗi keyword)
- Fuzzy name match (>80%): 40
- Category match: 60

**Adjustments**:
- Price > max: discard (-1)
- Price < min: discard (-1)
- Price proximity bonus: +10
- Category match bonus: +5

## Cache Strategy

| Layer | TTL | Scope |
|-------|-----|-------|
| Full catalog | 300s | Global |
| LLM parse | 86400s (24h) | Global, by query hash |
| Synonym map | ∞ | Global, persistent |
| Empty result | 1800s (session) | Session-level |

## Chi phí vận hành (dự kiến)

Với 1000 query/ngày sau warm-up:

- Regex-only: **$0**
- LLM parse cache hit: **$0**
- LLM parse miss (10%): **$0.000005**
- Synonym miss (4%): **$0.000008**
- LLM rerank (1%): **$0.000015**
- **Total/ngày**: ~**$0.001**

## Debugging

### Enable verbose logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
# Sẽ thấy: "Strategy X: Y results", "LLM parse: ...", etc.
```

### Test từng strategy riêng lẻ

```python
from tools.search.strategies import FullCatalogStrategy
from tools.search.query_analyzer import QueryAnalyzerPipeline

analyzer = QueryAnalyzerPipeline()
sq = analyzer.parse("kính thiên văn dưới 100")

strategy = FullCatalogStrategy()
results = await strategy.search(sq)
print(f"Found {len(results)} products")
for r in results:
    print(f"  - {r.product.name}: score={r.score}")
```

### Inspect merged results

```python
from tools.search.ranker import ResultRanker

ranker = ResultRanker()
merged = ranker.merge_and_rank([pool_a, pool_b, pool_c], sq)
print(f"Merged {len(merged)} unique products")
```

## Troubleshooting

### Không tìm được sản phẩm

1. **Kiểm tra regex parse**: In ra `SearchQuery` để xem category/keywords
   ```python
   analyzer = QueryAnalyzerPipeline()
   sq = analyzer.parse("query của tôi")
   print(f"Categories: {sq.category}, Keywords EN: {sq.keywords_en}, VN: {sq.keywords_vn}")
   ```

2. **Kiểm tra strategy output**: Chạy từng strategy riêng lẻ

3. **Kiểm tra synonym cache**: 
   ```python
   from tools.search.synonym_cache import SynonymCache
   cache = SynonymCache()
   print(cache.get_map())
   ```

### Performance chậm

- Kiểm tra gRPC latency: `DirectDBStrategy` timeout = 3s
- Kiểm tra full catalog cache: Có cache hit không?
- Nếu LLM rerank chạy: Có kích hoạt điều kiện `pool > 5` không?

### LLM parse sai intent

Cập nhật `QueryAnalyzerPipeline.llm_parse_cached()` với custom prompt nếu cần.

## Tương lai

- [ ] Semantic search fallback (nếu có budget embedding)
- [ ] A/B test scoring weights
- [ ] Tự học synonym từ user behavior
- [ ] Product tagging cho filter nhanh hơn

## Liên hệ

Mô-đun này là phần của AI Shopping Copilot (AIO02) — TF3 Phase 3.
