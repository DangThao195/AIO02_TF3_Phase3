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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from typing import Any, List
import argparse

# ── Parse command-line args ──
parser = argparse.ArgumentParser(description="Shopping Copilot API Server")
parser.add_argument("--mock", action="store_true", help="Chạy với gRPC mock EKS")
parser.add_argument(
    "--clean-cache",
    action="store_true",
    help="Xóa cache khi start (chỉ dùng cho testing)",
)
args, _ = parser.parse_known_args()

# Check environment variable for clean-cache (when run via uvicorn)
_CLEAN_CACHE = args.clean_cache or os.getenv("CLEAN_CACHE", "").lower() in [
    "true",
    "1",
    "yes",
]

# ── Logging setup (Console + FileHandler .txt) ──
file_handler = logging.FileHandler("uvicorn_execution.txt", mode="w", encoding="utf-8")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)

logging.basicConfig(
    level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout), file_handler]
)
logger = logging.getLogger("main")

# ── FastAPI app ──
app = FastAPI(
    title="Shopping Copilot API",
    description="Trợ lý mua sắm AI cho TechX Corp — AIO02 TF3",
    version="1.0.0",
    docs_url="/docs",
)

# FIX #7: Lock down CORS origins from env var in production
_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
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

        # Clean cache if flag is set (for testing only)
        if _CLEAN_CACHE:
            logger.warning(
                "[MAIN] CLEAN_CACHE=true: Clearing all caches (TESTING MODE)"
            )
            try:
                # Clear GenAI cache
                from src.memory.genai_cache import get_genai_cache_store

                genai_cache = get_genai_cache_store()
                if hasattr(genai_cache, "_store"):
                    genai_cache._store.clear()
                    genai_cache._entity_index.clear()
                    genai_cache._stats = {"hits": 0, "misses": 0, "invalidations": 0}
                    if hasattr(genai_cache, "_save"):
                        genai_cache._save()
                    logger.info("[MAIN] GenAI cache cleared")

                # Clear tool cache
                if hasattr(_agent, "_cache"):
                    _agent._cache._store.clear()
                    _agent._cache._stats = {"hits": 0, "misses": 0}
                    if hasattr(_agent._cache, "_save"):
                        _agent._cache._save()
                    logger.info("[MAIN] Tool cache cleared")

            except Exception as e:
                logger.error(f"[MAIN] Failed to clear cache: {e}")

    return _agent


# ── Request/Response models ──


class ChatRequest(BaseModel):
    message: str = Field(..., description="Tin nhắn của người dùng")
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="ID phiên chat (tạo mới nếu không có)",
    )
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
    intent: dict | None = None
    evidence: dict | None = None
<<<<<<< HEAD
    request_id: str = ""
=======
    cache: str = "miss"  # MANDATE #23: Cache hit/miss flag

>>>>>>> mandate23

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
        "cache_manager": "/cache-manager",
        "endpoints": {
            "chat": "POST /api/chat",
            "confirm": "POST /api/confirm",
            "health": "GET /health",
            "traces": "GET /api/traces/{request_id}",
            "trace_summary": "GET /api/traces/summary?period=24",
            "trigger_error": "POST /api/traces/trigger-error",
        },
    }


@app.get("/chatbot", response_class=HTMLResponse)
def chatbot():
    """Giao diện chatbot HTML với IO trace log."""
    import os

    html_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "static", "chatbot.html"
    )
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
            if args.mock or os.getenv("MOCK_EKS") == "true":
                mock_badge = '<span style="background:var(--warn-bg); border:1px solid var(--warn); color:var(--warn); font-size:11px; padding:2px 8px; border-radius:99px; font-weight:600; margin-left:6px;">MOCK EKS</span>'
                content = content.replace(
                    "<h1>Shopping <span>Copilot</span></h1>",
                    f"<h1>Shopping <span>Copilot</span>{mock_badge}</h1>",
                )
            return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>chatbot.html not found</h1>", status_code=404)


