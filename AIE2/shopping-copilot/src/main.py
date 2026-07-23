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
import time as _time
import uuid
from collections import defaultdict

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

# ── Logging setup (file + console, JSON + plain) ──
from src.logging_config import setup_logging, request_context
setup_logging()
logger = logging.getLogger("api")

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

# ── Observability metrics ──
_metrics = {
    "latencies": defaultdict(list),
    "gate_decisions": defaultdict(int),
    "hallucination": defaultdict(int),
    "tool_results": defaultdict(int),
}

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = _time.time()
    trace_id = str(uuid.uuid4())
    ctx = {
        "session_id": request.headers.get("X-Session-Id", request.query_params.get("session_id", "")),
        "trace_id": trace_id,
        "user_id": request.headers.get("X-User-Id", request.query_params.get("user_id", "anonymous")),
    }
    token = request_context.set(ctx)
    try:
        response = await call_next(request)
        latency_ms = (_time.time() - start) * 1000
        _metrics["latencies"][request.url.path].append(latency_ms)
        logger.info("[API] %s %s → %d (%.0fms) trace=%s",
                     request.method, request.url.path, response.status_code, latency_ms, trace_id)
        return response
    except Exception as e:
        latency_ms = (_time.time() - start) * 1000
        logger.error("[API] %s %s → 500 (%.0fms) trace=%s | %s",
                      request.method, request.url.path, latency_ms, trace_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "reply": "Internal server error."})
    finally:
        request_context.reset(token)

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


# ── PostgreSQL pool warmup ──
@app.on_event("startup")
async def warmup_db_pool():
    """Khởi tạo PostgreSQL pool ngay khi server start, tránh lazy init 5s trong request path."""
    try:
        from src.database.connect import init_pool
        init_pool()
        logger.info("[MAIN] PostgreSQL pool warmup done")
    except Exception as e:
        logger.warning("[MAIN] PostgreSQL pool warmup failed (will lazy init): %s", e)


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
    # v3.2 nodes
    "input_guard": "Kiểm tra đầu vào",
    "task_graph_builder": "Lập kế hoạch",
    "plan_validity_gate": "Kiểm tra kế hoạch",
    "tool_executor": "Thực thi công cụ",
    "reflection": "Phản ánh kết quả",
    "response_verifier": "Xác minh câu trả lời",
    "hallucination_guard": "Kiểm tra độ chính xác",
    "fallback_generator": "Tạo câu trả lời dự phòng",
    "answer_generator": "Tạo câu trả lời",
    "confirmation": "Xác nhận hành động",
    # v2 legacy (kept for backward compat)
    "InputGuard": "Kiểm tra đầu vào",
    "IntentClassifier": "Phân loại ý định",
    "EntityExtractor": "Trích xuất thông tin",
    "ResolveProduct": "Tra cứu sản phẩm",
    "Router": "Định tuyến",
    "Confirmation": "Xác nhận hành động",
    "ResponseEditor": "Biên tập câu trả lời",
    "AnswerGenerator": "Tạo câu trả lời",
    "LLMNode": "AI Agent",
    "ToolsNode": "Thực thi công cụ",
    "GetCart": "Xem giỏ hàng",
    "AddToCart": "Thêm vào giỏ",
    "ToolExecutor": "Công cụ",
}


