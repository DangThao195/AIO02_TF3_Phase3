# tools/__init__.py

from src.tools.search_product import search_products_v2
from src.tools.cart_tool import add_to_cart_tool, get_cart_tool, check_cart_item_tool
from src.tools.review_tool import get_product_reviews_tool, get_best_reviewed_products_tool, get_worst_reviewed_products_tool
from src.tools.recommendation_tool import get_recommendations_tool
from src.tools.currency_tool import convert_currency_tool
from src.tools.shipping_tool import get_shipping_quote_tool
from src.tools.catalog_tool import get_categories, get_all_products, get_top_rated_products, get_products_by_price_range
from src.tools.product_id_tool import get_product_id

# Danh sách đầy đủ tất cả các công cụ bàn giao cho AI Agent
# ⚠️ LƯỚI: search_products_v2 thay thế search_products_tool (multi-strategy, hỗ trợ tiếng Việt)
all_shopping_tools = [
    # Nhóm Search
    search_products_v2,          # tìm kiếm sản phẩm (multi-strategy)
    
    # Nhóm Catalog
    get_categories,              # lấy danh sách danh mục
    get_all_products,            # lấy toàn bộ sản phẩm (chỉ khi thực sự cần)
    get_top_rated_products,      # lấy sản phẩm đánh giá cao nhất
    get_products_by_price_range, # lấy sản phẩm theo khoảng giá
    
    # Nhóm ID Lookup
    get_product_id,              # tra product_id từ tên sản phẩm
    
    # Nhóm Core (Bắt buộc)
    get_product_reviews_tool,
    get_best_reviewed_products_tool,   # top sản phẩm review tốt nhất
    get_worst_reviewed_products_tool,  # top sản phẩm review tệ nhất
    add_to_cart_tool,
    get_cart_tool,
    
    # Nhóm Mở rộng (Đua top)
    get_recommendations_tool,
    convert_currency_tool,
    get_shipping_quote_tool
]