"""
test_fallback_tier2.py
======================
Unit tests for Task 3: Tier 2 Fallback integration.
When LLM calls fail or Circuit Breaker / Injection / Forced error active:
- Checks PostgreSQL reviews.product_summaries table.
- If old summary exists -> Returns Tier 2 static summary.
- If no summary exists -> Returns Tier 3 generic error message.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guardrails.error_injection as ei_module
import product_reviews_server as srv


def _base_patches(stack):
    stack.enter_context(patch.object(srv, "check_input", return_value=MagicMock(is_safe=True)))
    stack.enter_context(patch.object(srv, "filter_output", return_value=MagicMock(filtered_response="Is this product good?")))
    stack.enter_context(patch.object(srv, "is_clearly_off_topic_question", return_value=False))
    stack.enter_context(patch.object(srv, "get_cached_response", return_value=None))
    stack.enter_context(patch.object(srv, "acquire_lock", return_value=True))
    stack.enter_context(patch.object(srv, "release_lock"))
    stack.enter_context(patch.object(srv, "get_review_version", return_value="v1_test"))
    stack.enter_context(patch.object(srv, "generate_cache_key", return_value="cache_test"))
    stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=False))
    stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=True))
    stack.enter_context(patch.object(ei_module, "redis_client", None))
    stack.enter_context(patch.object(srv, "write_llm_trace"))
    stack.enter_context(patch.object(srv, "build_runtime_trace_record", return_value={
        "guardrails": {}, "cache": {}, "candidate": {}, "judge": {}
    }))
    stack.enter_context(patch.object(srv, "finalize_runtime_trace", return_value={}))
    stack.enter_context(patch.object(srv, "product_review_svc_metrics", {
        "app_ai_fallback_total": MagicMock(),
        "app_ai_assistant_counter": MagicMock(),
    }))
    mock_tracer = stack.enter_context(patch("product_reviews_server.tracer"))
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: mock_span
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)


class TestTier2FallbackIntegration(unittest.TestCase):

    def test_fallback_returns_tier2_when_summary_exists_in_db(self):
        """Khi gặp lỗi injection 429 và có tóm tắt cũ trong DB -> Trả về tóm tắt Tầng 2."""
        mock_db_summary = {
            "product_id": "PROD001",
            "summary_text": "This is a pre-approved static summary from PostgreSQL.",
            "rating_distribution": '{"5": 5}',
            "review_version": "v1_old",
            "updated_at": "2026-07-27 10:00:00",
        }

        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=mock_db_summary))

            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, "This is a pre-approved static summary from PostgreSQL.")

    def test_fallback_returns_tier3_when_summary_missing_in_db(self):
        """Khi gặp lỗi injection 429 và KHÔNG có tóm tắt trong DB -> Trả về generic error message (Tầng 3)."""
        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=None))

            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)

    def test_circuit_breaker_open_returns_tier2_summary_when_present(self):
        """Khi Circuit Breaker đang OPEN và có DB summary -> Trả về Tầng 2 static summary."""
        mock_db_summary = {
            "product_id": "PROD002",
            "summary_text": "Cached CB fallback summary from Postgres.",
        }

        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=False))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=mock_db_summary))

            response = srv.get_ai_assistant_response("PROD002", "Tell me about this item.")

        self.assertEqual(response.response, "Cached CB fallback summary from Postgres.")

    def test_redis_override_returns_tier2_summary_when_present(self):
        """Khi Redis fallback_override active và có DB summary -> Trả về Tầng 2 static summary."""
        mock_db_summary = {
            "product_id": "PROD003",
            "summary_text": "Redis override static summary from Postgres.",
        }

        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=True))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=mock_db_summary))

            response = srv.get_ai_assistant_response("PROD003", "Summary of reviews?")

        self.assertEqual(response.response, "Redis override static summary from Postgres.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