def _build_steps(state: dict) -> List[StepInfo]:
    durations = state.get("node_durations", {})
    errors = state.get("errors", [])
    violations = state.get("guardrail_violations", [])
    tool_results = state.get("tool_results", {})
    interrupts = state.get("__interrupt__", [])

    # Build error map: node_key → error_detail
    error_map: dict[str, str] = {}
    for err in errors:
        n = err.get("node", "")
        error_map[n] = err.get("error", "")

    # Build tool error map: tool_name → error_detail
    tool_error_map: dict[str, str] = {}
    for key, val in tool_results.items():
        if val.get("error"):
            tool_name = key.split(":")[0]
            warn = val.get("source", "")
            tool_error_map[tool_name] = f"[{warn}] {val['error']}" if warn else val["error"]

    steps: List[StepInfo] = []

    for node_key, ms in durations.items():
        base = node_key.split(":")[0]
        action = _STEP_LABELS.get(base, base)

        # v3.2: tool_executor:tool_name
        if node_key.startswith("tool_executor:"):
            tool_name = node_key.split(":", 1)[1]
            action = f"Công cụ: {tool_name}"
        # v2 legacy
        elif node_key.startswith("ToolExecutor:"):
            tool_name = node_key.split(":", 1)[1]
            action = f"Công cụ: {tool_name}"
        elif node_key.startswith("Aggregate"):
            action = "Tổng hợp kết quả"

        status = "ok"
        detail = ""

        # Match error by exact node_key first, then base
        err_detail = error_map.get(node_key) or error_map.get(base)
        if err_detail:
            status = "error"
            detail = err_detail
        elif base in tool_error_map:
            status = "error"
            detail = tool_error_map[base]

        if base == "ResolveProduct" and status == "ok":
            pname = state.get("resolved_product_name")
            if pname:
                detail = f"Đã tìm thấy: {pname}"
            elif state.get("entities", {}).get("product_name"):
                detail = "Không tìm thấy sản phẩm"

        if base in ("Confirmation", "confirmation"):
            pending = state.get("pending_action")
            if pending:
                detail = pending.get("message", "")[:80]
            elif status == "error":
                pass
            else:
                detail = "Đã xác nhận"

        steps.append(StepInfo(
            action=action,
            status=status,
            detail=detail,
            duration_ms=ms,
        ))

    # Thêm steps cho tool_results không có trong node_durations (vd tool chạy trong subgraph)
    seen_tools = set()
    for node_key in durations:
        if node_key.startswith("ToolExecutor:"):
            seen_tools.add(node_key.split(":", 1)[1])
    for key, val in tool_results.items():
        tool_name = key.split(":")[0]
        if tool_name not in seen_tools:
            seen_tools.add(tool_name)
            result_text = str(val.get("result", ""))
            err_text = val.get("error", "")
            is_error = bool(err_text) or ("lỗi" in result_text.lower()[:10] or "error" in result_text.lower()[:10] or "unavail" in result_text.lower()[:30])
            steps.append(StepInfo(
                action=f"Công cụ: {tool_name}",
                status="error" if is_error else "ok",
                detail=(err_text or result_text)[:150],
                duration_ms=0,
            ))

    # Thêm guardrail violations nếu chưa có trong steps
    for v in violations:
        already = any(s.status == "block" for s in steps)
        if not already:
            steps.append(StepInfo(
                action="Guardrail",
                status="block",
                detail=f"{v.get('type', 'Violation')}: {v.get('detail', '')}",
                duration_ms=0,
            ))

    # Thêm interrupt step nếu graph bị suspend (ConfirmationNode chưa return)
    if interrupts:
        has_pending = any(s.status == "pending" for s in steps)
        for intr in interrupts:
            val = intr.value if hasattr(intr, "value") else intr
            if not isinstance(val, dict):
                continue
            # Thêm tool errors từ interrupt value (ConfirmationNode capture từ subgraph)
            for tool_name, err_detail in val.get("tool_errors", {}).items():
                seen_tools.add(tool_name)  # tránh duplicate
                steps.append(StepInfo(
                    action=f"Công cụ: {tool_name}",
                    status="error",
                    detail=err_detail[:150],
                    duration_ms=0,
                ))
            # Thêm pending step nếu chưa có
            if not has_pending and val.get("pending_action"):
                pa = val["pending_action"]
                steps.append(StepInfo(
                    action="Chờ xác nhận",
                    status="pending",
                    detail=pa.get("message", "")[:120],
                    duration_ms=0,
                ))

    return steps


