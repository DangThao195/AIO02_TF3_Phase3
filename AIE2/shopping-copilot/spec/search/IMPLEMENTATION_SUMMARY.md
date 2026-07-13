# 📋 Implementation Summary: Multi-Strategy Search v2

**Ngày**: 2026-07-10  
**Đội**: AIO02 — TF3  
**Status**: ✅ Implementation complete (Phase 1-2)

---

## Tóm tắt

Thay thế `search_products_tool` cũ (gRPC LIKE query) bằng `search_products_v2` (multi-strategy orchestrator) hỗ trợ tìm kiếm thông minh tiếng Việt/Anh.

## Vấn đề cũ

❌ `search_products_tool` chỉ dùng LIKE %query%
- Query tiếng Việt "kính thiên văn" → 0 kết quả (tên sản phẩm tiếng Anh)
- Không hỗ trợ filter giá tự động ("dưới 100 đô")
- Không có ranking thông minh

## Giải pháp mới

✅ `search_products_v2` với 3 strategies chạy song parallel:

```
Query: "kính thiên văn dưới 100 đô"
    ↓
1. QueryAnalyzer: regex "kính thiên văn" → keywords_vn, LLM parse (fallback)
    ↓
2. Strategies chạy song song (timeout 3s):
   - FullCatalogStrategy: Load catalog, filter in-memory (FullText + regex)
   - DirectDBStrategy: gRPC SearchProducts (tên sản phẩm tiếng Anh)
   - SynonymExpansionStrategy: "kính thiên văn" → "telescope" → gRPC search
    ↓
3. ResultRanker: Merge + dedup + rule-based score
    ↓
4. LLMReranker (conditional): Reorder nếu pool > 5 + query complex
    ↓
Output: Top 15 sản phẩm xếp hạng tốt nhất
```

---

## Files tạo mới

```
tools/search/                          [MỚI] Module chính
├── __init__.py                        Export search_products_v2
├── models.py                          SearchQuery, Product, ScoredProduct, SearchResult
├── query_analyzer.py                  Regex + LLM parse query
├── strategies.py                      3 strategies: FullCatalog, DirectDB, Synonym
├── ranker.py                          Merge + rank results
├── reranker.py                        LLM rerank (conditional)
├── synonym_cache.py                   VN→EN keyword mapping
├── cache.py                           Empty result cache
├── orchestrator.py                    Main orchestrator + search_products_v2 tool
├── examples.py                        Example usage
└── README.md                          Documentation

tools/search/README.md                 [MỚI] Module docs
MIGRATION_GUIDE.md                     [MỚI] Migration từ tool cũ
```

## Files sửa

```
tools/catalog_tool.py                  [SỬA] Thêm deprecated warning ở search_products_tool
tools/__init__.py                      [SỬA] Thêm import search_products_v2
tests/test_search_integration.py       [MỚI] Unit tests cho models + regex + synonym
```

---

## Kiến trúc chi tiết

### Phase 1: Query Analyzer

**Regex parser** (cost $0, latency <1ms)
- Tách price: `dưới 50`, `từ 100-200`, `trên 75` → price_min, price_max
- Tách category: `kính thiên văn`, `ống nhòm`, `sách` → category slug
- Tách sort: `rẻ nhất`, `đắt nhất` → sort order
- Tách keywords: Loại stop words, phân loại VN vs EN

**LLM parse** (fallback, cost ~$0.000005, cached 24h)
- Chỉ chạy khi regex không bắt category hoặc query phức tạp
- Dùng Groq 8b-instant (model nhỏ, rẻ)
- Cache hit rate dự kiến >80% sau warm-up

### Phase 2: Search Strategies (song parallel)

**Strategy A: FullCatalogStrategy**
- Load ListProducts → cache 5 phút
- Filter in-memory: regex + fuzzy match
- Score theo weights: exact match (100), keyword in name (50), category (30), etc.

**Strategy B: DirectDBStrategy**
- Build query variants (raw, category, keywords)
- gRPC SearchProducts (DB LIKE)
- Base score 30-60

**Strategy C: SynonymExpansionStrategy**
- Expand VN keywords via SynonymCache
- gRPC SearchProducts với EN keywords
- Base score 35

### Phase 3: Result Merger & Ranker

- **Dedup**: Giữ product_id cao score nhất
- **Rule-based score**: Xếp hạng theo relevance/price
- **Top K**: Lấy top 15

### Phase 4: LLM Rerank (conditional)

Chỉ chạy khi:
- Pool > 5 sản phẩm
- Query phức tạp (multi-intent) hoặc is_complex = True

Dùng LLM để reorder top K theo intent người dùng.

---

## Scoring Weights

```
Exact name match:      100
Keyword in name:       50 (per keyword)
Keyword in category:   30 (per keyword)
Keyword in description: 20 (per keyword)
Fuzzy match (>80%):    40
Category match:        60

Adjustments:
- Price outside range: -1 (discard)
- Price proximity:     +10
- Category match:      +5
```

