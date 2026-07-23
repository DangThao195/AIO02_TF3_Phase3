# tools/__init__.py

from src.tools.search import search_products_v2
from src.tools.cart_tool import add_to_cart_tool, update_cart_item_tool, get_cart_tool, check_cart_item_tool
from src.tools.product_tool import get_product_details_tool
from src.tools.review_tool import get_product_reviews_tool
from src.tools.recommendation_tool import get_recommendations_tool
from src.tools.currency_tool import convert_currency_tool
from src.tools.shipping_tool import get_shipping_quote_tool
from src.tools.catalog_tool import get_categories, get_all_products
from src.tools.product_id_tool import get_product_id

# Danh sách đầy đủ tất cả các công cụ bàn giao cho AI Agent
# ⚠️ LƯỚI: search_products_v2 thay thế search_products_tool (multi-strategy, hỗ trợ tiếng Việt)
all_shopping_tools = [
    # Nhóm Search
    search_products_v2,          # tìm kiếm sản phẩm (multi-strategy)
    
    # Nhóm Catalog
    get_categories,              # lấy danh sách danh mục
    get_all_products,            # lấy toàn bộ sản phẩm (chỉ khi thực sự cần)
    
    # Nhóm ID Lookup
    get_product_id,              # tra product_id từ tên sản phẩm
    
    # Nhóm Product Detail
    get_product_details_tool,    # chi tiết sản phẩm theo ID
    
    # Nhóm Core (Bắt buộc)
    get_product_reviews_tool,
    add_to_cart_tool,
    update_cart_item_tool,       # cập nhật/xoá sản phẩm trong giỏ
    get_cart_tool,
    check_cart_item_tool,        # kiểm tra sản phẩm có trong giỏ không
    
    # Nhóm Mở rộng (Đua top)
    get_recommendations_tool,
    convert_currency_tool,
    get_shipping_quote_tool
]