@app.get("/cache-manager", response_class=HTMLResponse)
def cache_manager():
    """Giao diện quản lý cache và memory với tính năng đầy đủ."""
    html = """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Cache Manager</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#f1f5f9;line-height:1.6}
.container{max-width:1600px;margin:0 auto;padding:20px}
.header{background:#1e293b;padding:24px;border-radius:8px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 6px rgba(0,0,0,.3)}
.header h1{font-size:24px;display:flex;align-items:center;gap:12px}
.header-actions{display:flex;gap:12px}
.btn{padding:10px 20px;border:none;border-radius:6px;font-weight:600;cursor:pointer;transition:all .2s;font-size:14px}
.btn-primary{background:#3b82f6;color:#fff}
.btn-primary:hover{background:#2563eb}
.btn-danger{background:#ef4444;color:#fff}
.btn-danger:hover{background:#dc2626}
.btn-sm{padding:6px 12px;font-size:12px}
.grid{display:grid;grid-template-columns:320px 1fr;gap:24px}
.sidebar,.main{background:#1e293b;padding:20px;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,.3)}
.sidebar{max-height:calc(100vh - 200px);overflow-y:auto}
.sidebar-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid #334155}
.sidebar-header h3{font-size:16px;font-weight:700}
.badge{background:#334155;color:#94a3b8;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700}
.search-box{width:100%;padding:10px;background:#334155;border:1px solid #475569;border-radius:6px;color:#f1f5f9;margin-bottom:12px;font-size:13px}
.search-box:focus{outline:none;border-color:#3b82f6}
.user-list{display:flex;flex-direction:column;gap:6px}
.user-item{padding:12px;background:#334155;border-radius:6px;cursor:pointer;transition:all .2s;border-left:3px solid transparent}
.user-item:hover{background:#475569;transform:translateX(4px)}
.user-item.active{border-left-color:#3b82f6;background:#475569}
.user-id{font-weight:600;font-size:13px;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.user-meta{font-size:11px;color:#94a3b8;display:flex;gap:8px;flex-wrap:wrap}
.user-meta span{background:#1e293b;padding:2px 6px;border-radius:4px}
.tabs{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid #334155;overflow-x:auto}
.tab{padding:12px 20px;background:none;border:none;color:#94a3b8;font-weight:600;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-2px;transition:all .2s;font-size:14px;white-space:nowrap}
.tab:hover{color:#f1f5f9;background:#334155}
.tab.active{color:#3b82f6;border-bottom-color:#3b82f6}
.tab-content{display:none;animation:fadeIn .3s}
.tab-content.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.empty-state{text-align:center;padding:80px 20px;color:#64748b;font-size:15px}
.empty-state-icon{font-size:48px;margin-bottom:16px;opacity:.5}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:#334155;padding:20px;border-radius:8px;border-left:4px solid #3b82f6}
.stat-label{font-size:12px;color:#94a3b8;margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px}
.stat-value{font-size:32px;font-weight:700;color:#f1f5f9}
.stat-subvalue{font-size:13px;color:#94a3b8;margin-top:4px}
.session-list,.cache-list{display:flex;flex-direction:column;gap:12px}
.session-card,.cache-card{background:#334155;padding:16px;border-radius:8px;transition:all .2s}
.session-card:hover,.cache-card:hover{background:#475569;transform:translateY(-2px)}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #475569}
.session-id,.cache-key{font-weight:600;font-size:13px;font-family:monospace;color:#94a3b8}
.card-actions{display:flex;gap:6px}
.messages{display:flex;flex-direction:column;gap:8px;max-height:300px;overflow-y:auto;padding:8px;background:#1e293b;border-radius:6px}
.message{padding:10px 12px;border-radius:6px;font-size:13px;line-height:1.5}
.message.user{background:#1e40af;margin-left:15%}
.message.assistant{background:#475569;margin-right:15%}
.message-role{font-weight:700;font-size:10px;text-transform:uppercase;color:#94a3b8;margin-bottom:4px;letter-spacing:.5px}
.message-content{white-space:pre-wrap;word-break:break-word}
.message-time{font-size:10px;color:#64748b;margin-top:4px}
.memory-section{background:#334155;padding:16px;border-radius:8px;margin-bottom:16px}
.memory-section h4{font-size:14px;margin-bottom:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}
.memory-items{display:flex;flex-direction:column;gap:8px}
.memory-item{background:#475569;padding:10px 12px;border-radius:6px;font-size:13px}
.memory-item-label{font-weight:600;color:#94a3b8;font-size:11px;margin-bottom:4px}
.memory-item-value{color:#f1f5f9}
.cache-meta{display:flex;gap:16px;font-size:12px;color:#94a3b8;flex-wrap:wrap}
.cache-request{font-weight:600;margin-bottom:8px;color:#f1f5f9}
.cache-reply{font-size:13px;color:#94a3b8;margin-top:8px;padding:8px;background:#1e293b;border-radius:4px;max-height:100px;overflow:auto}
.loading{text-align:center;padding:40px;color:#94a3b8}
.spinner{display:inline-block;width:40px;height:40px;border:4px solid #334155;border-top-color:#3b82f6;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.toast{position:fixed;top:20px;right:20px;background:#1e293b;color:#f1f5f9;padding:16px 24px;border-radius:8px;box-shadow:0 10px 25px rgba(0,0,0,.5);z-index:1000;animation:slideIn .3s;border-left:4px solid #3b82f6}
.toast.error{border-left-color:#ef4444}
.toast.success{border-left-color:#10b981}
@keyframes slideIn{from{transform:translateX(400px);opacity:0}to{transform:translateX(0);opacity:1}}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:#1e293b}
::-webkit-scrollbar-thumb{background:#475569;border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:#64748b}
</style>
</head><body>
<div class="container">
<div class="header">
<h1><span>🗄️</span>Cache & Memory Manager</h1>
<div class="header-actions">
<a href="/chatbot" class="btn btn-primary" style="text-decoration:none;display:inline-block">💬 Chatbot</a>
<button class="btn btn-primary" onclick="loadData()">🔄 Refresh</button>
<button class="btn btn-danger" onclick="clearAllCache()">🗑️ Clear Cache</button>
</div>
</div>
<div class="grid">
<div class="sidebar">
<div class="sidebar-header">
<h3>Users</h3>
<span class="badge" id="userCount">0</span>
</div>
<input type="text" class="search-box" id="searchBox" placeholder="🔍 Search users..." oninput="filterUsers()">
<div class="user-list" id="userList">
<div class="loading"><div class="spinner"></div></div>
</div>
</div>
<div class="main">
<div class="tabs">
<button class="tab active" data-tab="stats" onclick="switchTab('stats')">📊 Stats</button>
<button class="tab" data-tab="sessions" onclick="switchTab('sessions')">💬 Sessions</button>
<button class="tab" data-tab="memory" onclick="switchTab('memory')">🧠 Memory</button>
<button class="tab" data-tab="cache" onclick="switchTab('cache')">⚡ Cache</button>
</div>
<div id="statsTab" class="tab-content active">
<div class="stats-grid" id="statsGrid">
<div class="loading"><div class="spinner"></div></div>
</div>
</div>
<div id="sessionsTab" class="tab-content">
<div class="empty-state"><div class="empty-state-icon">💬</div>Select a user to view sessions</div>
</div>
<div id="memoryTab" class="tab-content">
<div class="empty-state"><div class="empty-state-icon">🧠</div>Select a user to view memory</div>
</div>
<div id="cacheTab" class="tab-content">
<div class="empty-state"><div class="empty-state-icon">⚡</div>Select a user to view cache</div>
</div>
</div>
</div>
</div>
<script>
let DATA={users:[],sessions:{},cache:{},stats:{}};
let selectedUser=null;
let allUsers=[];

async function loadData(){
showToast('Loading data...','');
try{
const [users,cache]=await Promise.all([
fetch('/api/v1/users').then(r=>r.json()),
fetch('/debug/genai_cache').then(r=>r.json())
]);
DATA={users:users.users||[],cache:cache};
allUsers=DATA.users;
renderUserList();
renderStats();
showToast('Data loaded successfully','success');
}catch(e){
showToast('Error: '+e.message,'error');
}
}

function renderUserList(){
const ul=document.getElementById('userList');
const users=allUsers;
document.getElementById('userCount').textContent=users.length;
if(!users.length){
ul.innerHTML='<div class="empty-state">No users found</div>';
return;
}
ul.innerHTML=users.map(u=>`
<div class="user-item" onclick="selectUser('${u.user_id}')" data-user-id="${u.user_id}">
<div class="user-id" title="${u.user_id}">${u.user_id}</div>
<div class="user-meta">
<span>📅 ${u.total_sessions}s</span>
<span>💬 ${u.total_messages}m</span>
<span>⚙️ ${u.preferences_count}p</span>
</div>
</div>
`).join('');
}

function filterUsers(){
const q=document.getElementById('searchBox').value.toLowerCase();
allUsers=DATA.users.filter(u=>u.user_id.toLowerCase().includes(q));
renderUserList();
}

async function selectUser(uid){
selectedUser=uid;
document.querySelectorAll('.user-item').forEach(el=>{
el.classList.toggle('active',el.dataset.userId===uid);
});
showToast(`Loading ${uid}...`,'');
try{
const [sessions,memory]=await Promise.all([
fetch(`/api/v1/user/${uid}/sessions`).then(r=>r.json()),
fetch(`/debug/longterm/${uid}`).then(r=>r.json())
]);
renderUserSessions(sessions.sessions);
renderUserMemory(memory);
renderUserCache(uid);
}catch(e){
showToast('Error: '+e.message,'error');
}
}

function renderUserSessions(sessions){
const tab=document.getElementById('sessionsTab');
const entries=Object.entries(sessions);
if(!entries.length){
tab.innerHTML='<div class="empty-state"><div class="empty-state-icon">💬</div>No sessions found</div>';
return;
}
tab.innerHTML='<div class="session-list">'+entries.map(([sid,s])=>`
<div class="session-card">
<div class="card-header">
<div class="session-id">${sid.slice(0,24)}...</div>
<div class="card-actions">
<button class="btn btn-danger btn-sm" onclick="deleteSession('${sid}')">🗑️ Delete</button>
</div>
</div>
<div class="messages">${(s.messages||[]).slice(-5).map(m=>`
<div class="message ${m.role}">
<div class="message-role">${m.role}</div>
<div class="message-content">${escapeHtml(m.content.slice(0,200))}${m.content.length>200?'...':''}</div>
<div class="message-time">${new Date(m.timestamp).toLocaleString()}</div>
</div>
`).join('')}</div>
</div>
`).join('')+'</div>';
}

function renderUserMemory(mem){
const tab=document.getElementById('memoryTab');
tab.innerHTML=`
<div class="memory-section">
<h4>📌 Preferences</h4>
<div class="memory-items">
${(mem.preferences||[]).map(p=>`
<div class="memory-item">
<div class="memory-item-label">${p.type}</div>
<div class="memory-item-value">${p.value} (${(p.confidence*100).toFixed(0)}%)</div>
</div>
`).join('')||'<div style="color:#64748b;font-size:13px;padding:8px">No preferences</div>'}
</div>
</div>
<div class="memory-section">
<h4>💡 Facts</h4>
<div class="memory-items">
${(mem.facts||[]).map(f=>`
<div class="memory-item">
<div class="memory-item-value">${f.fact}</div>
</div>
`).join('')||'<div style="color:#64748b;font-size:13px;padding:8px">No facts</div>'}
</div>
</div>
<div class="memory-section">
<h4>📊 Interaction Summary</h4>
<div class="memory-items">
<div class="memory-item">
<div class="memory-item-label">Total Sessions</div>
<div class="memory-item-value">${mem.interaction_summary.total_sessions}</div>
</div>
<div class="memory-item">
<div class="memory-item-label">Total Messages</div>
<div class="memory-item-value">${mem.interaction_summary.total_messages}</div>
</div>
<div class="memory-item">
<div class="memory-item-label">Common Topics</div>
<div class="memory-item-value">${(mem.interaction_summary.common_topics||[]).join(', ')||'None'}</div>
</div>
</div>
</div>
`;
}

function renderUserCache(uid){
const tab=document.getElementById('cacheTab');
const entries=Object.entries(DATA.cache.entries||{}).filter(([k,v])=>v.user_id===uid);
if(!entries.length){
tab.innerHTML='<div class="empty-state"><div class="empty-state-icon">⚡</div>No cache entries</div>';
return;
}
tab.innerHTML='<div class="cache-list">'+entries.map(([k,e])=>`
<div class="cache-card">
<div class="card-header">
<div class="cache-key">${k.slice(-16)}</div>
</div>
<div class="cache-request">"${escapeHtml(e.request)}"</div>
<div class="cache-meta">
<span>👁️ Hits: ${e.hit_count||0}</span>
<span>📅 ${new Date(e.cached_at).toLocaleString()}</span>
<span>⏱️ Expires: ${new Date(e.expires_at).toLocaleString()}</span>
</div>
<div class="cache-reply">${escapeHtml(e.reply.slice(0,150))}...</div>
</div>
`).join('')+'</div>';
}

function renderStats(){
const sg=document.getElementById('statsGrid');
const totalCache=Object.keys(DATA.cache.entries||{}).length;
const stats=DATA.cache.stats||{};
sg.innerHTML=`
<div class="stat-card">
<div class="stat-label">Total Users</div>
<div class="stat-value">${DATA.users.length}</div>
</div>
<div class="stat-card">
<div class="stat-label">Active Sessions</div>
<div class="stat-value">${DATA.users.reduce((s,u)=>s+u.active_sessions,0)}</div>
</div>
<div class="stat-card">
<div class="stat-label">Cache Entries</div>
<div class="stat-value">${totalCache}</div>
<div class="stat-subvalue">Hits: ${stats.hits_exact||0} | Misses: ${stats.misses||0}</div>
</div>
<div class="stat-card">
<div class="stat-label">Cache Hit Rate</div>
<div class="stat-value">${stats.hit_rate_pct||0}%</div>
<div class="stat-subvalue">Semantic: ${stats.semantic_hit_rate_pct||0}%</div>
</div>
`;
}

function switchTab(name){
document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
document.querySelectorAll('.tab-content').forEach(tc=>tc.classList.remove('active'));
document.getElementById(name+'Tab').classList.add('active');
}

async function clearAllCache(){
if(!confirm('Clear all GenAI cache? This cannot be undone.'))return;
try{
await fetch('/api/v1/cache/clear',{method:'POST'});
showToast('Cache cleared successfully','success');
loadData();
}catch(e){
showToast('Error: '+e.message,'error');
}
}

async function deleteSession(sid){
if(!confirm(`Delete session ${sid.slice(0,8)}...?`))return;
try{
await fetch(`/api/v1/session/${sid}`,{method:'DELETE'});
showToast('Session deleted','success');
selectUser(selectedUser);
}catch(e){
showToast('Error: '+e.message,'error');
}
}

function escapeHtml(text){
const div=document.createElement('div');
div.textContent=text;
return div.innerHTML;
}

function showToast(msg,type=''){
const t=document.createElement('div');
t.className='toast '+(type||'');
t.textContent=msg;
document.body.appendChild(t);
setTimeout(()=>t.remove(),3000);
}

loadData();
</script>
</body></html>
"""
    return HTMLResponse(content=html)


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

                    detailed_items.append(
                        {
                            "product_id": p_id,
                            "name": p_name,
                            "price": p_price,
                            "quantity": item.quantity,
                        }
                    )
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
            detailed_items.append(
                {
                    "product_id": p_id,
                    "name": p_info.get("name", p_id),
                    "price": p_info.get("price", "0.00"),
                    "quantity": item["quantity"],
                }
            )
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
        req.session_id,
        req.user_id,
        req.message,
    )

    agent = _get_agent()
    result = await agent.chat(
        session_id=req.session_id,
        user_id=req.user_id,
        user_message=req.message,
    )

    logger.info(
        "[API] /api/chat response | session=%s | status=%s",
        req.session_id,
        result.get("status"),
    )

    request_id = result.get("request_id", "")
    steps_data = result.get("steps", [])
    steps = [StepInfo(**s) for s in steps_data] if steps_data else []