def _log_steps(state: dict, session_id: str):
    """Log step-by-step debug info ra console."""
    durations = state.get("node_durations", {})
    errors = state.get("errors", [])
    violations = state.get("guardrail_violations", [])
    tool_results = state.get("tool_results", {})
    interrupts = state.get("__interrupt__", [])
    final_answer = state.get("final_answer", "")

    logger.info("[DEBUG] ═════════════════ Steps ═════════════════")

    # Log steps từ node_durations (parent graph nodes)
    for node_key, ms in sorted(durations.items(), key=lambda x: list(durations.keys()).index(x[0])):
        base = node_key.split(":")[0]
        label = _STEP_LABELS.get(base, base)
        if node_key.startswith("ToolExecutor:"):
            label = f"Công cụ:{node_key.split(':',1)[1]}"

        status_icon = "✓"
        err_detail = ""
        for err in errors:
            if err.get("node", "") == node_key or err.get("node", "") == base:
                status_icon = "✗"
                err_detail = f" — {err.get('error', '')[:100]}"
                break
        if not err_detail and base in tool_results:
            for k, v in tool_results.items():
                if k.startswith(base) and v.get("error"):
                    status_icon = "✗"
                    err_detail = f" — {v['error'][:100]}"
                    break

        if base == "InputGuard" and violations:
            status_icon = "⊘"
            err_detail = f" — {violations[0].get('type','')}"

        logger.info("[DEBUG]   %s %s (%dms)%s", status_icon, label, ms, err_detail)

    # Log tool_results không có trong durations (chạy trong subgraph)
    seen_tools = set()
    for nk in durations:
        if nk.startswith("ToolExecutor:"):
            seen_tools.add(nk.split(":", 1)[1])
    for key, val in tool_results.items():
        tool_name = key.split(":")[0]
        if tool_name in seen_tools:
            continue
        seen_tools.add(tool_name)
        result_text = str(val.get("result", ""))
        err_text = val.get("error", "")
        icon = "✗" if (err_text or "lỗi" in result_text.lower()[:10]) else "✓"
        detail = (err_text or result_text)[:100]
        logger.info("[DEBUG]   %s Công cụ:%s %s", icon, tool_name, f" — {detail}" if detail else "")

    if violations:
        logger.info("[DEBUG]   ⊘ Guardrail: %s", violations[0].get("detail", ""))

    if errors:
        logger.info("[DEBUG] ── Chi tiết lỗi ──")
        for e in errors:
            logger.info("[DEBUG]   [%s] %s", e.get("node", "?"), e.get("error", ""))

    if interrupts:
        for intr in interrupts:
            val = intr.value if hasattr(intr, "value") else intr
            if isinstance(val, dict):
                if val.get("tool_errors"):
                    logger.info("[DEBUG] ── Lỗi tool (trong subgraph) ──")
                    for tool, err in val["tool_errors"].items():
                        logger.info("[DEBUG]   ✗ %s: %s", tool, err[:150])
                if val.get("pending_action"):
                    pa = val["pending_action"]
                    logger.info("[DEBUG]   ⏸ Chờ xác nhận: %s", pa.get("message", "")[:120])

    if tool_results:
        err_tools = {k: v for k, v in tool_results.items() if v.get("error")}
        if err_tools:
            logger.info("[DEBUG] ── Lỗi tool ──")
            for k, v in err_tools.items():
                logger.info("[DEBUG]   [%s] %s (source=%s)", k, v["error"][:150], v.get("source", "?"))

    answer_preview = final_answer[:120].replace("\n", " ")
    logger.info("[DEBUG] ── Trả lời: %s", answer_preview if answer_preview else "(trống)")
    logger.info("[DEBUG] ═════════════════════════════════════════")


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
async def api_get_cart(user_id: str):
    """Lấy danh sách sản phẩm trong giỏ hàng (giả lập hoặc gRPC thật tuỳ theo chế độ)."""
    try:
        if not (args.mock or os.getenv("MOCK_EKS") == "true"):
            import grpc
            from src.protos import demo_pb2_grpc, demo_pb2
            from src.tools.service_config import CART_ADDR, CATALOG_ADDR
            
            loop = asyncio.get_event_loop()
            
            def _fetch():
                with grpc.insecure_channel(CART_ADDR) as channel_cart, \
                     grpc.insecure_channel(CATALOG_ADDR) as channel_cat:
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
            
            return await loop.run_in_executor(None, _fetch)
                
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
        # Chỉ gửi input mới; để checkpoint giữ lại context cũ như candidate_products,
        # pending_action và lịch sử workflow giữa các lượt chat.
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=req.message)],
                "session_id": req.session_id,
                "user_id": req.user_id,
                "trace_id": str(uuid.uuid4()),
                # Reset per-turn transient state để tránh tích lũy từ turn trước
                "tool_results": {"__reset__": True},
                "errors": ["__reset__"],
                "node_durations": {"__reset__": 0},
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

    steps = _build_steps(result)
    _log_steps(result, req.session_id)

    violations = result.get("guardrail_violations", [])
    if violations:
        violation = violations[0]
        return ChatResponse(
            status="error",
            reply=violation.get("detail", "Yêu cầu bị từ chối."),
            session_id=req.session_id,
            steps=steps,
        )

    # Kiểm tra __interrupt__ từ ConfirmationNode (graph bị suspend chờ confirm)
    interrupts = result.get("__interrupt__", [])
    if interrupts:
        interrupt_value = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        if isinstance(interrupt_value, dict):
            pending_action = interrupt_value.get("pending_action")
            if pending_action:
                return ChatResponse(
                    status="pending",
                    reply=pending_action.get("message", "Vui lòng xác nhận hành động."),
                    token=pending_action.get("token"),
                    session_id=req.session_id,
                    steps=steps,
                )

    return ChatResponse(
        status="ok",
        reply=result.get("final_answer", ""),
        session_id=req.session_id,
        steps=steps,
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
        # Resume graph từ checkpoint — interrupt() trong ConfirmationNode
        # trả về resume data, node trả về {"confirmed": True}
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


@app.get("/debug/metrics")
def debug_metrics():
    """Observability metrics."""
    return {
        "latency_p50": sorted(_metrics["latencies"].get("/api/chat", [0]))[
            len(_metrics["latencies"].get("/api/chat", [])) // 2
        ] if _metrics["latencies"].get("/api/chat") else 0,
        "hallucination": dict(_metrics["hallucination"]),
        "tool_results": dict(_metrics["tool_results"]),
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
