import json
import os
import asyncio
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="Auto Tester for Shopping Copilot")

# Ensure static dir exists
os.makedirs(os.path.join(os.path.dirname(__file__), "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

AGENTIC_SERVER_URL = "http://localhost:8001/api/chat"
CONFIRM_URL = "http://localhost:8001/api/confirm"
TEST_DATA_FILE = os.path.join(os.path.dirname(__file__), "test.json")

def load_sessions():
    if not os.path.exists(TEST_DATA_FILE):
        return {"sessions": []}
    with open(TEST_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/")
def read_root():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)

@app.get("/sessions")
def get_sessions():
    return load_sessions()

@app.websocket("/ws/test/{session_id}")
async def websocket_test_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    data = load_sessions()
    target_session = next((s for s in data.get("sessions", []) if s.get("id") == session_id), None)
    
    if not target_session:
        await websocket.send_json({
            "type": "system_error",
            "content": f"Session {session_id} không tồn tại!"
        })
        await websocket.close()
        return

    await websocket.send_json({
        "type": "session_start",
        "content": f"--- Bắt đầu Test: {target_session.get('name')} ---"
    })

    # Prepare user_id for the test session
    user_id = f"test_user_{session_id}"
    test_session_id = f"test_run_{session_id}"

    async with httpx.AsyncClient(timeout=300.0) as client:
        for query in target_session.get("queries", []):
            # Emit user query
            await websocket.send_json({
                "type": "user_query",
                "content": query
            })
            
            # Call Agentic Server
            payload = {
                "message": query,
                "session_id": test_session_id,
                "user_id": user_id
            }
            
            try:
                response = await client.post(AGENTIC_SERVER_URL, json=payload)
                response.raise_for_status()
                result = response.json()
                
                # Auto-confirm write actions (add to cart, etc.)
                if result.get("status") == "pending":
                    token = result.get("token")
                    await websocket.send_json({
                        "type": "system_info",
                        "content": "🔄 Phát hiện yêu cầu xác nhận — đang tự động confirm..."
                    })
                    confirm_payload = {
                        "session_id": test_session_id,
                        "token": token
                    }
                    confirm_resp = await client.post(CONFIRM_URL, json=confirm_payload)
                    confirm_resp.raise_for_status()
                    confirm_result = confirm_resp.json()
                    
                    reply_text = confirm_result.get("reply", "[Confirmed]")
                    
                    await websocket.send_json({
                        "type": "system_info",
                        "content": "✅ Đã tự động confirm thành công."
                    })
                else:
                    reply_text = result.get("reply", "[No Reply]")
                
                # Emit agent response
                await websocket.send_json({
                    "type": "agent_response",
                    "content": reply_text
                })
                
                # Dynamic delay + 1s for UI
                await asyncio.sleep(1.0)
                
            except httpx.RequestError as exc:
                fallback_msg = f"[Fallback] Lỗi kết nối tới Agentic Server ở {AGENTIC_SERVER_URL}. Chi tiết: {str(exc)}. Dừng kịch bản hiện tại."
                await websocket.send_json({
                    "type": "agent_response",
                    "content": fallback_msg
                })
                break
            except httpx.HTTPStatusError as exc:
                fallback_msg = f"[Fallback] Agentic Server trả về lỗi HTTP {exc.response.status_code}. Dừng kịch bản hiện tại."
                await websocket.send_json({
                    "type": "agent_response",
                    "content": fallback_msg
                })
                break
            except Exception as e:
                await websocket.send_json({
                    "type": "system_error",
                    "content": f"Lỗi không xác định: {str(e)}"
                })
                break

    await websocket.send_json({
        "type": "system_info",
        "content": f"--- Kết thúc Test: {target_session.get('name')} ---"
    })
    await websocket.close()

if __name__ == "__main__":
    print("Starting Test Server on port 8002...")
    uvicorn.run("test_server:app", host="0.0.0.0", port=8002, reload=False)
