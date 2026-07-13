import grpc
from langchain_core.tools import tool
# Import các file proto vừa compile ở Bước 2
import protos.demo_pb2 as demo_pb2
import protos.demo_pb2_grpc as demo_pb2_grpc

# Địa chỉ mặc định hướng về port-forward local ở tuần 1
# Khi lên cluster ở tuần 2, CDO sẽ đổi thành: "product-catalog.techx-tf3.svc.cluster.local:3550"
import os
CATALOG_ADDR = os.getenv("CATALOG_ADDR", "product-catalog:3550")

@tool
def search_products_tool(query: str) -> str:
    """
    ⚠️ DEPRECATED: Dùng search_products_v2 thay vào đó (multi-strategy search).
    
    Hữu ích khi người dùng muốn tìm kiếm sản phẩm trong kho bằng từ khóa, 
    mô tả tự nhiên hoặc tìm theo khoảng giá, danh mục sản phẩm.
    
    ⚠️ Công cụ này chỉ dùng LIKE search cơ bản, không hỗ trợ tiếng Việt tốt.
    Thay vào đó, hãy dùng `search_products_v2` từ tools/search/ module.
    """
    # 1. Mở đường truyền kết nối gRPC không bảo mật (Insecure) tới service
    channel = grpc.insecure_channel(CATALOG_ADDR)
    
    # 2. Tạo một Stub Client từ file grpc compile
    stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
    
    try:
        # 3. Đóng gói tham số đầu vào đúng định dạng Protobuf
        request = demo_pb2.SearchProductsRequest(query=query)
        
        # 4. Thực hiện lệnh gọi gRPC qua mạng
        response = stub.SearchProducts(request)
        
        # 5. Xử lý kết quả trả về thành dạng chuỗi văn bản (String) để LLM đọc
        if not response.results:
            return f"Hệ thống Catalog báo: Không tìm thấy sản phẩm nào khớp với từ khóa '{query}'."
            
        formatted_results = []
        for product in response.results:
            money = product.price_usd
            formatted_results.append(
                f"- ID: {product.id} | Tên: {product.name} | "
                f"Mô tả: {product.description} | Giá: {money.units} {money.currency_code}"
            )
        return "\n".join(formatted_results)
        
    except grpc.RpcError as e:
        return f"Lỗi kết nối gRPC tới Product Catalog Service: {e.details()}"
    finally:
        channel.close()