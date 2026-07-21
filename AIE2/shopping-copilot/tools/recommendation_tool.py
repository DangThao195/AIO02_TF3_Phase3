# tools/recommendation_tool.py
import grpc
from langchain_core.tools import tool
import protos.demo_pb2 as demo_pb2
import protos.demo_pb2_grpc as demo_pb2_grpc

import os
RECO_ADDR = os.getenv("RECO_ADDR", "recommendation:8080")

@tool
def get_recommendations_tool(product_id: str, user_id: str = "default_user") -> str:
    """
    Hữu ích khi người dùng muốn xem các gợi ý sản phẩm liên quan, sản phẩm tương tự 
    hoặc các mặt hàng thường được mua kèm với sản phẩm họ đang xem (Cross-sell).
    Đầu vào cần thiết: product_id (mã sản phẩm hiện tại).
    """
    channel = grpc.insecure_channel(RECO_ADDR)
    stub = demo_pb2_grpc.RecommendationServiceStub(channel)
    
    try:
        # Khởi tạo request đúng cấu trúc ListRecommendationsRequest (gồm user_id và product_ids)
        request = demo_pb2.ListRecommendationsRequest(
            user_id=user_id,
            product_ids=[product_id]
        )
        response = stub.ListRecommendations(request)
        
        # Đọc danh sách ID trả về từ trường product_ids
        if not response.product_ids:
            return f"Hệ thống hiện tại không có gợi ý sản phẩm đi kèm nào cho sản phẩm '{product_id}'."
            
        return f"Các sản phẩm gợi ý thường được mua kèm với {product_id} là: " + ", ".join(response.product_ids)
        
    except grpc.RpcError as e:
        return f"Lỗi hệ thống khi lấy danh sách sản phẩm gợi ý (gRPC): {e.details()}"
    finally:
        channel.close()