<<<<<<< HEAD
    return JSONResponse(
        content=ChatResponse(
            status=result.get("status", "error"),
            reply=result.get("reply", "Có lỗi xảy ra."),
            token=result.get("token"),
            session_id=req.session_id,
            steps=steps,
            intent=result.get("intent"),
            evidence=result.get("evidence"),
            request_id=request_id,
        ).model_dump(),
        headers={"X-Request-ID": request_id} if request_id else {},
=======
    return ChatResponse(
        status=result.get("status", "error"),
        reply=result.get("reply", "Có lỗi xảy ra."),
        token=result.get("token"),
        session_id=req.session_id,
        steps=steps,
        intent=result.get("intent"),
        evidence=result.get("evidence"),
        cache=result.get("cache", "miss"),  # MANDATE #23: Pass through cache flag
>>>>>>> mandate23
    )


@app.post("/api/confirm", response_model=ConfirmResponse)
async def api_confirm(req: ConfirmRequest):
    """
    Xác nhận hành động ghi đang chờ (user bấm nút Xác nhận).
    Cần truyền token nhận được từ /api/chat khi status=pending.
    """
    logger.info("[API] /api/confirm | session=%s", req.session_id)

    agent = _get_agent()
    result = await agent.confirm(
        session_id=req.session_id, token=req.token, confirmed=req.confirmed
    )

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


<<<<<<< HEAD
# ── Trace endpoints (MANDATE #24 — LLM Observability) ──

@app.get("/api/traces/{request_id}")
def get_trace(request_id: str):
    """Fetch all traces for a given request_id (full call chain)."""
    from src.telemetry import get_tracer
    store = get_tracer()._store
    traces = store.get_by_request_id(request_id)
    if not traces:
        raise HTTPException(status_code=404, detail="No traces found for this request_id")
    return {"request_id": request_id, "traces": traces}


@app.get("/api/traces/summary")
def trace_summary(period: int = 24):
    """Aggregated view of LLM call traces over given period (hours)."""
    from src.telemetry import get_tracer
    store = get_tracer()._store
    agg = store.aggregate(period_hours=period)
    return {
        "period_hours": period,
        "summary": agg,
        "total_calls": sum(s["calls"] for s in agg.values()),
        "total_cost_usd": round(sum(s["total_cost_usd"] for s in agg.values()), 6),
        "total_tokens": sum(s["total_tokens"] for s in agg.values()),
    }


@app.post("/api/traces/trigger-error")
async def trigger_error():
    """Trigger an LLM call with invalid model to generate error trace."""
    import uuid
    from src.telemetry import get_tracer
    from langchain_core.messages import HumanMessage
    tracer = get_tracer()
    trace_id = str(uuid.uuid4())
    request_id = tracer.create_request_id()
    try:
        import os
        from langchain_aws import ChatBedrockConverse
        bad_llm = ChatBedrockConverse(
            model="fake-invalid-model-v0",
            region_name=os.getenv("BEDROCK_REGION", "ap-southeast-1"),
        )
        await bad_llm.ainvoke([HumanMessage(content="test")])
    except Exception as e:
        tracer.record_call(
            trace_id=trace_id,
            request_id=request_id,
            layer="triggered_error_test",
            session_id="",
            user_id="",
            prompt_text="test error trigger",
            response=None,
            error=str(e),
            outcome="error",
            latency_ms=0,
        )
    return {
        "status": "error_trace_generated",
        "request_id": request_id,
        "trace_id": trace_id,
    }


=======
# ── MANDATE #23: Cache Invalidation & Memory API ──


class InvalidateCacheRequest(BaseModel):
    entity_type: str = Field(..., description="Loại entity (product, user, category)")
    entity_id: str = Field(..., description="ID của entity cần invalidate")


@app.post("/api/v1/cache/invalidate")
def api_invalidate_cache(req: InvalidateCacheRequest):
    """
    Vô hiệu hóa cache khi dữ liệu nguồn thay đổi (cho BTC replay test).

    Example: POST /api/v1/cache/invalidate
    {
        "entity_type": "product",
        "entity_id": "OLJCESPC7Z"
    }
    """
    from src.memory.genai_cache import get_genai_cache_store

    genai_cache = get_genai_cache_store()
    count = genai_cache.invalidate_by_entity(req.entity_type, req.entity_id)

    logger.info(
        "[API] Cache invalidated | entity=%s:%s | count=%d",
        req.entity_type,
        req.entity_id,
        count,
    )

    return {
        "status": "ok",
        "message": f"Invalidated {count} cache entries",
        "entity": f"{req.entity_type}:{req.entity_id}",
    }


@app.post("/api/v1/cache/clear")
def api_clear_cache():
    """
    Xóa sạch GenAI cache, session, long-term memory để reset môi trường trước khi test.

    KHÔNG xóa cart data (giữ nguyên giỏ hàng của users).
    """
    from src.memory.genai_cache import get_genai_cache_store
    from src.memory.longterm_memory import get_longterm_memory_store
    from src.memory.store import SessionStore

    cleared_items = {
        "genai_cache": 0,
        "sessions": 0,
        "longterm_memory": 0,
        "tool_cache": 0,
    }

    # Clear GenAI Cache
    try:
        genai_cache = get_genai_cache_store()
        count = genai_cache.clear()
        cleared_items["genai_cache"] = count
        logger.info("[API] GenAI cache cleared | count=%d", count)
    except Exception as e:
        logger.error("[API] Failed to clear GenAI cache: %s", e)

    # Clear Sessions
    try:
        sessions = SessionStore()
        count = len(sessions._store)
        sessions._store.clear()
        sessions._save()
        cleared_items["sessions"] = count
        logger.info("[API] Sessions cleared | count=%d", count)
    except Exception as e:
        logger.error("[API] Failed to clear sessions: %s", e)

    # Clear Long-term Memory
    try:
        ltm = get_longterm_memory_store()
        count = len(ltm._store)
        ltm._store.clear()
        ltm._save()
        cleared_items["longterm_memory"] = count
        logger.info("[API] Long-term memory cleared | count=%d", count)
    except Exception as e:
        logger.error("[API] Failed to clear long-term memory: %s", e)

    # Clear Tool Cache (from CopilotAgent)
    try:
        agent = _get_agent()
        if hasattr(agent, "_cache") and hasattr(agent._cache, "_store"):
            count = len(agent._cache._store)
            agent._cache._store.clear()
            agent._cache._stats = {"hits": 0, "misses": 0}
            if hasattr(agent._cache, "_save"):
                agent._cache._save()
            cleared_items["tool_cache"] = count
            logger.info("[API] Tool cache cleared | count=%d", count)
    except Exception as e:
        logger.error("[API] Failed to clear tool cache: %s", e)

    logger.info(
        "[API] Cache cleared | genai=%d | sessions=%d | ltm=%d | tool=%d",
        cleared_items["genai_cache"],
        cleared_items["sessions"],
        cleared_items["longterm_memory"],
        cleared_items["tool_cache"],
    )

    return {
        "status": "ok",
        "message": f"Cleared {sum(cleared_items.values())} total entries (preserving cart data)",
        "details": cleared_items,
    }


@app.get("/debug/genai_cache")
def debug_genai_cache():
    """GenAI Response Cache stats."""
    from src.memory.genai_cache import get_genai_cache_store

    return get_genai_cache_store().dump()


@app.get("/api/v1/cache/metrics")
def api_cache_metrics():
    """
    MANDATE #23: Comprehensive cache metrics endpoint.
    """
    from src.memory.genai_cache import get_genai_cache_store, _GENAI_CACHE_TTL

    metrics = {"summary": {}, "tool_cache": {}}

    try:
        genai_cache = get_genai_cache_store()
        stats = genai_cache._stats

        total_hits = (
            stats.get("hits_exact", 0)
            + stats.get("hits_semantic", 0)
            + stats.get("hits_global", 0)
        )
        total_requests = total_hits + stats.get("misses", 0)
        hit_rate = (
            round((total_hits / total_requests) * 100, 2) if total_requests > 0 else 0.0
        )

        backend = "valkey" if os.environ.get("VALKEY_URL") else "file"

        metrics["summary"] = {
            "genai_hits_exact": stats.get("hits_exact", 0),
            "genai_hits_semantic": stats.get("hits_semantic", 0),
            "genai_hits_global": stats.get("hits_global", 0),
            "genai_misses": stats.get("misses", 0),
            "genai_hit_rate_pct": hit_rate,
            "backend": backend,
            "cache_ttl_seconds": _GENAI_CACHE_TTL,
            "titan_embeds": stats.get("titan_embeds", 0),
            "invalidations": stats.get("invalidations", 0),
        }
    except Exception as e:
        logger.error("[API] Failed to get GenAI cache metrics: %s", e)
        metrics["summary"] = {"error": str(e)}

    try:
        agent = _get_agent()
        if hasattr(agent, "_cache"):
            tool_stats = agent._cache._stats
            tool_hits = tool_stats.get("hits", 0)
            tool_misses = tool_stats.get("misses", 0)
            tool_total = tool_hits + tool_misses
            tool_hit_rate = (
                round((tool_hits / tool_total) * 100, 2) if tool_total > 0 else 0.0
            )

            metrics["tool_cache"] = {
                "hits": tool_hits,
                "misses": tool_misses,
                "hit_rate_pct": tool_hit_rate,
            }
    except Exception as e:
        logger.error("[API] Failed to get tool cache metrics: %s", e)
        metrics["tool_cache"] = {"error": str(e)}

    return metrics


@app.get("/debug/longterm/{user_id}")
def debug_longterm_memory(user_id: str):
    """Long-term memory của một user."""
    from src.memory.longterm_memory import get_longterm_memory_store

    ltm = get_longterm_memory_store()
    data = ltm.dump(user_id)
    if data is None:
        raise HTTPException(status_code=404, detail="User memory không tồn tại")
    return data


@app.get("/debug/longterm_stats")
def debug_longterm_stats():
    """Thống kê long-term memory."""
    from src.memory.longterm_memory import get_longterm_memory_store

    return get_longterm_memory_store().stats()


@app.get("/api/v1/users")
def api_list_users():
    """Danh sách tất cả users với thống kê."""
    from src.memory.longterm_memory import get_longterm_memory_store
    from src.memory.store import SessionStore

    ltm = get_longterm_memory_store()
    sessions = SessionStore()

    users_data = ltm.dump_all()
    sessions_data = sessions.dump_all()

    users = []
    for user_id, memory in users_data.items():
        user_sessions = [
            s for s in sessions_data.values() if s.get("user_id") == user_id
        ]
        users.append(
            {
                "user_id": user_id,
                "total_sessions": memory["interaction_summary"]["total_sessions"],
                "total_messages": memory["interaction_summary"]["total_messages"],
                "active_sessions": len(user_sessions),
                "last_interaction": memory["interaction_summary"]["last_interaction"],
                "preferences_count": len(memory.get("preferences", [])),
                "facts_count": len(memory.get("facts", [])),
            }
        )

    return {"users": sorted(users, key=lambda x: x["last_interaction"], reverse=True)}


@app.get("/api/v1/user/{user_id}/sessions")
def api_user_sessions(user_id: str):
    """Lấy tất cả sessions của một user."""
    from src.memory.store import SessionStore

    sessions = SessionStore()
    all_sessions = sessions.dump_all()

    user_sessions = {
        sid: data
        for sid, data in all_sessions.items()
        if data.get("user_id") == user_id
    }

    return {"user_id": user_id, "sessions": user_sessions}


@app.delete("/api/v1/session/{session_id}")
def api_delete_session(session_id: str):
    """Xóa một session cụ thể."""
    from src.memory.store import SessionStore

    sessions = SessionStore()

    if session_id not in sessions._store:
        raise HTTPException(status_code=404, detail="Session not found")

    del sessions._store[session_id]
    sessions._save()

    logger.info("[API] Deleted session | session_id=%s", session_id)

    return {"status": "ok", "message": f"Deleted session {session_id}"}


@app.delete("/api/v1/user/{user_id}/memory")
def api_delete_user_memory(user_id: str):
    """Xóa long-term memory của một user."""
    from src.memory.longterm_memory import get_longterm_memory_store

    ltm = get_longterm_memory_store()

    if user_id not in ltm._store:
        raise HTTPException(status_code=404, detail="User memory not found")

    del ltm._store[user_id]
    ltm._save()

    logger.info("[API] Deleted user memory | user_id=%s", user_id)

    return {"status": "ok", "message": f"Deleted memory for {user_id}"}
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
    uvicorn.run(
        "src.main:app", host="0.0.0.0", port=port, reload=False, log_level="info"
    )
