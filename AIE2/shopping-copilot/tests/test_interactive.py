"""
test_interactive.py — Interactive CLI Test cho Shopping Copilot Agent.

Test toàn bộ luồng chat end-to-end:
  - Nhập câu hỏi tự do từ terminal
  - Hiển thị kết quả JSON đầy đủ (status, reply, token, guardrail info)
  - Hỗ trợ multi-turn (giữ session liên tục)
  - Hỗ trợ xác nhận hành động ghi (confirm/cancel)
  - Hiển thị cache stats, session info

2 chế độ chạy:
  1. MOCK mode (mặc định): mock gRPC, dùng LLM Groq thật → test luồng agent
  2. LIVE mode: gọi gRPC thật (cần port-forward từ EKS) → test end-to-end

Chạy:
    py test_interactive.py              # Mock mode (cần GROQ_API_KEY trong .env)
    py test_interactive.py --live       # Live mode (cần cả gRPC port-forward)
    py test_interactive.py --no-llm     # Full mock (không cần API key, test guardrail only)

Tham chiếu: agentic_design.md — Mục 6, 8.
"""

import sys
import os
import json
import uuid
import time
import logging
import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── Setup path ──
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ── Parse arguments ──
parser = argparse.ArgumentParser(description="Interactive Shopping Copilot Test")
parser.add_argument("--live", action="store_true", help="Chế độ LIVE — gọi gRPC thật (cần port-forward)")
parser.add_argument("--no-llm", action="store_true", help="Full mock — không cần GROQ_API_KEY")
parser.add_argument("--user-id", default="test_user_001", help="User ID cho session (default: test_user_001)")
parser.add_argument("--debug", action="store_true", help="Bật debug logging")
args = parser.parse_args()

# ── Logging ──
log_level = logging.DEBUG if args.debug else logging.WARNING
logging.basicConfig(
    level=log_level,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stderr,
)


# ══════════════════════════════════════════════════════════════════
# Mock setup
# ══════════════════════════════════════════════════════════════════

_patches = []

# Mock gRPC data
MOCK_PRODUCTS = [
    {"id": "OLJCESPC7Z", "name": "Vintage Typewriter", "desc": "Máy đánh chữ cổ điển", "price": "65.50", "currency": "USD"},
    {"id": "66VCHSJNUP", "name": "Vintage Camera Lens", "desc": "Ống kính camera vintage", "price": "45.99", "currency": "USD"},
    {"id": "1YMWWN1N4O", "name": "Home Barista Kit", "desc": "Bộ pha cà phê tại nhà", "price": "124.00", "currency": "USD"},
    {"id": "L9ECAV7KIM", "name": "Terrarium", "desc": "Bể cây cảnh mini", "price": "36.45", "currency": "USD"},
    {"id": "2ZYFJ3GM2N", "name": "Film Camera", "desc": "Máy ảnh phim retro", "price": "89.99", "currency": "USD"},
]

MOCK_REVIEWS = {
    "OLJCESPC7Z": [
        {"reviewer": "Nguyen Van A", "rating": 5, "content": "Máy đánh chữ rất đẹp, phím gõ êm. Pin dùng được 2 tuần liên tục."},
        {"reviewer": "Tran Thi B", "rating": 4, "content": "Thiết kế cổ điển rất ưng, nhưng hơi nặng. Chất lượng tốt."},
    ],
    "66VCHSJNUP": [
        {"reviewer": "Le Van C", "rating": 5, "content": "Ống kính chụp cực nét, lắp vừa máy Nikon D3500."},
        {"reviewer": "Pham D", "rating": 3, "content": "Lens tốt nhưng giao hàng hơi lâu, 5 ngày mới nhận."},
    ],
}

MOCK_RECOMMENDATIONS = ["66VCHSJNUP", "1YMWWN1N4O", "L9ECAV7KIM"]

MOCK_CART = {}  # user_id -> list of {product_id, quantity}


