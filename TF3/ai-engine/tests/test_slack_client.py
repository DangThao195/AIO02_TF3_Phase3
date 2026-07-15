"""Slack adapter tests (AIOps-06) — the security-critical parts: signature + replay guard.

Uses a FAKE signing secret set in env for the test; never the real one. Proves a forged or
replayed callback is rejected before it can approve anything.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from ai_engine.aiops.slack_client import (
    SlackConfigError,
    SlackSignatureError,
    verify_slack_signature,
)

FAKE_SECRET = "test-signing-secret-not-real"


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", FAKE_SECRET)


def _sign(body: bytes, ts: str) -> str:
    base = b"v0:" + ts.encode() + b":" + body
    return "v0=" + hmac.new(FAKE_SECRET.encode(), base, hashlib.sha256).hexdigest()


def test_valid_signature_passes():
    body = b'{"actions":[{"action_id":"approve","value":"TF3-ACT-1"}]}'
    ts = str(int(time.time()))
    verify_slack_signature(timestamp=ts, signature=_sign(body, ts), raw_body=body)  # no raise


def test_forged_signature_rejected():
    body = b'{"actions":[{"action_id":"approve","value":"X"}]}'
    ts = str(int(time.time()))
    with pytest.raises(SlackSignatureError, match="mismatch"):
        verify_slack_signature(timestamp=ts, signature="v0=deadbeef", raw_body=body)


def test_replayed_old_request_rejected():
    body = b'{"x":1}'
    old_ts = str(int(time.time()) - 600)          # 10 min old -> stale
    with pytest.raises(SlackSignatureError, match="stale"):
        verify_slack_signature(timestamp=old_ts, signature=_sign(body, old_ts), raw_body=body)


def test_tampered_body_rejected():
    ts = str(int(time.time()))
    sig = _sign(b'{"amount":1}', ts)              # signed the original
    with pytest.raises(SlackSignatureError, match="mismatch"):
        verify_slack_signature(timestamp=ts, signature=sig, raw_body=b'{"amount":9999}')  # tampered


def test_missing_timestamp_rejected():
    with pytest.raises(SlackSignatureError, match="timestamp"):
        verify_slack_signature(timestamp="", signature="v0=x", raw_body=b"{}")


def test_missing_secret_is_config_error(monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    body = b"{}"
    ts = str(int(time.time()))
    with pytest.raises(SlackConfigError, match="SIGNING_SECRET"):
        verify_slack_signature(timestamp=ts, signature="v0=x", raw_body=body)
