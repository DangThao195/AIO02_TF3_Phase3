# tools/search/examples.py
"""
Ví dụ về cách dùng multi-strategy search module.

Chạy: python -m tools.search.examples
"""

import asyncio
from tools.search.orchestrator import SearchOrchestrator
from tools.search.query_analyzer import QueryAnalyzerPipeline, RegexQueryAnalyzer
from tools.search.synonym_cache import SynonymCache


async def example_1_basic_search():
    """Ví dụ 1: Search cơ bản."""
    print("\n" + "="*60)
    print("VÍ DỤ 1: Search cơ bản")
    print("="*60)

    orchestrator = SearchOrchestrator()
    
    # Test query tiếng Anh
    print("\n🔍 Query: 'telescope'")
    result = await orchestrator.search("telescope")
    print(f"   → Tìm được {len(result.products)} sản phẩm")
    print(f"   → Strategies dùng: {result.strategies_used}")
    
    # Test query tiếng Việt
    print("\n🔍 Query: 'kính thiên văn'")
    result = await orchestrator.search("kính thiên văn")
    print(f"   → Tìm được {len(result.products)} sản phẩm")
    print(f"   → Strategies dùng: {result.strategies_used}")


async def example_2_price_filter():
    """Ví dụ 2: Search với filter giá."""
    print("\n" + "="*60)
    print("VÍ DỤ 2: Search với filter giá")
    print("="*60)

    orchestrator = SearchOrchestrator()
    
    queries = [
        "dưới 50 đô",
        "từ 100 đến 200 đô",
        "telescope under 100",
    ]
    
    for q in queries:
        print(f"\n🔍 Query: '{q}'")
        result = await orchestrator.search(q)
        print(f"   → Tìm được {len(result.products)} sản phẩm")
        if result.products:
            print(f"   → Giá: ${result.products[0].product.price_usd.units}")


async def example_3_query_parsing():
    """Ví dụ 3: Xem cách parse query."""
    print("\n" + "="*60)
    print("VÍ DỤ 3: Query parsing")
    print("="*60)

    analyzer = QueryAnalyzerPipeline()
    
    queries = [
        "kính thiên văn",
        "dưới 100 đô",
        "kính thiên văn rẻ nhất",
        "from 50 to 150 USD telescopes",
    ]
    
    for q in queries:
        sq = analyzer.parse(q)
        print(f"\n📝 Query: '{q}'")
        print(f"   Category: {sq.category}")
        print(f"   Keywords EN: {sq.keywords_en}")
        print(f"   Keywords VN: {sq.keywords_vn}")
        print(f"   Price range: ${sq.price_min} - ${sq.price_max}")
        print(f"   Sort: {sq.sort}")
        print(f"   Is complex: {sq.is_complex}")


async def example_4_synonym_expansion():
    """Ví dụ 4: VN→EN synonym mapping."""
    print("\n" + "="*60)
    print("VÍ DỤ 4: Synonym expansion")
    print("="*60)

    cache = SynonymCache()
    
    vn_keywords = ["kính thiên văn", "ống nhòm", "sách", "đèn pin"]
    print(f"\n📝 VN keywords: {vn_keywords}")
    
    en_keywords = cache.expand(vn_keywords)
    print(f"   → EN keywords: {en_keywords}")
    
    # Show map
    print(f"\n📚 Full synonym map (first 10 entries):")
    full_map = cache.get_map()
    for i, (vn, en) in enumerate(list(full_map.items())[:10]):
        print(f"   {vn:20} → {en}")


def example_5_regex_patterns():
    """Ví dụ 5: Regex pattern matching."""
    print("\n" + "="*60)
    print("VÍ DỤ 5: Regex pattern matching")
    print("="*60)

    analyzer = RegexQueryAnalyzer()
    
    # Test price patterns
    price_queries = [
        "dưới 50",
        "từ 100 đến 200",
        "trên 75",
    ]
    
    print("\n💰 Price patterns:")
    for q in price_queries:
        sq = analyzer.parse(q)
        print(f"   '{q}' → min={sq.price_min}, max={sq.price_max}")
    
    # Test category patterns
    category_queries = [
        "kính thiên văn",
        "ống nhòm",
        "đèn pin",
        "sách",
    ]
    
    print("\n🏷️  Category patterns:")
    for q in category_queries:
        sq = analyzer.parse(q)
        print(f"   '{q}' → {sq.category}")
    
    # Test sort patterns
    sort_queries = [
        "rẻ nhất",
        "đắt nhất",
        "giá thấp",
    ]
    
    print("\n📊 Sort patterns:")
    for q in sort_queries:
        sq = analyzer.parse(q)
        print(f"   '{q}' → {sq.sort}")


async def main():
    """Chạy tất cả ví dụ."""
    print("\n" + "🔬 "*20)
    print("MULTI-STRATEGY SEARCH MODULE — EXAMPLES")
    print("🔬 "*20)
    
    # Các ví dụ không cần gRPC (offline)
    print("\n⏩ Các ví dụ offline (không cần gRPC)...")
    example_5_regex_patterns()
    await example_3_query_parsing()
    await example_4_synonym_expansion()
    
    # Các ví dụ cần gRPC (online)
    print("\n⏳ Các ví dụ online (cần gRPC lên catalog service)...")
    print("   ⚠️  Đảm bảo port-forward: kubectl port-forward svc/product-catalog 3550:3550")
    try:
        await example_1_basic_search()
        await example_2_price_filter()
    except Exception as e:
        print(f"   ⚠️  Bỏ qua (gRPC không khả dụng): {e}")
    
    print("\n" + "✅ "*20)
    print("XONG!")


if __name__ == "__main__":
    asyncio.run(main())
