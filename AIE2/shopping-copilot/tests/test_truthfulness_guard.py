"""
test_truthfulness_guard.py — Tests for guardrail and fallback behavior (v3.2)

Replaces v2 CopilotAgent-based tests with direct guardrail/fallback tests.
"""

import os
import sys
import re
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

from src.guardrails.fallback import handle_exception


def _is_direct_tool_message(text: str) -> bool:
    """
    Detect if a message is a direct tool result that should pass through.
    Equivalent to v2 CopilotAgent._should_return_tool_message_directly().
    """
    patterns = [
        r"không tìm thấy sản phẩm",
        r"product not found",
        r"giỏ hàng.*trống",
        r"cart.*empty",
        r"không có sản phẩm nào",
        r"chưa có đánh giá",
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


class TestTruthfulnessGuard(unittest.TestCase):
    def test_detects_not_found_and_empty_cart_messages(self):
        self.assertTrue(
            _is_direct_tool_message(
                "Không tìm thấy sản phẩm 'OLJCESPC7Z' trong giỏ hàng của bạn."
            )
        )
        self.assertTrue(
            _is_direct_tool_message(
                "Giỏ hàng của người dùng 'test_user' hiện đang trống."
            )
        )
        self.assertTrue(
            _is_direct_tool_message("Product not found in cart")
        )
        self.assertFalse(
            _is_direct_tool_message(
                "Đã thêm sản phẩm vào giỏ hàng thành công."
            )
        )

    def test_returns_friendly_fallback_for_bedrock_unavailable(self):
        response = handle_exception(Exception("bedrock-runtime connection timeout"))

        self.assertEqual(response["status"], "error")
        self.assertIn("không khả dụng", response["reply"].lower())
        self.assertEqual(response["error_code"], "BEDROCK_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
