# TF3 AIOps API & Event Contracts

## 1. Slack Alert Integration Contract
**Endpoint:** Managed via Slack Incoming Webhook (Securely loaded from `aiops-engine-secrets`).
**Format:** Slack Block Kit (JSON)
**Payload Schema (Example for INCIDENT-2026-004):**
```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🚨 AIOps Alert: Connection Pool Exhaustion Detected (INCIDENT-2026-004)"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Service:* Payment Service\n*Impact:* Transactions failing due to connection pool limits reached during network scanning.\n*Root Cause:* Spike in invalid concurrent requests."
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "Approve Auto-scaling (Remediate)"
          },
          "style": "primary",
          "value": "scale_payment_service"
        }
      ]
    }
  ]
}
```

## 2. Docker Registry (ECR) Pull Contract
**Account ID:** `197826770971`
**Region:** `ap-southeast-1`
**Image URI:** `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest`
**Contract:** The AWS ECR policy allows `arn:aws:iam::[CDO_ACCOUNT_ID]:root` to perform `ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage`, and `ecr:BatchCheckLayerAvailability`.

## 3. OpenFeature (flagd) Fault Injection Contract
**Resource:** ConfigMap `flagd-config` in `techx-tf3` namespace.
**Contract:** Modifying the `state` of `paymentFailure` (or similar flags) from `"OFF"` to `"ON"` instantly propagates to the `payment-service` to simulate incidents.

## 4. Remediation Webhook Contract (Planned)
**Format:** HTTP POST
**Payload:**
```json
{
  "incident_id": "INCIDENT-2026-004",
  "action": "scale_payment_service",
  "approved_by": "slack_user_id"
}
```
