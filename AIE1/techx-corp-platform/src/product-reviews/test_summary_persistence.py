"""
test_summary_persistence.py
============================
Unit tests for Task 2: Khi LLM + Judge thành công (approved/deterministic),
hệ thống ghi đè bản tóm tắt vào reviews.product_summaries.

Dùng Bedrock path vì dễ mock toàn bộ flow:
  call_candidate_bedrock → apply_runtime_fidelity_gate → finally block
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guardrails.error_injection as ei_module
import product_reviews_server as srv


def _base_patches(stack, filtered_response="Is this product good?"):
    """Các mock chung cho mọi test trong file này."""
    stack.enter_context(patch.object(srv, "check_input", return_value=MagicMock(is_safe=True)))
    stack.enter_context(patch.object(srv, "filter_output",
                                     return_value=MagicMock(filtered_response=filtered_response)))
    stack.enter_context(patch.object(srv, "is_clearly_off_topic_question", return_value=False))
    stack.enter_context(patch.object(srv, "get_cached_response", return_value=None))
    stack.enter_context(patch.object(srv, "acquire_lock", return_value=True))
    stack.enter_context(patch.object(srv, "release_lock"))
    stack.enter_context(patch.object(srv, "should_cache", return_value=False))
    stack.enter_context(patch.object(srv, "get_review_version", return_value="v1_test"))
    stack.enter_context(patch.object(srv, "generate_cache_key", return_value="cache_test"))
    stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=False))
    stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=True))
    stack.enter_context(patch.object(ei_module, "redis_client", None))
    stack.enter_context(patch.object(srv, "get_injected_error_type", return_value=None))
    stack.enter_context(patch.object(srv, "write_llm_trace"))
    stack.enter_context(patch.object(srv, "build_runtime_trace_record", return_value={
        "guardrails": {}, "cache": {}, "candidate": {}, "judge": {}
    }))
    stack.enter_context(patch.object(srv, "finalize_runtime_trace", return_value={}))
    stack.enter_context(patch.object(srv, "product_review_svc_metrics", {
        "app_ai_fallback_total": MagicMock(),
        "app_ai_assistant_counter": MagicMock(),
    }))
    # Dùng Bedrock path
    stack.enter_context(patch.object(srv, "llm_provider", "bedrock"))
    stack.enter_context(patch.object(srv, "fetch_product_reviews", return_value="[]"))
    stack.enter_context(patch.object(srv, "normalize_reviews_for_context", return_value=("[]", [])))
    stack.enter_context(patch.object(srv, "answer_deterministic_rating_question", return_value=None))
    stack.enter_context(patch.object(srv, "answer_deterministic_absence_question", return_value=None))
    stack.enter_context(patch.object(srv, "fetch_product_info", return_value='{"name":"Lens Kit"}'))
    stack.enter_context(patch.object(srv, "check_feature_flag", return_value=False))
    stack.enter_context(patch.object(srv, "build_bedrock_user_prompt", return_value="grounded_prompt"))

    mock_tracer = stack.enter_context(patch("product_reviews_server.tracer"))
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: mock_span
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)


class TestSummaryPersistenceOnApproved(unittest.TestCase):
    """Khi judge_status=approved → save_product_summary được gọi."""

    def test_approved_result_triggers_save(self):
        """judge_status=approved + grounded answer → save_product_summary được gọi."""
        mock_save = MagicMock(return_value=True)

        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv, "call_candidate_bedrock",
                                             return_value="Great product!"))
            stack.enter_context(patch.object(srv, "post_process_output",
                                             return_value="Great product!"))
            stack.enter_context(patch.object(srv, "apply_runtime_fidelity_gate",
                                             return_value=("Great product!", "approved")))
            stack.enter_context(patch.object(srv, "save_product_summary", mock_save))

            srv.get_ai_assistant_response("PROD001", "Is this product good?")

        mock_save.assert_called_once_with(
            product_id="PROD001",
            summary_text="Great product!",
            review_version="v1_test",
        )

    def test_rejected_result_does_not_trigger_save(self):
        """judge_status=rejected → save_product_summary KHÔNG được gọi."""
        mock_save = MagicMock(return_value=True)

        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv, "call_candidate_bedrock",
                                             return_value="Bad answer"))
            stack.enter_context(patch.object(srv, "post_process_output",
                                             return_value=srv.UNVERIFIED_SUMMARY_MESSAGE))
            stack.enter_context(patch.object(srv, "apply_runtime_fidelity_gate",
                                             return_value=(srv.UNVERIFIED_SUMMARY_MESSAGE, "rejected")))
            stack.enter_context(patch.object(srv, "save_product_summary", mock_save))

            srv.get_ai_assistant_response("PROD001", "Is this product good?")

        mock_save.assert_not_called()

    def test_fallback_result_does_not_trigger_save(self):
        """result=FALLBACK_SUMMARY_MESSAGE (LLM lỗi) → save_product_summary KHÔNG được gọi."""
        mock_save = MagicMock(return_value=True)

        with ExitStack() as stack:
            _base_patches(stack)
            # call_candidate_bedrock trả về FALLBACK_SUMMARY_MESSAGE (after retries exhausted)
            stack.enter_context(patch.object(srv, "call_candidate_bedrock",
                                             return_value=srv.FALLBACK_SUMMARY_MESSAGE))
            stack.enter_context(patch.object(srv, "save_product_summary", mock_save))

            srv.get_ai_assistant_response("PROD001", "Is this product good?")

        mock_save.assert_not_called()

    def test_save_db_failure_is_non_fatal(self):
        """Lỗi DB khi lưu tóm tắt không làm crash response - trả đúng kết quả LLM."""
        mock_save = MagicMock(side_effect=Exception("DB connection refused"))

        with ExitStack() as stack:
            _base_patches(stack)
            stack.enter_context(patch.object(srv, "call_candidate_bedrock",
                                             return_value="Great product!"))
            stack.enter_context(patch.object(srv, "post_process_output",
                                             return_value="Great product!"))
            stack.enter_context(patch.object(srv, "apply_runtime_fidelity_gate",
                                             return_value=("Great product!", "approved")))
            stack.enter_context(patch.object(srv, "save_product_summary", mock_save))

            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        # DB lỗi nhưng response vẫn là kết quả LLM, không crash
        self.assertEqual(response.response, "Great product!")
        mock_save.assert_called_once()  # Đã cố gọi, dù lỗi


if __name__ == "__main__":
    unittest.main(verbosity=2)
