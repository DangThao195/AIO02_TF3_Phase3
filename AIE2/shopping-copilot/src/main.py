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

# ── LangGraph graph (lazy init) ──
_graph = None

def _get_graph():
    """Lazy init LangGraph graph."""
    global _graph
    if _graph is None:
        if args.mock or os.getenv("MOCK_EKS") == "true":
            logger.info("[MAIN] Initializing with EKS Microservices Mocked!")
            from tests.test_interactive import _setup_grpc_mocks
            _setup_grpc_mocks()

        from src.graph.main_graph import build_graph
        _graph = build_graph()
        logger.info("[MAIN] LangGraph graph initialized")
    return _graph


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


# ── Step labels mapping (node_key → display name) ──
_STEP_LABELS: dict[str, str] = {
    "InputGuard": "Kiểm tra đầu vào",
    "IntentClassifier": "Phân loại ý định",
    "EntityExtractor": "Trích xuất thông tin",
    "ResolveProduct": "Tra cứu sản phẩm",
    "Router": "Định tuyến",
    "AnswerGenerator": "Tạo câu trả lời",
    "LLMNode": "AI Agent",
    "ToolsNode": "Thực thi công cụ",
    "GetCart": "Xem giỏ hàng",
    "ToolExecutor": "Công cụ",
}

def _build_steps(state: dict) -> List[StepInfo]:
    durations = state.get("node_durations", {})
    errors = state.get("errors", [])
    steps: List[StepInfo] = []

    for node_key, ms in durations.items():
        base = node_key.split(":")[0]
        action = _STEP_LABELS.get(base, base)

        if node_key.startswith("ToolExecutor:"):
            tool_name = node_key.split(":", 1)[1]
            action = f"Công cụ: {tool_name}"
        elif node_key.startswith("Aggregate"):
            action = "Tổng hợp kết quả"

        status = "ok"
        detail = ""
        for err in errors:
            if err.get("node", "").startswith(base):
                status = "error"
                detail = err.get("error", "")[:100]
                break

        if base == "ResolveProduct" and status == "ok":
            pname = state.get("resolved_product_name")
            if pname:
                detail = f"Đã tìm thấy: {pname}"
            elif state.get("entities", {}).get("product_name"):
                detail = "Không tìm thấy sản phẩm"
        elif base == "InputGuard" and status == "ok":
            violations = state.get("guardrail_violations", [])
            if violations:
                status = "block"
                detail = violations[0].get("type", "Violation")

        steps.append(StepInfo(
            action=action,
            status=status,
            detail=detail,
            duration_ms=ms,
        ))

    return steps


class ConfirmRequest(BaseModel):
    session_id: str = Field(..., description="ID phiên chat")
    token: str = Field(..., description="HMAC token từ agent")

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

    Luôn dùng LangGraph StateGraph path.
    """
    from langchain_core.messages import HumanMessage

    logger.info(
        "[API] /api/chat | session=%s | user=%s | msg=%.80s",
        req.session_id, req.user_id, req.message,
    )

    graph = _get_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    try:
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=req.message)],
                "session_id": req.session_id,
                "user_id": req.user_id,
                "trace_id": str(uuid.uuid4()),
                "intent": "agent",
                "intent_source": "default",
                "entities": {},
                "candidate_products": [],
                "tool_results": {},
                "final_answer": "",
                "pending_workflows": [],
                "current_workflow_index": 0,
                "workflow_results": [],
                "pending_action": None,
                "confirmed": False,
                "errors": [],
                "retry_count": 0,
                "node_retry_counts": {},
                "guardrail_violations": [],
                "node_durations": {},
            },
            config=config,
        )
    except Exception as e:
        logger.error("[API] LangGraph error | session=%s | err=%s", req.session_id, e)
        return ChatResponse(
            status="error",
            reply=f"Lỗi hệ thống: {str(e)[:200]}",
            session_id=req.session_id,
        )

    logger.info(
        "[API] LangGraph response | session=%s | violations=%d",
        req.session_id, len(result.get("guardrail_violations", []))
    )

    # Nếu có guardrail violation → trả lỗi
    violations = result.get("guardrail_violations", [])
    if violations:
        violation = violations[0]
        return ChatResponse(
            status="error",
            reply=violation.get("detail", "Yêu cầu bị từ chối."),
            session_id=req.session_id,
            steps=_build_steps(result),
        )

    # Nếu confirmation pending
    pending_action = result.get("pending_action")
    if pending_action and not result.get("confirmed", False):
        return ChatResponse(
            status="pending",
            reply=pending_action.get("message", "Vui lòng xác nhận hành động."),
            token=pending_action.get("token"),
            session_id=req.session_id,
            steps=_build_steps(result),
        )

    return ChatResponse(
        status="ok",
        reply=result.get("final_answer", ""),
        session_id=req.session_id,
        steps=_build_steps(result),
    )


@app.post("/api/confirm", response_model=ConfirmResponse)
async def api_confirm(req: ConfirmRequest):
    """
    Xác nhận hành động ghi đang chờ (user bấm nút Xác nhận).
    Cần truyền token nhận được từ /api/chat khi status=pending.

    Dùng LangGraph Command(resume) để resume từ checkpoint.
    """
    from src.guardrails.confirmation import verify_confirmation_token
    from langgraph.types import Command

    logger.info("[API] /api/confirm | session=%s", req.session_id)

    # Verify HMAC token trước
    is_valid, action_data = verify_confirmation_token(req.token)
    if not is_valid:
        return ConfirmResponse(status="error", reply="Token không hợp lệ hoặc đã hết hạn.")

    graph = _get_graph()
    config = {"configurable": {"thread_id": req.session_id}}

    try:
        # Resume graph từ checkpoint với confirmed=True
        result = await graph.ainvoke(
            Command(resume={"confirmed": True}),
            config=config,
        )
        return ConfirmResponse(
            status="ok",
            reply=result.get("final_answer", "✅ Đã xác nhận."),
        )
    except Exception as e:
        logger.error("[API] LangGraph confirm error | session=%s | err=%s", req.session_id, e)
        return ConfirmResponse(
            status="error",
            reply=f"Lỗi xác nhận: {str(e)[:200]}",
        )


# ── Debug endpoints ──

@app.get("/debug/session/{session_id}")
def debug_session(session_id: str):
    """Tra cứu session memory từ LangGraph checkpoint."""
    from src.memory.store import CacheStore
    return {
        "session_id": session_id,
        "note": "LangGraph dùng MemorySaver checkpoint — không có session memory riêng",
    }


@app.get("/debug/cache")
def debug_cache():
    """Cache store stats và entries."""
    from src.memory.store import CacheStore
    cs = CacheStore()
    return cs.dump() if hasattr(cs, "dump") else {"note": "CacheStore available"}


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
