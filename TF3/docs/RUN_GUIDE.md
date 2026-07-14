# TF3 AIOps Run Guide (How-To-Run)

This guide explains how to deploy, run, and test the AIOps engine and its associated incident simulations.

## 1. Prerequisites
- `kubectl` configured with access to the EKS cluster (namespace: `techx-tf3`).
- Docker installed (if building images locally).
- AWS CLI configured with proper IAM permissions (for ECR).
- A valid Slack Incoming Webhook URL.

## 2. Deploying the AIOps Engine from ECR (For CDO)
The engine image is hosted on ECR. The ECR policy has been updated to allow cross-account pulls.

1.  **Login to ECR:**
    ```bash
    aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com
    ```
2.  **Pull the Image:**
    ```bash
    docker pull 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest
    ```
3.  **Run Locally (Docker):**
    ```bash
    docker run -e SLACK_WEBHOOK_URL="your_webhook_url" 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest
    ```

## 3. Simulating Incidents via flagd (OpenFeature)
The `payment-service` reads feature flags from a Kubernetes ConfigMap.

1.  **Edit the ConfigMap:**
    ```bash
    kubectl edit configmap flagd-config -n techx-tf3
    ```
2.  **Enable Payment Failure Simulation:**
    Change the `state` of `paymentFailure` to `"ON"`:
    ```json
    "paymentFailure": {
      "state": "ON",
      "defaultVariant": "on",
      "variants": {
        "on": true,
        "off": false
      }
    }
    ```
3.  Save and exit. The application will instantly start simulating failures.

## 4. Triggering Slack Alerts Manually
If you need to manually test the Slack alert for `INCIDENT-2026-004` (Connection Pool Exhaustion):

1.  Navigate to the scripts folder:
    ```bash
    cd ai-engine/scripts
    ```
2.  Run the Python script (ensure `requests` is installed):
    ```bash
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    python send-incident-slack-004.py
    ```

## 5. Reviewing Metrics and Logs
- Use `kubectl logs deployment/payment-service -n techx-tf3` to observe the generated error logs.
- Dashboards (Grafana/Datadog if configured) should reflect the simulated 503 errors and connection pool metrics.
