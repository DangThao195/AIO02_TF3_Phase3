import requests
import json
import logging
from config import SLACK_WEBHOOK_URL

logger = logging.getLogger("AIOpsEngine.SlackNotifier")

class SlackNotifier:
    def __init__(self):
        self.webhook_url = SLACK_WEBHOOK_URL

    def send_incident_notification(self, incident_id: str, diagnosis: dict) -> bool:
        analysis_val = diagnosis.get('analysis')
        if isinstance(analysis_val, dict):
            lines = []
            # 1. Hiện tượng
            phenomenon = analysis_val.get('hiện_tượng') or analysis_val.get('phenomenon') or analysis_val.get('incident_symptom')
            if phenomenon:
                lines.append(f"* **Hiện tượng**: {phenomenon}")
            # 2. Nguyên nhân
            rc = analysis_val.get('nguyên_nhân') or analysis_val.get('root_cause') or analysis_val.get('cause')
            if rc:
                lines.append(f"* **Nguyên nhân**: {rc}")
            # 3. Bằng chứng
            evidence = analysis_val.get('bằng_chứng') or analysis_val.get('evidence')
            if evidence:
                lines.append("* **Bằng chứng**:")
                if isinstance(evidence, dict):
                    for k, v in evidence.items():
                        lines.append(f"  - _{k.title()}_: {v}")
                else:
                    lines.append(f"  - {evidence}")
            # 4. Vùng ảnh hưởng
            blast = (analysis_val.get('vùng_ảnh_hưởng') or 
                     analysis_val.get('vùng_ảnh_hưởng_blast_radius') or 
                     analysis_val.get('blast_radius') or 
                     analysis_val.get('impacted_services'))
            if blast:
                lines.append(f"* **Vùng ảnh hưởng (Blast Radius)**: {blast}")
            # Thêm các trường phụ khác
            for k, v in analysis_val.items():
                if k not in ['hiện_tượng', 'phenomenon', 'incident_symptom',
                             'nguyên_nhân', 'root_cause', 'cause',
                             'bằng_chứng', 'evidence',
                             'vùng_ảnh_hưởng', 'vùng_ảnh_hưởng_blast_radius', 'blast_radius', 'impacted_services']:
                    lines.append(f"* **{k.title()}**: {v}")
            analysis_str = "\n".join(lines)
        else:
            analysis_str = str(analysis_val)

        if not self.webhook_url:
            logger.warning("Slack Webhook URL is empty! Printing message to console instead.")
            print(f"\n=== SLACK INCIDENT CARD ({incident_id}) ===")
            print(f"RCA Analysis:\n{analysis_str}")
            print(f"Matched Incident: {diagnosis.get('matched_incident')}")
            print(f"Proposed Action: {diagnosis.get('proposed_action')}")
            print(f"Command: {diagnosis.get('action_command')}")
            print("=========================================\n")
            return True


        trace_id = diagnosis.get('trace_id') or 'unknown-trace-id'
        culprit_service = diagnosis.get('culprit_service') or 'unknown-service'
        trace_analysis = diagnosis.get('trace_analysis') or culprit_service
        chain_block = f"\n```{trace_analysis}```" if trace_analysis and " -> " in trace_analysis else ""
        rca_mrkdwn = f"*Phân tích đường đi lỗi (RCA):* Phát hiện bất thường bắt nguồn từ dịch vụ `{culprit_service}`.\n`traceId`: `{trace_id}`{chain_block}"

        # Slack Block Kit payload structure
        if incident_id.startswith("INC-ML-") and not diagnosis.get("action_command"):
            # Thẻ cảnh báo sớm máy học dạng thông tin thuần túy
            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"⚠️ Proactive ML Warning: {incident_id} (SLO Stable)",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": rca_mrkdwn
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Phân tích chi tiết chẩn đoán AI:*\n{analysis_str}"
                        }
                    }
                ]
            }
        else:
            # Thẻ sự cố vỡ SLO đầy đủ kèm nút Approve/Reject tự khắc phục
            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"🚨 AIOps Incident Alert: {incident_id}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": rca_mrkdwn
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Phân tích chi tiết chẩn đoán AI:*\n{analysis_str}\n\n*Đối chiếu sự cố lịch sử:* `{diagnosis.get('matched_incident')}` | *Độ tự tin quyết định AI:* `{float(diagnosis.get('confidence_score', 1.0)) * 100}%`"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Lệnh khắc phục đề xuất:*\n`{diagnosis.get('action_command')}`"
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "✅ Approve (Duyệt chạy)",
                                    "emoji": True
                                },
                                "style": "primary",
                                "value": "approve",
                                "action_id": f"approve_{incident_id}"
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "❌ Reject (Từ chối)",
                                    "emoji": True
                                },
                                "style": "danger",
                                "value": "reject",
                                "action_id": f"reject_{incident_id}"
                            }
                        ]
                    }
                ]
            }

        try:
            response = requests.post(
                self.webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Sent interactive Slack card successfully.")
                return True
            logger.error(f"Failed to send Slack card: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error sending Slack notification: {str(e)}")
        return False
