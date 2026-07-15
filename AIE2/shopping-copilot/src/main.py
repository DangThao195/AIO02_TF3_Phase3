"""
main.py — Shopping Copilot API Server

Routes:
  POST /api/chat    — gửi tin nhắn, nhận trả lời từ agent
  POST /api/confirm — xác nhận hành động ghi (sau khi user bấm nút)
  GET  /health      — health check
  GET  /            — thông tin server

Chạy local:
  py -m uvicorn src.main:app --reload --port 8001
  hoặc: cd .. && py -m src.main
"""

import logging
import sys
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import Any, List
import argparse

# ── Parse command-line args ──
parser = argparse.ArgumentParser(description="Shopping Copilot API Server")
parser.add_argument("--mock", action="store_true", help="Chạy với gRPC mock EKS")
args, _ = parser.parse_known_args()

# ── Logging setup (JSON-friendly format) ──
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")

# ── FastAPI app ──
app = FastAPI(
    title="Shopping Copilot API",
    description="Trợ lý mua sắm AI cho TechX Corp — AIO02 TF3",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Lazy import agent (sau khi logging setup để tránh vòng import) ──
_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        if args.mock or os.getenv("MOCK_EKS") == "true":
            logger.info("[MAIN] Initializing with EKS Microservices Mocked!")
            # Import mock stubs setup
            from tests.test_interactive import _setup_grpc_mocks
            _setup_grpc_mocks()
            
        from src.agent.copilot_agent import CopilotAgent
        _agent = CopilotAgent()
        logger.info("[MAIN] CopilotAgent initialized")
    return _agent


# ── Request/Response models ──

class ChatRequest(BaseModel):
    message: str = Field(..., description="Tin nhắn của người dùng")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()),
                            description="ID phiên chat (tạo mới nếu không có)")
    user_id: str = Field(default="anonymous", description="ID người dùng")

class StepInfo(BaseModel):
    action: str
    status: str
    detail: str
    duration_ms: int

class ChatResponse(BaseModel):
    status: str
    reply: str
    session_id: str
    token: str | None = None
    steps: List[StepInfo] = []

class ConfirmRequest(BaseModel):
    session_id: str = Field(..., description="ID phiên chat")
    token: str = Field(..., description="HMAC token từ agent")
    confirmed: bool = Field(default=True, description="False khi user chọn Hủy")

class ConfirmResponse(BaseModel):
    status: str
    reply: str


# ── API Endpoints ──

@app.get("/health")
def health():
    """Health check — luôn trả 200 nếu server đang sống."""
    return {"status": "ok", "service": "shopping-copilot"}


@app.get("/")
def index():
    """Thông tin cơ bản về service."""
    return {
        "service": "Shopping Copilot API",
        "version": "1.0.0",
        "team": "AIO02 — TF3",
        "docs": "/docs",
        "chatbot": "/chatbot",
        "endpoints": {
            "chat": "POST /api/chat",
            "confirm": "POST /api/confirm",
            "health": "GET /health",
        },
    }


@app.get("/chatbot", response_class=HTMLResponse)
def chatbot():
    """Giao diện chatbot HTML với IO trace log."""
    import os
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "chatbot.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
            if args.mock or os.getenv("MOCK_EKS") == "true":
                mock_badge = '<span style="background:var(--warn-bg); border:1px solid var(--warn); color:var(--warn); font-size:11px; padding:2px 8px; border-radius:99px; font-weight:600; margin-left:6px;">MOCK EKS</span>'
                content = content.replace(
                    '<h1>Shopping <span>Copilot</span></h1>',
                    f'<h1>Shopping <span>Copilot</span>{mock_badge}</h1>'
                )
            return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>chatbot.html not found</h1>", status_code=404)


