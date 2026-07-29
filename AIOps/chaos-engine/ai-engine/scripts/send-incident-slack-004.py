#!/usr/bin/env python3
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

def main():
    load_env()
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if not token or not channel:
        print("❌ Thiếu token hoặc channel id trong .env", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    # Định dạng Block Kit chuẩn Slack cho Incident Report 004
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 CẢNH BÁO DƯ CHẤN SỰ CỐ (INCIDENT-2026-004)"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Trạng thái:* 🔴 *CRITICAL (ĐẠO CHÍCH TẤN CÔNG)*\n"
                    "*Mã sự cố:* `INCIDENT-2026-004`\n"
                    "*Thời điểm phát hiện:* 2026-07-14 16:30:00 (Local Time) 🕒"
                )
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "🔍 *Đánh giá Chỉ số SLO (SLO Violation):*\n"
                    "• *SLO Đặt hàng thành công:* Cam kết $\\ge 99.0\\%$\n"
                    "• *Thực tế (SLI):* *91.2%* (Đang giảm nhanh) ⚠️\n"
                    "• *Tốc độ tiêu hao (Burn-rate):* *28.8x* (Cực kỳ nguy cấp, cháy hết ngân sách lỗi sau 1.5 giờ)"
                )
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "🔬 *Định vị Nguyên nhân gốc (RCA - Culprit Service):*\n"
                    "• *Thủ phạm:* `payment-service` (Dịch vụ Thanh toán)\n"
                    "• *Trạng thái Pods:* `payment-8447bf7668-zx4dj` bị quá tải kết nối do tấn công càn quét API.\n"
                    "• *Bằng chứng Logs (Drain3 templates):*\n"
                    "  - `[Error] Connection timeout to Payment Gateway (AWS Bedrock)`\n"
                    "  - `[Error] Database connection pool exhausted (current: 50/50)`\n"
                    "  - `rpc error: desc = Payment request failed. Invalid token. app.loyalty.level=gold`"
                )
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "💡 *Đề xuất khắc phục từ AI Engine (Suggested Remediation):*\n"
                    "• *Hành động:* Scale up `deployment/payment` ──▶ *3 replicas* (Hiện tại: 1 replica)\n"
                    "• *Bán kính ảnh hưởng (Blast Radius):* Thấp (Tăng replica giãn tải database connection)\n"
                    "• *Kịch bản hoàn tác (Rollback Plan):* Scale down về 1 replica khi dư chấn qua đi"
                )
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Duyệt Vá Lỗi"
                    },
                    "action_id": "approve_remediation",
                    "value": "INCIDENT-2026-004"
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Từ Chối"
                    },
                    "action_id": "reject_remediation",
                    "value": "INCIDENT-2026-004"
                }
            ]
        }
    ]

    payload = {
        "channel": channel,
        "blocks": blocks,
        "text": "🚨 Cảnh báo sự cố: INCIDENT-2026-004 (CRITICAL)"
    }

    with httpx.Client(timeout=10) as client:
        r = client.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
        j = r.json()
        if not j.get("ok"):
            print(f"❌ Lỗi gửi card: {j.get('error')}", file=sys.stderr)
            return 1
        print("✅ Đã gửi thẻ sự cố chi tiết lên Slack thành công!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
