from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from dataclasses import replace

import httpx
import pytest

from ai_engine.server import create_app, AIOpsEngine
from ai_engine.common.config import Config
from ai_engine.common.schemas import ApprovalDecision, Severity, SourceLayer
from ai_engine.aiops.remediation import RemediationRecord, ActionType, Execution


# Mock AIOpsEngine.run to prevent real loop query
@pytest.fixture(autouse=True)
def mock_engine_run(monkeypatch):
    async def fake_run(*args, **kwargs):
        pass
    monkeypatch.setattr(AIOpsEngine, "run", fake_run)


def _sign(body: bytes, ts: str, secret: str) -> str:
    base = b"v0:" + ts.encode("utf-8") + b":" + body
    return "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()


@pytest.mark.anyio
async def test_healthz():
    cfg = Config()
    app = create_app(cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/healthz")
    assert res.status_code == 200
    assert res.text == "ok"


@pytest.mark.anyio
async def test_metrics():
    cfg = Config()
    app = create_app(cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    assert res.status_code == 200
    assert "ai_engine_blind" in res.text


@pytest.mark.anyio
async def test_slack_interactive_invalid_signature(monkeypatch):
    cfg = Config()
    cfg = replace(cfg, slack=replace(cfg.slack, signing_secret="secret"))
    app = create_app(cfg)

    headers = {
        "x-slack-request-timestamp": "123456",
        "x-slack-signature": "v0=invalid",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/webhooks/slack/interactive", headers=headers, content=b"{}")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_slack_interactive_no_pending_record(monkeypatch):
    cfg = Config()
    secret = "secret"
    cfg = replace(cfg, slack=replace(cfg.slack, signing_secret=secret))
    
    # Mock verify_slack_signature to return True to bypass timing limit
    monkeypatch.setattr("ai_engine.server.verify_slack_signature", lambda *a, **kw: True)
    
    app = create_app(cfg)

    payload = {
        "type": "block_actions",
        "user": {"id": "U123", "username": "testuser"},
        "actions": [{"action_id": "approve", "value": "nonexistent"}],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    headers = {
        "x-slack-request-timestamp": str(int(time.time())),
        "x-slack-signature": "dummy",
        "content-type": "application/x-www-form-urlencoded",
    }
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/webhooks/slack/interactive", headers=headers, content=body)
    assert res.status_code == 400
    assert "No pending remediation record found" in res.text
