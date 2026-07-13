#!/usr/bin/env python
"""
End-to-end test cho search_products_v2 với real gRPC service + LLM.

Setup trước khi chạy:
1. Set GROQ_API_KEY:
   $env:GROQ_API_KEY="gsk_..."
   
2. Setup port-forward (nếu product-catalog trên EKS):
   kubectl port-forward svc/product-catalog 3550:3550
   
3. Chạy test:
   python tools/search/test_e2e.py "kính thiên văn dưới 100 đô"

"""

import sys
import os
import asyncio
import logging
from typing import Optional
from pathlib import Path

# Add parent directory to path for imports
shopping_copilot_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(shopping_copilot_root))

# Load .env file
from dotenv import load_dotenv
load_dotenv()

# Setup logging chi tiết
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger("test_e2e")


class E2ETestRunner:
    """End-to-end test runner kết nối gRPC + LLM."""

    def __init__(self):
        """Initialize runner."""
        self.api_key = os.getenv("GROQ_API_KEY")
        self.catalog_addr = os.getenv("PRODUCT_CATALOG_ADDR", "localhost:3550")
        self.has_api_key = bool(self.api_key)
        
        logger.info("=" * 80)
        logger.info("END-TO-END TEST: search_products_v2")
        logger.info("=" * 80)
        logger.info(f"GROQ_API_KEY: {'✅ SET' if self.has_api_key else '❌ NOT SET'}")
        logger.info(f"Product Catalog: {self.catalog_addr}")
        logger.info("=" * 80)

    async def test_search_e2e(self, query: str):
        """
        Test search end-to-end: query parse → gRPC call → results.
        
        Args:
            query: Raw user query (tiếng Việt hoặc Anh)
        """
        logger.info("\n" + "=" * 80)
        logger.info(f"QUERY: {query}")
        logger.info("=" * 80)
        
        # Phase 1: Query parsing
        logger.info("\n[Phase 1] QUERY PARSING")
        from tools.search.query_analyzer import QueryAnalyzerPipeline
        
        pipeline = QueryAnalyzerPipeline()
        sq = pipeline.parse(query)
        
        logger.info(f"  ✓ Category: {sq.category}")
        logger.info(f"  ✓ Keywords EN: {sq.keywords_en}")
        logger.info(f"  ✓ Keywords VN: {sq.keywords_vn}")
        logger.info(f"  ✓ Price: ${sq.price_min or 0} - ${sq.price_max or '∞'}")
        logger.info(f"  ✓ Sort: {sq.sort}")
        logger.info(f"  ✓ Intent: {sq.intent}")
        logger.info(f"  ✓ Is Complex: {sq.is_complex}")
        
        # Phase 2: Synonym expansion
        logger.info("\n[Phase 2] SYNONYM EXPANSION")
        from tools.search.synonym_cache import SynonymCache
        
        cache = SynonymCache()
        en_keywords = cache.expand(sq.keywords_vn)
        logger.info(f"  ✓ Expanded keywords: {en_keywords}")
        
        # Phase 3: Search strategies
        logger.info("\n[Phase 3] SEARCH STRATEGIES")
        from tools.search.orchestrator import SearchOrchestrator
        
        orchestrator = SearchOrchestrator()
        try:
            result = await orchestrator.search(query)
            
            logger.info(f"  ✓ Strategies used: {result.strategies_used}")
            logger.info(f"  ✓ Found {len(result.products)} products")
            
            if result.products:
                logger.info(f"\n[Phase 4] TOP RESULTS")
                for i, scored_product in enumerate(result.products[:5], 1):
                    p = scored_product.product
                    score = scored_product.score
                    strategy = scored_product.strategy_name
                    logger.info(f"  {i}. [{score:6.1f}] {p.name}")
                    logger.info(f"     Price: ${p.price_usd.units}.{p.price_usd.nanos:09d} | Category: {p.categories}")
                    logger.info(f"     Strategy: {strategy}")
            else:
                logger.warning(f"  ⚠️  No products found")
                if result.error:
                    logger.error(f"  Error: {result.error}")
                    
        except Exception as e:
            logger.error(f"❌ Search failed: {e}", exc_info=True)
            
            # Fallback: show parse result
            logger.info("\n[Fallback] SHOWING PARSE RESULT")
            logger.info(f"  Query parse successful, but gRPC call failed.")
            logger.info(f"  Category: {sq.category}")
            logger.info(f"  Price filter: ${sq.price_min or 0} - ${sq.price_max or '∞'}")

    async def test_batch(self, queries: list[str]):
        """Test multiple queries."""
        logger.info("\n" + "=" * 80)
        logger.info("BATCH TEST MODE")
        logger.info("=" * 80)
        
        for i, query in enumerate(queries, 1):
            logger.info(f"\n{'='*80}")
            logger.info(f"TEST {i}/{len(queries)}")
            logger.info(f"{'='*80}")
            
            await self.test_search_e2e(query)

    def print_setup_instructions(self):
        """Print setup instructions."""
        logger.info("\n" + "=" * 80)
        logger.info("📋 SETUP INSTRUCTIONS")
        logger.info("=" * 80)
        
        if not self.has_api_key:
            logger.warning("\n❌ GROQ_API_KEY not set!")
            logger.info("\nTo set API key:")
            logger.info("  1. Get from: https://console.groq.com/keys")
            logger.info("  2. Set in PowerShell:")
            logger.info("     $env:GROQ_API_KEY='gsk_your_key'")
            logger.info("  3. Or create .env file with GROQ_API_KEY=...")
            logger.info("  4. Re-run this script")
        else:
            logger.info("\n✅ GROQ_API_KEY found")
        
        logger.info(f"\nTo connect to product-catalog on EKS:")
        logger.info("  kubectl port-forward svc/product-catalog 3550:3550")
        logger.info(f"\nThen test with:")
        logger.info("  python tools/search/test_e2e.py \"kính thiên văn dưới 100 đô\"")


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="End-to-end test for search_products_v2",
        epilog="""
Examples:
  python tools/search/test_e2e.py "kính thiên văn"
  python tools/search/test_e2e.py "dưới 100 đô"
  python tools/search/test_e2e.py "ống nhòm rẻ nhất"
        """
    )
    parser.add_argument("queries", nargs="*", help="Query/queries to test")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run batch test with predefined queries"
    )
    
    args = parser.parse_args()
    
    runner = E2ETestRunner()
    
    # Default batch queries
    batch_queries = [
        "kính thiên văn",
        "kính thiên văn dưới 100 đô",
        "ống nhòm rẻ nhất",
        "sách từ 20 đến 50 đô",
        "đèn pin",
        "telescope dưới 500",
    ]
    
    try:
        if args.batch:
            await runner.test_batch(batch_queries)
        elif args.queries:
            await runner.test_batch(args.queries)
        else:
            runner.print_setup_instructions()
            
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
