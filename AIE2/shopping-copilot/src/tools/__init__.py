# tools/__init__.py

from src.tools.search import search_products_v2
from src.tools.cart_tool import add_to_cart_tool, get_cart_tool
from src.tools.review_tool import get_product_reviews_tool
from src.tools.recommendation_tool import get_recommendations_tool
from src.tools.currency_tool import convert_currency_tool
from src.tools.shipping_tool import get_shipping_quote_tool

# Danh sách đầy đủ tất cả các công cụ bàn giao cho AI Agent
# ⚠️ LƯỚI: search_products_v2 thay thế search_products_tool (multi-strategy, hỗ trợ tiếng Việt)
all_shopping_tools = [
    # Nhóm Search (COQUI: dùng search_products_v2 thay vì search_products_tool cũ)
    search_products_v2,          # ✅ MỚI: multi-strategy (recommended)
    
    # Nhóm Core (Bắt buộc)
    get_product_reviews_tool,
    add_to_cart_tool,
    get_cart_tool,
    
    # Nhóm Mở rộng (Đua top)
    get_recommendations_tool,
    convert_currency_tool,
    get_shipping_quote_tool
]