def _build_mock_search_response():
    """Tạo mock response cho SearchProducts."""
    mock_resp = MagicMock()
    mock_results = []
    for p in MOCK_PRODUCTS:
        item = MagicMock()
        item.id = p["id"]
        item.name = p["name"]
        item.description = p["desc"]
        price = MagicMock()
        price.units = int(float(p["price"]))
        price.nanos = int((float(p["price"]) % 1) * 1e9)
        price.currency_code = p["currency"]
        item.price_usd = price
        item.categories = ["vintage"]
        mock_results.append(item)
    mock_resp.results = mock_results
    return mock_resp


def _build_mock_reviews_response(product_id):
    """Tạo mock response cho GetProductReviews."""
    mock_resp = MagicMock()
    reviews = MOCK_REVIEWS.get(product_id, [])
    mock_reviews = []
    for r in reviews:
        review = MagicMock()
        review.reviewer_name = r["reviewer"]
        review.rating = r["rating"]
        review.content = r["content"]
        mock_reviews.append(review)
    mock_resp.product_reviews = mock_reviews
    return mock_resp


def _build_mock_cart_response(user_id):
    """Tạo mock response cho GetCart."""
    mock_resp = MagicMock()
    items = MOCK_CART.get(user_id, [])
    mock_items = []
    for item in items:
        mock_item = MagicMock()
        mock_item.product_id = item["product_id"]
        mock_item.quantity = item["quantity"]
        mock_items.append(mock_item)
    mock_resp.items = mock_items
    return mock_resp


def _build_mock_recommendations_response():
    """Tạo mock response cho ListRecommendations."""
    mock_resp = MagicMock()
    mock_resp.product_ids = MOCK_RECOMMENDATIONS
    return mock_resp


def _build_mock_currency_response():
    """Tạo mock response cho CurrencyService.Convert."""
    mock_resp = MagicMock()
    mock_resp.units = 1625000
    mock_resp.nanos = 0
    mock_resp.currency_code = "VND"
    return mock_resp


def _build_mock_shipping_response():
    """Tạo mock response cho ShippingService.GetQuote."""
    mock_resp = MagicMock()
    cost = MagicMock()
    cost.units = 8
    cost.nanos = 990000000
    mock_resp.cost_usd = cost
    mock_resp.shipping_days = 5
    return mock_resp