---

## Cache Strategy

| Layer | TTL | Scope | Hit rate (dự kiến) |
|-------|-----|-------|------------------|
| Full catalog | 300s (5m) | Global | 95% |
| LLM parse | 86400s (24h) | Global (hash) | 80-85% |
| Synonym map | ∞ (persistent) | Global | 70% (tự học) |
| Empty result | 1800s (session) | Session | 50% (reduce LLM rerank) |

---

## Chi phí vận hành (Warm-up)

### Cost per query (sau 1000 queries)

| Path | Frequency | Cost/query | Cost/1000q |
|------|-----------|-----------|-----------|
| Regex-only | 40% | $0 | $0 |
| Cache hit | 45% | $0 | $0 |
| LLM parse miss | 10% | $0.000005 | $0.005 |
| Synonym miss | 4% | $0.000008 | $0.032 |
| LLM rerank | 1% | $0.000015 | $0.015 |
| **TOTAL** | **100%** | | **~$0.05/1000q** |

**Dự kiến**: ~$0.001/ngày (1000q/day)

---

## Testing

### Unit tests (offline)

```bash
# Test regex parser
pytest tests/test_search_integration.py::TestQueryAnalyzer -v

# Test synonym cache
pytest tests/test_search_integration.py::TestSynonymCache -v

# Test models
pytest tests/test_search_integration.py::TestSearchModels -v
```

### Integration tests (online, cần gRPC)

```bash
# Run examples (xem actual search results)
python -m tools.search.examples
```

---

## Migration Path

### Immediate (ngay lập tức)
1. ✅ Deploy tất cả files
2. ✅ Cập nhật `tools/__init__.py` (export search_products_v2)
3. ✅ Deprecate `search_products_tool` (thêm warning)

### Week 1 (phase deploy)
- [ ] Verify search_products_v2 hoạt động với real catalog data
- [ ] Tune scoring weights nếu cần
- [ ] Monitor cost (expect ~$0.001/day)

### Week 2 (stabilize)
- [ ] Collect user feedback trên query VN
- [ ] Tự học synonym từ user behavior (optional)
- [ ] Decommission search_products_tool (optional)

---

## Definition of Done (DoD)

| # | Task | Status |
|---|------|--------|
| 1 | Regex parse price (dưới, từ-đến, trên) | ✅ |
| 2 | Regex parse category (telescopes, binoculars, etc.) | ✅ |
| 3 | FullCatalogStrategy in-memory filter | ✅ |
| 4 | DirectDBStrategy gRPC wrapper | ✅ |
| 5 | SynonymExpansionStrategy VN→EN | ✅ |
| 6 | ResultRanker merge + dedup + score | ✅ |
| 7 | SearchOrchestrator parallel execution | ✅ |
| 8 | LLMReranker conditional (pool > 5) | ✅ |
| 9 | search_products_v2 LangChain tool | ✅ |
| 10 | Unit tests (offline) | ✅ |
| 11 | Examples + docs | ✅ |
| 12 | Integration tests (online) | ⏳ (pending verify) |

---

## Known Issues & Limitations

1. **gRPC ListProducts latency**: Nếu catalog > 1000 products, load time có thể chậm
   - **Mitigation**: Cache 5 phút, in-memory filter

2. **LLM parse outdated responses**: Nếu catalog update, cache 24h không refresh
   - **Mitigation**: Call `cache.refresh()` khi catalog update, hoặc manual invalidate

3. **Synonym cache incomplete**: Khi gặp từ mới VN, phải gọi LLM 1 lần
   - **Mitigation**: Seed cache comprehensively ở deploy time, hoặc tự học

4. **LLM rerank ngoài thời gian real-time**: Timeout 3s chỉ cho strategies, rerank chạy tuần tự
   - **Mitigation**: LLM rerank chỉ chạy conditional (pool > 5 + complex), dự kiến <0.5s

---

## Next Steps

### Validation Phase
- [ ] Load test: 100 queries/sec → verify latency <2s
- [ ] Accuracy test: So sánh search results với expectation
- [ ] Cost monitoring: Track LLM token usage daily

### Optimization Phase (optional)
- [ ] Semantic search fallback (embedding model)
- [ ] A/B test scoring weights
- [ ] Auto-tag products (category, keywords)
- [ ] User behavior learning (synonym auto-expand)

### Deprecation Phase
- [ ] Remove search_products_tool sau 2-4 tuần
- [ ] Document breaking changes

---

## Support & Contact

**Questions?** Liên hệ AIO02 team (TF3 Phase 3)

**Documentation**:
- [tools/search/README.md](tools/search/README.md) — Module docs
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) — Migration từ tool cũ
- [search_design.md](shopping-copilot/spec/search_design.md) — Thiết kế chi tiết

---

**Implementation by**: Claude Code (GitHub Copilot)  
**Date**: 2026-07-10  
**Version**: 1.0.0 (Phase 1-2 complete)
