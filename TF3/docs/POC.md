# TF3 AIOps Proof of Concept (POC)

## Overview
This POC demonstrates the ability of the TF3 AIOps engine to detect, notify, and simulate remediation for critical incidents within the TechX Corp Platform.

## Scenario: INCIDENT-2026-004 (Payment Service Exhaustion)
**Objective:** Prove that a sudden spike in invalid requests (simulating a network scan / "đạo chích" attack) causing connection pool exhaustion is detected and alerted properly.

## Steps Demonstrated
1.  **Fault Simulation**: We used OpenFeature (`flagd`) to toggle the `paymentFailure` flag to `ON` within the `techx-tf3` EKS cluster. This successfully simulated the failure mode in the `payment-service`.
2.  **Detection**: The simulated failures resulted in `503 Service Unavailable` errors and connection pool exhaustion metrics, which were logged.
3.  **Notification & Interaction**: 
    -   A Python script (`send-incident-slack-004.py`) was developed to dispatch an interactive Block Kit message to a Slack channel.
    -   The message clearly stated the incident details, root cause, and provided an actionable button: "Approve Auto-scaling".
4.  **Cross-Account Artifact Sharing**: Configured AWS ECR (`ecr-policy.json`) to allow the CDO team to pull the `ai-engine` Docker image (`197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:latest`) to deploy and verify the POC in their environments (e.g., `us-east-1`).

## Results
- The POC successfully validated the pipeline from Incident Simulation -> Detection -> Alerting -> Proposed Remediation.
- Zero touch operation required to push the alert to Slack once the incident pattern was identified.
- Readiness achieved for CDO integration.
