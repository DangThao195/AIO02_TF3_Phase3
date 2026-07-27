import numpy as np
import pandas as pd
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("AIOpsEngine.DriftDetector")

class DriftDetector:
    def __init__(self, psi_threshold: float = 0.25, cosine_threshold: float = 0.22, quality_decay_threshold: float = 0.15):
        self.psi_threshold = psi_threshold
        self.cosine_threshold = cosine_threshold
        self.quality_decay_threshold = quality_decay_threshold
        
        # Baselines (established from offline golden evaluation datasets)
        self.baseline_intent_dist = {"order_query": 0.4, "product_search": 0.3, "recommendation": 0.2, "chitchat": 0.1}
        self.baseline_abstention_rate = 0.05   # Expect 5% fallback/abstention in normal production
        self.baseline_fallback_rate = 0.08     # Expect 8% fallback in normal production
        self.baseline_judge_score = 4.2        # Expect mean score of 4.2 out of 5
        self.baseline_centroid = np.array([0.15] * 32) # Simulated 32-dim embedding centroid for baseline queries

    def calculate_psi(self, expected: List[float], actual: List[float], num_bins: int = 10) -> float:
        """
        Calculate Population Stability Index (PSI) to detect data distribution shift.
        PSI = sum((Actual_i - Expected_i) * ln(Actual_i / Expected_i))
        """
        try:
            expected = np.array(expected)
            actual = np.array(actual)

            # Ensure distributions sum to 1
            expected = expected / (np.sum(expected) + 1e-10)
            actual = actual / (np.sum(actual) + 1e-10)

            # Avoid division by zero and log of zero
            expected = np.where(expected == 0, 1e-4, expected)
            actual = np.where(actual == 0, 1e-4, actual)

            # Recalculate normalization after zero-adjustment
            expected = expected / np.sum(expected)
            actual = actual / np.sum(actual)

            psi = np.sum((actual - expected) * np.log(actual / expected))
            return float(psi)
        except Exception as e:
            logger.error(f"Error calculating PSI: {e}")
            return 0.0

    def calculate_cosine_distance(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Calculate cosine distance between two embedding vectors."""
        try:
            dot_product = np.dot(vec_a, vec_b)
            norm_a = np.linalg.norm(vec_a)
            norm_b = np.linalg.norm(vec_b)
            if norm_a == 0 or norm_b == 0:
                return 1.0
            cosine_similarity = dot_product / (norm_a * norm_b)
            return float(1.0 - cosine_similarity)
        except Exception as e:
            logger.error(f"Error calculating cosine distance: {e}")
            return 1.0

    def detect_drift(self, current_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate current system metrics (prompts, fallback counters, intent distributions)
        and determine if Data/Model drift is occurring.
        """
        results = {
            "drift_detected": False,
            "drift_type": None,
            "metrics": {},
            "message": "AI model quality and input distribution are within normal baseline."
        }

        # 1. Evaluate Intent Distribution Drift (Categorical Data Drift via PSI)
        current_intents = current_data.get("intents", {})
        if current_intents:
            # Map intents to baseline ordering
            keys = list(self.baseline_intent_dist.keys())
            expected_dist = [self.baseline_intent_dist[k] for k in keys]
            
            # Extract actual distribution from current data, default to small value if missing
            actual_counts = [current_intents.get(k, 1) for k in keys]
            actual_dist = np.array(actual_counts) / (sum(actual_counts) + 1e-10)
            
            psi_score = self.calculate_psi(expected_dist, actual_dist.tolist())
            results["metrics"]["intent_psi"] = psi_score
            
            if psi_score > self.psi_threshold:
                results["drift_detected"] = True
                results["drift_type"] = "DATA_DRIFT"
                results["message"] = f"Significant data shift detected! User query intents distribution shifted (PSI: {psi_score:.4f} > {self.psi_threshold})."
                return results

        # 2. Evaluate Query Embedding Space Drift (Embedding Drift)
        current_embeddings = current_data.get("embeddings", [])
        if current_embeddings:
            # Calculate distance of current batch centroid to baseline centroid
            avg_current_embedding = np.mean(current_embeddings, axis=0)
            embedding_distance = self.calculate_cosine_distance(self.baseline_centroid, avg_current_embedding)
            results["metrics"]["embedding_distance"] = embedding_distance
            
            if embedding_distance > self.cosine_threshold:
                results["drift_detected"] = True
                results["drift_type"] = "EMBEDDING_DRIFT"
                results["message"] = f"Embedding drift detected! Out-of-distribution prompts / new query styles (Cosine Distance: {embedding_distance:.4f} > {self.cosine_threshold})."
                return results

        # 3. Evaluate Output Quality Proxy Drift (Abstention, Fallback, Judge Score)
        abstention_rate = current_data.get("abstention_rate", 0.0)
        fallback_rate = current_data.get("fallback_rate", 0.0)
        judge_score = current_data.get("judge_score", 4.2)

        results["metrics"]["abstention_rate"] = abstention_rate
        results["metrics"]["fallback_rate"] = fallback_rate
        results["metrics"]["judge_score"] = judge_score

        # Abstention Rate spike
        if abstention_rate > self.baseline_abstention_rate * 3.0: # e.g. > 15%
            results["drift_detected"] = True
            results["drift_type"] = "QUALITY_DRIFT"
            results["message"] = f"Model Quality Drift! Abstention/Refusal rate spiked (Rate: {abstention_rate:.2%} vs Baseline: {self.baseline_abstention_rate:.2%})."
            return results

        # Fallback Rate spike
        if fallback_rate > self.baseline_fallback_rate * 2.5: # e.g. > 20%
            results["drift_detected"] = True
            results["drift_type"] = "QUALITY_DRIFT"
            results["message"] = f"Model Quality Drift! Model falling back to fallback routes frequently (Rate: {fallback_rate:.2%} vs Baseline: {self.baseline_fallback_rate:.2%})."
            return results

        # LLM Judge Score decay
        if judge_score < self.baseline_judge_score * (1.0 - self.quality_decay_threshold): # e.g. < 3.57
            results["drift_detected"] = True
            results["drift_type"] = "QUALITY_DRIFT"
            results["message"] = f"Model Performance Drift! Evaluated LLM Judge score degraded to {judge_score:.2f} (Baseline: {self.baseline_judge_score:.2f})."
            return results

        return results
