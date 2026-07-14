# TF3 AIOps Engine Specification

## 1. Overview
The TF3 AIOps Engine is an intelligent operational module deployed in the `techx-tf3` EKS cluster namespace. It is designed to automatically detect, analyze, and remediate incidents occurring within the TechX Corp Platform (e.g., payment failures, connection pool exhaustion) across the AWS `us-east-1` region.

## 2. Architecture
*   **Cluster**: EKS `techx-tf3`
*   **Region**: `us-east-1`
*   **Components**:
    *   `payment-service` (Node.js)
    *   `aiops-engine` (Python)
    *   `flagd` (OpenFeature provider for fault injection)

## 3. Core Capabilities
1.  **Incident Detection**: Monitors metrics, logs, and events for anomalies (e.g., `INCIDENT-2026-004`).
2.  **Alerting & Notification**: Integrates with Slack using Block Kit to provide real-time alerts with interactive approval actions (Approve Auto-scaling).
3.  **Remediation**: Executes automated runbooks or applies configuration changes upon approval.
4.  **Fault Injection**: Uses `flagd` ConfigMap (`flagd-config`) to simulate incidents like `paymentFailure`.

## 4. Security & Configuration
*   Secrets (e.g., Slack Webhooks, API keys) are managed via Kubernetes Secrets (`aiops-engine-secrets`).
*   Cross-account ECR access policies are applied to allow CDO team pulling images from the central registry (`197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest`).
