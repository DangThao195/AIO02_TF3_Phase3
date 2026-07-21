#!/usr/bin/env python
"""
Interactive test tool cho search_products_v2.
Chạy bằng: python tools/search/test_interactive.py

Hỗ trợ hai mode:
1. MOCK: Không cần GROQ_API_KEY (test regex + synonym + logic)
2. REAL: Với GROQ_API_KEY (test với LLM thật)
"""

import sys
import os
import logging
from typing import Optional

# Setup logging chi tiết
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger("test_interactive")

# Test queries (tiếng Việt thật)
TEST_QUERIES = [
    # Đơn giản
    "kính thiên văn",
    "ống nhòm",
    "sách",
    
    # Với giá
    "kính thiên văn dưới 100 đô",
    "từ 50 đến 200 đô",
    "sách rẻ nhất",
    
    # Phức tạp
    "tôi muốn mua kính thiên văn chất lượng cao dưới 500 đô, rẻ nhất",
    "tìm cho tôi ống nhòm từ 200 đến 500 đô",
    
    # Không có category
    "cái tốt mà rẻ",
    "sản phẩm mới",
]


class TestRunner:
    """Interactive test runner cho search module."""

    def __init__(self, mock: bool = True):
        """
        Args:
            mock: Nếu True, dùng mock LLM (không cần API key)
                  Nếu False, dùng Groq thật (cần GROQ_API_KEY)
        """
        self.mock = mock
        self._setup_mode()

    def _setup_mode(self):
        """Setup mock hay real mode."""
        api_key = os.getenv("GROQ_API_KEY")
        
        if self.mock or not api_key:
            logger.info("=" * 80)
            logger.info("MODE: MOCK (không cần API key)")
            logger.info("=" * 80)
            self.mode = "mock"
        else:
            logger.info("=" * 80)
            logger.info("MODE: REAL (với GROQ_API_KEY)")
            logger.info("=" * 80)
            self.mode = "real"

    def test_regex_parsing(self):
        """Test regex query parsing (không cần LLM)."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 1: REGEX QUERY PARSING")
        logger.info("=" * 80)
        
        from tools.search.query_analyzer import RegexQueryAnalyzer
        
        analyzer = RegexQueryAnalyzer()
        
        test_cases = [
            ("kính thiên văn", "Should detect category=telescopes"),
            ("dưới 100 đô", "Should parse price_max=100"),
            ("từ 50 đến 200 đô", "Should parse price_min=50, price_max=200"),
            ("rẻ nhất", "Should detect sort=price_asc"),
            ("đắt nhất", "Should detect sort=price_desc"),
        ]
        
        for query, description in test_cases:
            logger.info(f"\n[Query] {query}")
            logger.info(f"[Expect] {description}")
            
            sq = analyzer.parse(query)
            logger.info(f"[Result]")
            logger.info(f"  - category: {sq.category}")
            logger.info(f"  - price_min: {sq.price_min}")
            logger.info(f"  - price_max: {sq.price_max}")
            logger.info(f"  - sort: {sq.sort}")
            logger.info(f"  - keywords_vn: {sq.keywords_vn}")
            logger.info(f"  - is_complex: {sq.is_complex}")

    def test_synonym_expansion(self):
        """Test Vietnamese→English synonym expansion."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 2: SYNONYM EXPANSION")
        logger.info("=" * 80)
        
        from tools.search.synonym_cache import SynonymCache
        
        cache = SynonymCache()
        
        test_keywords = [
            (["kính thiên văn"], "Should expand to telescope"),
            (["ống nhòm"], "Should expand to binoculars"),
            (["sách"], "Should expand to book"),
            (["đèn pin"], "Should expand to flashlight"),
        ]
        
        for vn_keywords, description in test_keywords:
            logger.info(f"\n[Keywords VN] {vn_keywords}")
            logger.info(f"[Expect] {description}")
            
            en_keywords = cache.expand(vn_keywords)
            logger.info(f"[Result] {en_keywords}")

    def test_query_pipeline(self):
        """Test full query analysis pipeline."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 3: QUERY ANALYSIS PIPELINE")
        logger.info("=" * 80)
        
        from tools.search.query_analyzer import QueryAnalyzerPipeline
        
        pipeline = QueryAnalyzerPipeline()
        
        # In mock mode, set LLM to mock để tránh real API call
        if self.mode == "mock":
            from llm.llm import MockLLMClient
            pipeline.llm = MockLLMClient()
        
        queries = [
            "kính thiên văn dưới 100 đô",
            "tôi muốn mua ống nhòm rẻ nhất",
            "sách từ 20 đến 50 đô",
        ]
        
        for query in queries:
            logger.info(f"\n[Raw Query] {query}")
            logger.info(f"[Mode] {self.mode}")
            
            sq = pipeline.parse(query)
            
            logger.info(f"[Parsed Query]")
            logger.info(f"  - category: {sq.category}")
            logger.info(f"  - keywords_en: {sq.keywords_en}")
            logger.info(f"  - keywords_vn: {sq.keywords_vn}")
            logger.info(f"  - price_min: {sq.price_min}")
            logger.info(f"  - price_max: {sq.price_max}")
            logger.info(f"  - sort: {sq.sort}")
            logger.info(f"  - intent: {sq.intent}")
            logger.info(f"  - is_complex: {sq.is_complex}")

    def test_interactive(self):
        """Interactive test with user input."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 4: INTERACTIVE TEST - SUGGEST QUERIES")
        logger.info("=" * 80)
        
        logger.info("\nSuggested queries to test:")
        for i, query in enumerate(TEST_QUERIES, 1):
            logger.info(f"{i:2d}. {query}")
        
        logger.info("\n" + "=" * 80)
        logger.info("To test with your own queries, use:")
        logger.info("  from tools.search.orchestrator import SearchOrchestrator")
        logger.info("  orchestrator = SearchOrchestrator()")
        logger.info("  result = await orchestrator.search('your query here')")
        logger.info("=" * 80)

    def run_all(self):
        """Run all tests."""
        try:
            self.test_regex_parsing()
            self.test_synonym_expansion()
            self.test_query_pipeline()
            self.test_interactive()
            
            logger.info("\n" + "=" * 80)
            logger.info("✅ ALL TESTS COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ TEST FAILED: {e}", exc_info=True)
            sys.exit(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Interactive test tool for search_products_v2")
    parser.add_argument(
        "--mode",
        choices=["mock", "real"],
        default="mock",
        help="Test mode: 'mock' (no API key needed) or 'real' (needs GROQ_API_KEY)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Force mock if no API key
    api_key = os.getenv("GROQ_API_KEY")
    if args.mode == "real" and not api_key:
        logger.warning("⚠️  GROQ_API_KEY not set, switching to MOCK mode")
        args.mode = "mock"
    
    runner = TestRunner(mock=(args.mode == "mock"))
    runner.run_all()


if __name__ == "__main__":
    main()
