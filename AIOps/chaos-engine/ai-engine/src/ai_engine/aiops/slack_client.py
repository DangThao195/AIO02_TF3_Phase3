"""Slack adapter for the approval gate (C6 / AIOps-06).

Sends the Approve/Reject card to a channel and verifies that interaction callbacks genuinely
come from Slack. Two hard security rules:

  1. Secrets come ONLY from env (SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET) — never hardcoded,
     never logged, never committed. Rotate on the Slack app page if they leak.
  2. Every incoming callback is verified with Slack's HMAC-SHA256 signature AND a timestamp
     freshness check (replay guard). An unverified request is rejected before it can approve
     anything — otherwise anyone could forge an approval and bypass the human gate.

Transport (httpx) is injected so this is testable without hitting Slack.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import httpx

from ..common.schemas import RemediationRecord
from .approval import render_slack_blockkit

SLACK_API = "https://slack.com/api"
# Slack rejects/needs re-verify requests older than 5 min; we use the same window as replay guard.
MAX_SIGNATURE_AGE_S = 60 * 5


class SlackConfigError(RuntimeError):
    """Raised when a required Slack secret is missing from the environment."""


class SlackSignatureError(Exception):
    """Raised when a callback fails signature/timestamp verification — do NOT trust it."""


def _bot_token() -> str:
    tok = os.environ.get("SLACK_BOT_TOKEN")
    if not tok:
        raise SlackConfigError("SLACK_BOT_TOKEN not set (load from K8s secret, never hardcode)")
    return tok


def _signing_secret() -> bytes:
    sec = os.environ.get("SLACK_SIGNING_SECRET")
    if not sec:
        raise SlackConfigError("SLACK_SIGNING_SECRET not set (load from K8s secret, never hardcode)")
    return sec.encode()


class SlackApprovalClient:
    def __init__(self, channel: str | None = None, client: httpx.Client | None = None):
        self._channel = channel or os.environ.get("SLACK_APPROVAL_CHANNEL", "")
        self._client = client or httpx.Client(timeout=5)

    def post_approval_card(self, record: RemediationRecord, evidence_url: str | None = None) -> str:
        """Post the Approve/Reject card. Returns the Slack message ts (for later update)."""
        if not self._channel:
            raise SlackConfigError("SLACK_APPROVAL_CHANNEL not set")
        card = render_slack_blockkit(record, evidence_url)
        resp = self._client.post(
            f"{SLACK_API}/chat.postMessage",
            headers={"Authorization": f"Bearer {_bot_token()}"},
            json={"channel": self._channel, **card},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            # never echo the token; only Slack's error code
            raise RuntimeError(f"slack postMessage failed: {data.get('error')}")
        return data.get("ts", "")


def verify_slack_signature(
    *, timestamp: str, signature: str, raw_body: bytes, now: float | None = None
) -> None:
    """Verify a Slack request signature (HMAC-SHA256) + timestamp freshness.

    Raises SlackSignatureError if invalid. This MUST pass before a callback is allowed to
    approve/execute anything (the human gate depends on the callback being genuine).

    basestring = "v0:{timestamp}:{raw_body}"; expected = "v0=" + hex(HMAC-SHA256(secret, basestring)).
    """
    now = time.time() if now is None else now
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise SlackSignatureError("missing/invalid timestamp") from None
    if abs(now - ts) > MAX_SIGNATURE_AGE_S:
        raise SlackSignatureError("stale request (replay guard)")

    basestring = b"v0:" + timestamp.encode() + b":" + raw_body
    expected = "v0=" + hmac.new(_signing_secret(), basestring, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise SlackSignatureError("signature mismatch")
