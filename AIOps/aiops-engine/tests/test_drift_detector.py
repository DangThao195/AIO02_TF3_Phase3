import pytest
import numpy as np
from drift_detector import DriftDetector

def test_drift_detector_stable():
    detector = DriftDetector()
    
    # Baseline stable data
    stable_data = {
        "intents": {"order_query": 40, "product_search": 30, "recommendation": 20, "chitchat": 10},
        "embeddings": [[0.15] * 32],
        "abstention_rate": 0.04,
        "fallback_rate": 0.05,
        "judge_score": 4.3
    }
    
    result = detector.detect_drift(stable_data)
    assert result["drift_detected"] is False
    assert result["drift_type"] is None

def test_drift_detector_data_drift():
    detector = DriftDetector()
    
    # Highly shifted intent distribution (PSI should be high)
    shifted_data = {
        "intents": {"order_query": 5, "product_search": 5, "recommendation": 10, "chitchat": 80},
        "embeddings": [[0.15] * 32],
        "abstention_rate": 0.04,
        "fallback_rate": 0.05,
        "judge_score": 4.3
    }
    
    result = detector.detect_drift(shifted_data)
    assert result["drift_detected"] is True
    assert result["drift_type"] == "DATA_DRIFT"

def test_drift_detector_embedding_drift():
    detector = DriftDetector()
    
    # Shifted prompt embedding centroid (high cosine distance - non-parallel vector)
    shifted_embeddings_data = {
        "intents": {"order_query": 40, "product_search": 30, "recommendation": 20, "chitchat": 10},
        "embeddings": [[0.8] + [-0.8] * 31],
        "abstention_rate": 0.04,
        "fallback_rate": 0.05,
        "judge_score": 4.3
    }
    
    result = detector.detect_drift(shifted_embeddings_data)
    assert result["drift_detected"] is True
    assert result["drift_type"] == "EMBEDDING_DRIFT"

def test_drift_detector_quality_drift():
    detector = DriftDetector()
    
    # Degraded LLM judge score
    degraded_quality_data = {
        "intents": {"order_query": 40, "product_search": 30, "recommendation": 20, "chitchat": 10},
        "embeddings": [[0.15] * 32],
        "abstention_rate": 0.04,
        "fallback_rate": 0.05,
        "judge_score": 3.2  # Degraded from baseline 4.2
    }
    
    result = detector.detect_drift(degraded_quality_data)
    assert result["drift_detected"] is True
    assert result["drift_type"] == "QUALITY_DRIFT"
