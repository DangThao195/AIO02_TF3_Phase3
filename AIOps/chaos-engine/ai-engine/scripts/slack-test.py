#!/usr/bin/env python3
"""Slack connection smoke test (C6 / C2). Reads token+channel from .env, sends a real message.

Chạy sau khi đã điền SLACK_BOT_TOKEN + SLACK_CHANNEL_ID vào .env:
    python scripts/slack-test.py            # gửi tin nhắn test đơn giản
    python scripts/slack-test.py --card     # gửi thử approval card (Block Kit)

Xác nhận: (1) token hợp lệ (auth.test), (2) bot ở trong kênh, (3) gửi được tin.
Không in token ra màn hình. Thoát mã != 0 nếu lỗi để dùng được trong CI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> None:
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not token or not channel:
        print("❌ Thiếu SLACK_BOT_TOKEN hoặc SLACK_CHANNEL_ID trong .env", file=sys.stderr)
        print("   Lấy Bot Token (xoxb-) ở: Slack app → OAuth & Permissions → Install to Workspace")
        print("   Lấy Channel ID (C0...) ở: chuột phải kênh → View channel details → cuối trang")
        return 2
    if not token.startswith("xoxb-"):
        print(f"⚠️  Token không bắt đầu bằng 'xoxb-' (bạn đang dùng {token.split('-')[0]}-...). "
              "Kiểu HTTP cần Bot User OAuth Token (xoxb-), không phải app token (xapp-).",
              file=sys.stderr)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    with httpx.Client(timeout=10) as c:
        # 1. auth.test — token hợp lệ + xem bot là ai
        r = c.post("https://slack.com/api/auth.test", headers=headers)
        j = r.json()
        if not j.get("ok"):
            print(f"❌ auth.test lỗi: {j.get('error')}", file=sys.stderr)
            return 1
        print(f"✅ Token hợp lệ — bot @{j.get('user')} trong workspace '{j.get('team')}'")

        # 2. gửi tin nhắn
        if "--card" in sys.argv:
            blocks = _demo_card()
            payload = {"channel": channel, "blocks": blocks, "text": "TF3 AI Engine — approval card (test)"}
        else:
            payload = {"channel": channel,
                       "text": "✅ *TF3 AI Engine* đã kết nối Slack thành công (C6/C2). Đây là tin nhắn test."}
        r = c.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
        j = r.json()
        if not j.get("ok"):
            err = j.get("error")
            hint = {
                "not_in_channel": "Bot chưa ở trong kênh — gõ /invite @tên-bot trong kênh đó.",
                "channel_not_found": "Sai SLACK_CHANNEL_ID (phải là C0..., không phải tên kênh).",
                "invalid_auth": "Token sai/hết hạn — lấy lại Bot User OAuth Token.",
                "missing_scope": "Thiếu scope chat:write — thêm ở OAuth & Permissions rồi reinstall.",
            }.get(err, "")
            print(f"❌ chat.postMessage lỗi: {err}. {hint}", file=sys.stderr)
            return 1
        print(f"✅ Đã gửi tin vào kênh {channel} (ts={j.get('ts')}). Kiểm tra Slack.")
    return 0


def _demo_card() -> list:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🛠️ TF3 · Đề xuất khắc phục (TEST)"}},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": "*Action:* `scale` deployment/checkout → 4 replicas\n*Incident:* TF3-TEST-0001\n*Rollback:* scale về 2"}},
        {"type": "actions", "elements": [
            {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "✅ Duyệt"},
             "action_id": "approve", "value": "TF3-TEST-0001"},
            {"type": "button", "style": "danger", "text": {"type": "plain_text", "text": "❌ Từ chối"},
             "action_id": "reject", "value": "TF3-TEST-0001"},
        ]},
        {"type": "context", "elements": [{"type": "mrkdwn",
            "text": "_Đây là card test — bấm nút cần Request URL công khai đã cấu hình._"}]},
    ]


if __name__ == "__main__":
    raise SystemExit(main())
