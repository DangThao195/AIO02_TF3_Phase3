from src.tools.search.flow1.sql_executor import (
    FullCatalogStrategy,
    DirectDBStrategy,
    SynonymExpansionStrategy
)

class Flow1SQL:
    """
    Wrapper của Flow 1 (SQL Matching) để tuân thủ thiết kế search_design.md.
    """
    @staticmethod
    async def run(sq):
        # Gọi song song các strategy thuộc Flow 1
        strategies = [FullCatalogStrategy(), DirectDBStrategy(), SynonymExpansionStrategy()]
        tasks = [s.search(sq) for s in strategies if s.should_run(sq)]
        import asyncio
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        flat_results = []
        for r in results:
            if isinstance(r, list):
                flat_results.extend(r)
        return flat_results