@app.get("/api/cart")
def api_get_cart(user_id: str):
    """Lấy danh sách sản phẩm trong giỏ hàng (giả lập hoặc gRPC thật tuỳ theo chế độ)."""
    try:
        if not (args.mock or os.getenv("MOCK_EKS") == "true"):
            import grpc
            from src.protos import demo_pb2_grpc, demo_pb2
            from src.tools.service_config import CART_ADDR, CATALOG_ADDR
            
            channel_cart = grpc.insecure_channel(CART_ADDR)
            channel_cat = grpc.insecure_channel(CATALOG_ADDR)
            try:
                stub_cart = demo_pb2_grpc.CartServiceStub(channel_cart)
                stub_cat = demo_pb2_grpc.ProductCatalogServiceStub(channel_cat)
                
                req = demo_pb2.GetCartRequest(user_id=user_id)
                res = stub_cart.GetCart(req)
                
                detailed_items = []
                for item in res.items:
                    p_id = item.product_id
                    try:
                        p_res = stub_cat.GetProduct(demo_pb2.GetProductRequest(id=p_id))
                        p_name = p_res.name
                        p_price = f"{p_res.price_usd.units}.{p_res.price_usd.nanos // 10000000:02d}"
                    except Exception:
                        p_name = p_id
                        p_price = "0.00"
                        
                    detailed_items.append({
                        "product_id": p_id,
                        "name": p_name,
                        "price": p_price,
                        "quantity": item.quantity
                    })
                return {"user_id": user_id, "items": detailed_items}
            finally:
                channel_cart.close()
                channel_cat.close()
                
        # Fallback: Trả về mock data
        from tests.test_interactive import MOCK_CART, MOCK_PRODUCTS
        items = MOCK_CART.get(user_id, [])
        prod_map = {p["id"]: p for p in MOCK_PRODUCTS}
        detailed_items = []
        for item in items:
            p_id = item["product_id"]
            p_info = prod_map.get(p_id, {"name": p_id, "price": "0.00"})
            detailed_items.append({
                "product_id": p_id,
                "name": p_info.get("name", p_id),
                "price": p_info.get("price", "0.00"),
                "quantity": item["quantity"]
            })
        return {"user_id": user_id, "items": detailed_items}
    except Exception as e:
        return {"user_id": user_id, "items": [], "error": str(e)}


@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    """
    Gửi tin nhắn đến Shopping Copilot và nhận câu trả lời.

    - **status = ok**: có câu trả lời
    - **status = pending**: cần xác nhận hành động ghi (dùng token để confirm)
    - **status = error**: có lỗi (input bị block hoặc exception)
    """
    logger.info(
        "[API] /api/chat | session=%s | user=%s | msg=%.80s",
        req.session_id, req.user_id, req.message
    )

    agent = _get_agent()
    result = await agent.chat(
        session_id=req.session_id,
        user_id=req.user_id,
        user_message=req.message,
    )

    logger.info(
        "[API] /api/chat response | session=%s | status=%s",
        req.session_id, result.get("status")
    )

    steps_data = result.get("steps", [])
    steps = [StepInfo(**s) for s in steps_data] if steps_data else []

    return ChatResponse(
        status=result.get("status", "error"),
        reply=result.get("reply", "Có lỗi xảy ra."),
        token=result.get("token"),
        session_id=req.session_id,
        steps=steps,
    )


@app.post("/api/confirm", response_model=ConfirmResponse)
async def api_confirm(req: ConfirmRequest):
    """
    Xác nhận hành động ghi đang chờ (user bấm nút Xác nhận).
    Cần truyền token nhận được từ /api/chat khi status=pending.
    """
    logger.info("[API] /api/confirm | session=%s", req.session_id)

    agent = _get_agent()
    result = await agent.confirm(session_id=req.session_id, token=req.token, confirmed=req.confirmed)

    return ConfirmResponse(
        status=result.get("status", "error"),
        reply=result.get("reply", "Có lỗi xảy ra."),
    )


# ── Debug endpoints (memory inspection) ──

@app.get("/debug/session/{session_id}")
def debug_session(session_id: str):
    """Tra cứu session memory."""
    agent = _get_agent()
    data = agent.sessions.dump(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session không tồn tại")
    return data


@app.get("/debug/sessions")
def debug_sessions():
    """Danh sách tất cả session đang active."""
    agent = _get_agent()
    return agent.sessions.dump_all()


@app.get("/debug/cache")
def debug_cache():
    """Cache store stats và entries."""
    agent = _get_agent()
    return agent.cache_store.dump()


@app.get("/debug/ratelimit")
def debug_ratelimit():
    """Rate limiter state."""
    from src.guardrails.rate_limiter import rate_limiter as rl
    with rl._lock:
        return {
            "config": {
                "max_per_minute": rl.max_per_minute,
                "max_per_day": rl.max_per_day,
                "max_tokens_per_day": rl.max_tokens_per_day,
            },
            "active_users": len(rl._requests),
            "users": {
                uid: {
                    "requests_last_24h": len(ts_list),
                    "tokens_today": rl._daily_tokens.get(uid, 0),
                }
                for uid, ts_list in rl._requests.items()
            },
        }


# ── Entry point ──
if __name__ == "__main__":
    import uvicorn
    # Đảm bảo thư mục cha chứa 'src' được thêm vào sys.path để uvicorn import được 'src.main:app'
    import sys
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
        
    port = int(os.getenv("PORT", "8001"))
    mode_str = "MOCK" if (args.mock or os.getenv("MOCK_EKS") == "true") else "LIVE"
    logger.info("Starting Shopping Copilot API [%s] on port %d", mode_str, port)
    uvicorn.run("src.main:app", host="0.0.0.0", port=port, reload=False, log_level="info")
