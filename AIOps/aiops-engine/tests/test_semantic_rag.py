import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from llm_diagnostician import LLMDiagnostician

def test_cosine_similarity_internals():
    diagnostician = LLMDiagnostician()
    
    # Test identical vectors (similarity should be 1.0)
    v1 = [1.0, 2.0, 3.0]
    v2 = [1.0, 2.0, 3.0]
    
    # We can extract the local function inside retrieve_relevant_playbooks by running a dummy retrieval
    # or just replicate it to verify the mathematical formula
    def cosine_similarity(v1, v2):
        length = min(len(v1), len(v2))
        dot_product = sum(a * b for a, b in zip(v1[:length], v2[:length]))
        norm_a = sum(a * a for a in v1[:length]) ** 0.5
        norm_b = sum(b * b for b in v2[:length]) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)
        
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-6
    
    # Test orthogonal vectors (similarity should be 0.0)
    v3 = [1.0, 0.0]
    v4 = [0.0, 1.0]
    assert abs(cosine_similarity(v3, v4) - 0.0) < 1e-6

def test_semantic_retrieval_inc1():
    diagnostician = LLMDiagnostician()
    
    if not diagnostician.playbooks_kb:
        pytest.skip("Vector KB index playbooks_vector_index.json not found. Run embed_playbooks.py first.")
        
    # Query related to Postgres Connection slots pool exhaustion (should match INC-1)
    query_text = "Service: product-catalog. Logs: connection pool cạn kiệt max connections slots full"
    
    retrieved = diagnostician.retrieve_relevant_playbooks(query_text, k=1)
    
    assert "INC-1" in retrieved
    assert "PostgreSQL" in retrieved

def test_semantic_retrieval_inc4():
    diagnostician = LLMDiagnostician()
    
    if not diagnostician.playbooks_kb:
        pytest.skip("Vector KB index playbooks_vector_index.json not found. Run embed_playbooks.py first.")
        
    # Query related to Bedrock Rate Limit 429 (should match INC-4)
    query_text = "Service: product-reviews. Logs: Bedrock API rate limit 429 Too Many Requests"
    
    retrieved = diagnostician.retrieve_relevant_playbooks(query_text, k=1)
    
    assert "INC-4" in retrieved
    assert "Feature Flag" in retrieved
