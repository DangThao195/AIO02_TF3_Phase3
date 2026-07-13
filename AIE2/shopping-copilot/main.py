"""
main.py — Shopping Copilot API Server

Routes:
  POST /api/chat    — gửi tin nhắn, nhận trả lời từ agent
  POST /api/confirm — xác nhận hành động ghi (sau khi user bấm nút)
  GET  /health      — health check
  GET  /            — thông tin server

Chạy local:
  py -m uvicorn main:app --reload --port 8001
  hoặc: py main.py
"""

import logging
import sys
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
        from agent.copilot_agent import CopilotAgent
        _agent = CopilotAgent()
        logger.info("[MAIN] CopilotAgent initialized")
    return _agent


# ── Request/Response models ──

class ChatRequest(BaseModel):
    message: str = Field(..., description="Tin nhắn của người dùng")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()),
                            description="ID phiên chat (tạo mới nếu không có)")
    user_id: str = Field(default="anonymous", description="ID người dùng")

class ChatResponse(BaseModel):
    status: str
    reply: str
    token: str | None = None
    session_id: str

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
        "tools_available": 3,
        "endpoints": {
            "chat": "POST /api/chat",
            "confirm": "POST /api/confirm",
            "health": "GET /health",
        },
    }


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(req: ChatRequest):
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
    result = agent.chat(
        session_id=req.session_id,
        user_id=req.user_id,
        user_message=req.message,
    )

    logger.info(
        "[API] /api/chat response | session=%s | status=%s",
        req.session_id, result.get("status")
    )

    return ChatResponse(
        status=result.get("status", "error"),
        reply=result.get("reply", "Có lỗi xảy ra."),
        token=result.get("token"),
        session_id=req.session_id,
    )


@app.post("/api/confirm", response_model=ConfirmResponse)
def api_confirm(req: ConfirmRequest):
    """
    Xác nhận hành động ghi đang chờ (user bấm nút Xác nhận).
    Cần truyền token nhận được từ /api/chat khi status=pending.
    """
    logger.info("[API] /api/confirm | session=%s", req.session_id)

    agent = _get_agent()
    result = agent.confirm(session_id=req.session_id, token=req.token)

    return ConfirmResponse(
        status=result.get("status", "error"),
        reply=result.get("reply", "Có lỗi xảy ra."),
    )


# ── Entry point ──
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    logger.info("Starting Shopping Copilot API on port %d", port)
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")
