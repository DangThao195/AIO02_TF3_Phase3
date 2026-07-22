import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

from src.agent.copilot_agent import CopilotAgent
from src.guardrails.fallback import handle_exception


class TestTruthfulnessGuard(unittest.TestCase):
    def test_detects_not_found_and_empty_cart_messages(self):
        agent = CopilotAgent.__new__(CopilotAgent)

        self.assertTrue(
            agent._should_return_tool_message_directly(
                "Không tìm thấy sản phẩm 'OLJCESPC7Z' trong giỏ hàng của bạn."
            )
        )
        self.assertTrue(
            agent._should_return_tool_message_directly(
                "Giỏ hàng của người dùng 'test_user' hiện đang trống."
            )
        )
        self.assertTrue(
            agent._should_return_tool_message_directly("Product not found in cart")
        )
        self.assertFalse(
            agent._should_return_tool_message_directly(
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