def _setup_grpc_mocks():
    """Mock tất cả gRPC calls với dữ liệu giả."""
    import tools.catalog_tool
    import tools.review_tool
    import tools.cart_tool
    import tools.recommendation_tool
    import tools.currency_tool
    import tools.shipping_tool

    # Mock grpc.insecure_channel cho tất cả modules
    all_modules = [
        tools.catalog_tool, tools.review_tool, tools.cart_tool,
        tools.recommendation_tool, tools.currency_tool, tools.shipping_tool,
    ]

    # Tạo mock channel và stubs
    mock_channel = MagicMock()
    mock_channel.__enter__ = MagicMock(return_value=mock_channel)
    mock_channel.__exit__ = MagicMock(return_value=False)

    for mod in all_modules:
        try:
            p = patch(f"{mod.__name__}.grpc.insecure_channel", return_value=mock_channel)
            p.start()
            _patches.append(p)
        except AttributeError:
            # Một số module như shipping_tool không dùng grpc
            continue

    # Mock agent's grpc channel (for confirm flow)
    try:
        import agent.copilot_agent
        p = patch(f"agent.copilot_agent.grpc.insecure_channel", return_value=mock_channel)
        p.start()
        _patches.append(p)
    except ImportError:
        pass

    # ── Mock Catalog Stub ──
    mock_catalog_stub = MagicMock()
    mock_catalog_stub.return_value.SearchProducts.return_value = _build_mock_search_response()
    p = patch("tools.catalog_tool.demo_pb2_grpc.ProductCatalogServiceStub", mock_catalog_stub)
    p.start()
    _patches.append(p)

    # ── Mock Review Stub ──
    mock_review_stub = MagicMock()
    mock_review_stub.return_value.GetProductReviews.side_effect = lambda req: _build_mock_reviews_response(req.product_id)
    p = patch("tools.review_tool.demo_pb2_grpc.ProductReviewServiceStub", mock_review_stub)
    p.start()
    _patches.append(p)

    # ── Mock Cart Stub ──
    def _mock_add_item(req):
        user_id = req.user_id
        if user_id not in MOCK_CART:
            MOCK_CART[user_id] = []
        # Check if product already in cart
        for item in MOCK_CART[user_id]:
            if item["product_id"] == req.item.product_id:
                item["quantity"] += req.item.quantity
                return MagicMock()
        MOCK_CART[user_id].append({
            "product_id": req.item.product_id,
            "quantity": req.item.quantity,
        })
        return MagicMock()

    mock_cart_stub = MagicMock()
    mock_cart_stub.return_value.GetCart.side_effect = lambda req: _build_mock_cart_response(req.user_id)
    mock_cart_stub.return_value.AddItem.side_effect = _mock_add_item
    p = patch("tools.cart_tool.demo_pb2_grpc.CartServiceStub", mock_cart_stub)
    p.start()
    _patches.append(p)

    # Mock agent's CartServiceStub too (for confirm flow)
    try:
        p = patch("agent.copilot_agent.demo_pb2_grpc.CartServiceStub", mock_cart_stub)
        p.start()
        _patches.append(p)
    except Exception:
        pass

    # ── Mock Recommendation Stub ──
    mock_reco_stub = MagicMock()
    mock_reco_stub.return_value.ListRecommendations.return_value = _build_mock_recommendations_response()
    p = patch("tools.recommendation_tool.demo_pb2_grpc.RecommendationServiceStub", mock_reco_stub)
    p.start()
    _patches.append(p)

    # ── Mock Currency Stub ──
    mock_currency_stub = MagicMock()
    mock_currency_stub.return_value.Convert.return_value = _build_mock_currency_response()
    p = patch("tools.currency_tool.demo_pb2_grpc.CurrencyServiceStub", mock_currency_stub)
    p.start()
    _patches.append(p)

    # ── Mock Shipping Stub ──
    try:
        mock_shipping_stub = MagicMock()
        mock_shipping_stub.return_value.GetQuote.return_value = _build_mock_shipping_response()
        p = patch("tools.shipping_tool.demo_pb2_grpc.ShippingServiceStub", mock_shipping_stub)
        p.start()
        _patches.append(p)
    except AttributeError:
        # shipping_tool dùng REST nên không cần patch grpc stub
        pass


def _setup_llm_mock():
    """Mock LLM cho chế độ --no-llm."""
    from langchain_core.messages import AIMessage

    mock_llm = MagicMock()

    def _mock_invoke(messages, *a, **kw):
        # Đọc tin nhắn cuối cùng
        last_msg = messages[-1].content if messages else ""
        # Trả câu trả lời mẫu (không gọi tool)
        return AIMessage(content=(
            f"[MOCK LLM] Tôi nhận được câu hỏi: \"{last_msg}\"\n\n"
            f"Đây là chế độ mock (--no-llm). LLM không thật sự hoạt động.\n"
            f"Các guardrail layers vẫn chạy đầy đủ.\n"
            f"Để test với LLM thật, bỏ flag --no-llm và set GROQ_API_KEY trong .env"
        ))

    mock_llm.invoke = _mock_invoke
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)

    p = patch("agent.copilot_agent._build_llm", return_value=mock_llm)
    p.start()
    _patches.append(p)

    # Đảm bảo _API_KEY có giá trị
    p2 = patch("agent.copilot_agent._API_KEY", "mock-key-for-testing")
    p2.start()
    _patches.append(p2)


# ══════════════════════════════════════════════════════════════════
# Display helpers
# ══════════════════════════════════════════════════════════════════

# ANSI colors
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_DARK = "\033[48;5;236m"


def _print_banner():
    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║         🛒  Shopping Copilot — Interactive Test CLI          ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}
