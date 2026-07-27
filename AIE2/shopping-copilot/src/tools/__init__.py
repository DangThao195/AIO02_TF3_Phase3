# tools/__init__.py

from src.tools.search.category_filter import category_filter
from src.tools.search.price_filter import price_filter
from src.tools.search.semantic_filter import semantic_filter
from src.tools.search.multi_filter import multi_filter
from src.tools.cart_tool import add_to_cart_tool, update_cart_item_tool, get_cart_tool, check_cart_item_tool
from src.tools.product_tool import get_product_details_tool
from src.tools.review_tool import get_product_reviews_tool, get_best_reviewed_products_tool, get_worst_reviewed_products_tool
from src.tools.recommendation_tool import get_recommendations_tool
from src.tools.currency_tool import convert_currency_tool
from src.tools.shipping_tool import get_shipping_quote_tool
from src.tools.catalog_tool import get_categories, get_all_products
from src.tools.product_id_tool import get_product_id
from src.tools.out_of_scope_tool import respond_out_of_scope_tool

# Danh sách đầy đủ tất cả các công cụ bàn giao cho AI Agent
all_shopping_tools = [
    # Nhóm Filter (thay thế search_products_v2)
    category_filter,             # lọc sản phẩm theo danh mục
    price_filter,                # lọc sản phẩm theo khoảng giá
    semantic_filter,             # tìm kiếm sản phẩm theo ngữ nghĩa
    multi_filter,                # chuỗi filter tuần tự (category → price → semantic)

    # Nhóm Catalog
    get_categories,              # lấy danh sách danh mục
    get_all_products,            # lấy toàn bộ sản phẩm (chỉ khi thực sự cần)

    # Nhóm ID Lookup
    get_product_id,              # tra product_id từ tên sản phẩm

    # Nhóm Product Detail
    get_product_details_tool,    # chi tiết sản phẩm theo ID

    # Nhóm Core (Bắt buộc)
    get_product_reviews_tool,
    get_best_reviewed_products_tool,  # sản phẩm đánh giá cao nhất
    get_worst_reviewed_products_tool,  # sản phẩm đánh giá thấp nhất
    add_to_cart_tool,
    update_cart_item_tool,       # cập nhật/xoá sản phẩm trong giỏ
    get_cart_tool,
    check_cart_item_tool,        # kiểm tra sản phẩm có trong giỏ không

    # Nhóm Mở rộng (Đua top)
    get_recommendations_tool,
    convert_currency_tool,
    get_shipping_quote_tool
]