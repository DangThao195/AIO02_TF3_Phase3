import unittest
from unittest.mock import MagicMock, patch


class TestCartTool(unittest.TestCase):
    def test_check_cart_item_tool_not_found(self):
        from src.tools.cart_tool import check_cart_item_tool

        mock_channel = MagicMock()
        mock_stub = MagicMock()

        item = MagicMock()
        item.product_id = "OTHER1234"
        item.quantity = 2

        mock_response = MagicMock()
        mock_response.items = [item]
        mock_stub.GetCart.return_value = mock_response
        mock_channel.__enter__.return_value = mock_channel
        mock_channel.__exit__.return_value = False

        with patch("src.tools.cart_tool.grpc.insecure_channel", return_value=mock_channel):
            with patch("src.tools.cart_tool.demo_pb2_grpc.CartServiceStub", return_value=mock_stub):
                result = check_cart_item_tool.func(user_id="test_user", product_id="OLJCESPC7Z")

        self.assertEqual(result, "Không tìm thấy sản phẩm 'OLJCESPC7Z' trong giỏ hàng của bạn.")

    def test_check_cart_item_tool_found(self):
        from src.tools.cart_tool import check_cart_item_tool

        mock_channel = MagicMock()
        mock_stub = MagicMock()

        item = MagicMock()
        item.product_id = "OLJCESPC7Z"
        item.quantity = 3

        mock_response = MagicMock()
        mock_response.items = [item]
        mock_stub.GetCart.return_value = mock_response
        mock_channel.__enter__.return_value = mock_channel
        mock_channel.__exit__.return_value = False

        with patch("src.tools.cart_tool.grpc.insecure_channel", return_value=mock_channel):
            with patch("src.tools.cart_tool.demo_pb2_grpc.CartServiceStub", return_value=mock_stub):
                result = check_cart_item_tool.func(user_id="test_user", product_id="OLJCESPC7Z")

        self.assertEqual(result, "Sản phẩm 'OLJCESPC7Z' đang có trong giỏ hàng với số lượng 3.")


if __name__ == "__main__":
    unittest.main()