""")

    mode = "LIVE (gRPC thật)" if args.live else ("MOCK (no LLM)" if args.no_llm else "MOCK (LLM Groq thật)")
    print(f"  {C.DIM}Mode:{C.RESET}      {C.YELLOW}{mode}{C.RESET}")
    print(f"  {C.DIM}User ID:{C.RESET}   {C.WHITE}{args.user_id}{C.RESET}")
    print(f"  {C.DIM}Session:{C.RESET}   {C.WHITE}(auto-generated){C.RESET}")
    print()
    print(f"  {C.DIM}Commands:{C.RESET}")
    print(f"    {C.GREEN}/confirm{C.RESET}    — Xác nhận hành động ghi đang chờ")
    print(f"    {C.RED}/cancel{C.RESET}     — Huỷ hành động đang chờ")
    print(f"    {C.CYAN}/session{C.RESET}    — Xem thông tin session hiện tại")
    print(f"    {C.CYAN}/cache{C.RESET}      — Xem cache stats")
    print(f"    {C.CYAN}/cart{C.RESET}       — Xem mock cart data")
    print(f"    {C.YELLOW}/new{C.RESET}        — Tạo session mới")
    print(f"    {C.RED}/quit{C.RESET}       — Thoát")
    print()
    print(f"  {C.DIM}{'─' * 60}{C.RESET}")
    print()


def _print_result(result: dict, elapsed_ms: int):
    """In kết quả JSON đẹp với màu sắc."""
    status = result.get("status", "?")
    reply = result.get("reply", "")
    token = result.get("token")
    error_code = result.get("error_code")

    # Status badge
    if status == "ok":
        badge = f"{C.GREEN}✅ OK{C.RESET}"
    elif status == "pending":
        badge = f"{C.YELLOW}⏳ PENDING{C.RESET}"
    elif status == "error":
        badge = f"{C.RED}❌ ERROR{C.RESET}"
    else:
        badge = f"{C.DIM}{status}{C.RESET}"

    print(f"\n  {C.DIM}┌─ Response ({'─' * 44}){C.RESET}")
    print(f"  {C.DIM}│{C.RESET} {C.BOLD}Status:{C.RESET}  {badge}")
    if error_code:
        print(f"  {C.DIM}│{C.RESET} {C.BOLD}Code:{C.RESET}    {C.RED}{error_code}{C.RESET}")
    print(f"  {C.DIM}│{C.RESET} {C.BOLD}Latency:{C.RESET} {elapsed_ms}ms")
    if token:
        short_token = token[:30] + "..." if len(token) > 30 else token
        print(f"  {C.DIM}│{C.RESET} {C.BOLD}Token:{C.RESET}   {C.YELLOW}{short_token}{C.RESET}")
    print(f"  {C.DIM}│{C.RESET}")

    # Reply content
    reply_lines = reply.split("\n")
    for line in reply_lines:
        color = C.GREEN if status == "ok" else (C.YELLOW if status == "pending" else C.RED)
        print(f"  {C.DIM}│{C.RESET}   {color}{line}{C.RESET}")

    print(f"  {C.DIM}└{'─' * 58}{C.RESET}")

    # JSON dump
    print(f"\n  {C.DIM}JSON:{C.RESET}")
    json_str = json.dumps(result, indent=2, ensure_ascii=False)
    for line in json_str.split("\n"):
        print(f"  {C.DIM}  {line}{C.RESET}")
    print()


def _print_session_info(agent, session_id):
    """In thông tin session hiện tại."""
    session = agent._sessions.dump(session_id)
    if not session:
        print(f"  {C.YELLOW}Session '{session_id}' chưa tồn tại.{C.RESET}\n")
        return

    print(f"\n  {C.CYAN}{C.BOLD}Session Info{C.RESET}")
    print(f"  {C.DIM}{'─' * 50}{C.RESET}")
    print(f"  Session ID:  {session.get('session_id', '?')}")
    print(f"  User ID:     {session.get('user_id', '?')}")
    print(f"  Created:     {session.get('created_at', '?')}")
    print(f"  Last Active: {session.get('last_active', '?')}")
    print(f"  Messages:    {len(session.get('messages', []))}")
    print(f"  Total Turns: {session.get('metadata', {}).get('total_turns', 0)}")

    pending = session.get("pending_confirmation", {})
    if pending.get("token"):
        print(f"  {C.YELLOW}Pending:     {pending.get('action', '?')} — expires {pending.get('expires_at', '?')}{C.RESET}")
    else:
        print(f"  Pending:     None")

    msgs = session.get("messages", [])
    if msgs:
        print(f"\n  {C.DIM}Recent messages:{C.RESET}")
        for m in msgs[-6:]:  # Last 6
            role = m.get("role", "?")
            content = m.get("content", "")[:80]
            icon = "👤" if role == "user" else "🤖"
            print(f"    {icon} {C.DIM}[{role}]{C.RESET} {content}{'...' if len(m.get('content', '')) > 80 else ''}")
    print()


def _print_cache_stats(agent):
    """In cache stats."""
    stats = agent._cache.stats()
    print(f"\n  {C.CYAN}{C.BOLD}Cache Stats{C.RESET}")
    print(f"  {C.DIM}{'─' * 50}{C.RESET}")
    print(f"  Hits:      {stats.get('hits', 0)}")
    print(f"  Misses:    {stats.get('misses', 0)}")
    print(f"  Entries:   {stats.get('total_entries', 0)}")
    print(f"  Hit Rate:  {stats.get('hit_rate_pct', 0)}%")
    print()


def _print_cart():
    """In mock cart data."""
    print(f"\n  {C.CYAN}{C.BOLD}Mock Cart Data{C.RESET}")
    print(f"  {C.DIM}{'─' * 50}{C.RESET}")
    if not MOCK_CART:
        print(f"  {C.DIM}(trống){C.RESET}")
    else:
        for user_id, items in MOCK_CART.items():
            print(f"  User: {user_id}")
            for item in items:
                print(f"    - {item['product_id']} x{item['quantity']}")
    print()


# ══════════════════════════════════════════════════════════════════
# Main loop
# ══════════════════════════════════════════════════════════════════

def main():
    # ── Setup mocks ──
    if not args.live:
        _setup_grpc_mocks()
    if args.no_llm:
        _setup_llm_mock()

    # ── Init agent ──
    from agent.copilot_agent import CopilotAgent
    agent = CopilotAgent()

    session_id = str(uuid.uuid4())
    user_id = args.user_id
    pending_token = None

    _print_banner()

    print(f"  {C.GREEN}🤖 Xin chào! Tôi là trợ lý mua sắm của TechX Corp.{C.RESET}")
    print(f"  {C.GREEN}   Hãy hỏi tôi về sản phẩm, đánh giá, hoặc thêm hàng vào giỏ!{C.RESET}")
    print()

    while True:
        try:
            user_input = input(f"  {C.BLUE}{C.BOLD}Bạn ▶{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n  {C.DIM}Bye! 👋{C.RESET}\n")
            break

        if not user_input:
            continue

        # ── Lệnh đặc biệt ──
        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "/q"):
            print(f"\n  {C.DIM}Bye! 👋{C.RESET}\n")
            break

        elif cmd == "/new":
            session_id = str(uuid.uuid4())
            pending_token = None
            print(f"  {C.CYAN}🔄 Session mới: {session_id[:8]}...{C.RESET}\n")
            continue

        elif cmd == "/session":
            _print_session_info(agent, session_id)
            continue

        elif cmd == "/cache":
            _print_cache_stats(agent)
            continue

        elif cmd == "/cart":
            _print_cart()
            continue

        elif cmd == "/confirm":
            if not pending_token:
                print(f"  {C.YELLOW}Không có hành động nào đang chờ xác nhận.{C.RESET}\n")
                continue
            t0 = time.monotonic()
            result = agent.confirm(session_id=session_id, token=pending_token)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _print_result(result, elapsed_ms)
            pending_token = None
            continue

        elif cmd == "/cancel":
            if not pending_token:
                print(f"  {C.YELLOW}Không có hành động nào đang chờ huỷ.{C.RESET}\n")
                continue
            agent._sessions.clear_pending(session_id)
            pending_token = None
            print(f"  {C.RED}✖ Đã huỷ hành động đang chờ.{C.RESET}\n")
            continue

        # ── Chat bình thường ──
        t0 = time.monotonic()
        result = agent.chat(
            session_id=session_id,
            user_id=user_id,
            user_message=user_input,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        _print_result(result, elapsed_ms)

        # Track pending token
        if result.get("status") == "pending" and result.get("token"):
            pending_token = result["token"]
            print(f"  {C.YELLOW}💡 Gõ /confirm để xác nhận, hoặc /cancel để huỷ.{C.RESET}\n")

    # ── Cleanup mocks ──
    for p in _patches:
        try:
            p.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
