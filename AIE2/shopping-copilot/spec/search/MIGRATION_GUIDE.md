# MIGRATION_GUIDE.md

# 🔄 Migration Guide: search_products_tool → search_products_v2

## Tóm tắt

Nếu bạn đang dùng `search_products_tool` cũ, hãy chuyển sang `search_products_v2` ngay lập tức.

**Tại sao?**
- ✅ Hỗ trợ tiếng Việt hoàn toàn
- ✅ Chạy nhanh hơn (3 strategy song parallel)
- ✅ Xếp hạng thông minh hơn (LLM rerank optional)
- ✅ Chi phí thấp (~$0.001/ngày)

## Thay đổi trong code

### Trước (cũ)

```python
from tools import search_products_tool

# Dùng trong LangChain agent
all_tools = [search_products_tool, ...]

# Query chỉ hoạt động với tiếng Anh
# "kính thiên văn" → 0 results
# "telescope" → OK
```

### Sau (mới)

```python
from tools import search_products_v2

# Dùng trong LangChain agent
all_tools = [search_products_v2, ...]

# Query hoạt động với cả Việt + Anh
# "kính thiên văn" → ✅ telescope products
# "telescope" → ✅ same results
# "dưới 100 đô" → ✅ filtered by price
```

## Testing

### Unit test

```bash
pytest tests/test_search_integration.py::TestQueryAnalyzer -v
pytest tests/test_search_integration.py::TestSynonymCache -v
```

### Manual test

```python
import asyncio
from tools.search.orchestrator import SearchOrchestrator

orchestrator = SearchOrchestrator()

# Test VN query
result = asyncio.run(orchestrator.search("kính thiên văn dưới 100 đô"))
print(f"Found {len(result.products)} products")
for p in result.products[:3]:
    print(f"  - {p.product.name}: ${p.product.price_usd.units}")
```

## Checklist

- [ ] Thay import `search_products_tool` → `search_products_v2` trong `tools/__init__.py`
- [ ] Verify `tools/search/` module được install (gồm tất cả .py files)
- [ ] Chạy tests: `pytest tests/test_search_integration.py -v`
- [ ] Test manual qua agent
- [ ] Monitor cost (expect ~$0.001/1000 queries)

## Troubleshooting

### Import error: `ModuleNotFoundError: No module named 'tools.search'`

→ Đảm bảo tất cả files trong `tools/search/` đã được tạo (xem structure ở README.md)

### Empty result từ search

→ Kiểm tra:
1. Query parse: Chạy `RegexQueryAnalyzer().parse(query)` để xem keywords
2. Strategy output: Chạy từng strategy riêng lẻ (xem debug section ở README)
3. Synonym cache: In `SynonymCache().get_map()` để xem mappings

### LLM parse fail (SyntaxError)

→ Cập nhật LLM prompt ở `QueryAnalyzerPipeline._llm_parse_cached()` nếu LLM trả JSON không hợp lệ

### Performance chậm

→ Kiểm tra:
- Có cache hit không? (Full catalog: 5 phút, LLM parse: 24h)
- Strategy timeout: 3 giây
- Nếu LLM rerank chạy: Có query complexity cao không? (pool > 5 AND is_complex)

## Notes

- Tool cũ `search_products_tool` được giữ lại cho backward compatibility nhưng đã deprecated
- Không recommend dùng cùng lúc `search_products_tool` + `search_products_v2` (sẽ confuse agent)
- Session-level empty result cache giúp tránh duplicate LLM calls trong cùng 1 session

## Rollback

Nếu cần quay lại tool cũ:

```python
from tools import search_products_tool  # Không recommend

all_tools = [search_products_tool, ...]
```

## Support

Liên hệ AIO02 team nếu có issue.
