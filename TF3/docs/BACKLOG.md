# TF3 AIOps Engine Backlog

## Current Sprint
- [x] Analyze and report on `INCIDENT-2026-004` (Connection Pool Exhaustion).
- [x] Implement interactive Slack alert via Block Kit for `INCIDENT-2026-004`.
- [x] Configure ECR access policy for cross-account pull from CDO.
- [x] Document SPEC, BACKLOG, CONTRACTS, POC, and RUN_GUIDE.

## Next Sprint (To-Do)
- [ ] **Automated Remediation Execution**: Link Slack "Approve Auto-scaling" button to an actual webhook that triggers Kubernetes HPA or deployment scaling commands.
- [ ] **Incident Prediction**: Integrate a predictive model in the `aiops-engine` based on historical metrics to warn before exhaustion occurs.
- [ ] **CDO Dashboard**: Build an aggregated metrics dashboard (e.g., Grafana) displaying real-time metrics across `us-east-1` for CDO visibility.
- [ ] **Advanced Chaos Engineering**: Expand `flagd-config` with latency injection, database disconnect scenarios, and randomized pod failures to stress-test the AIOps engine.
- [ ] **Incident Runbooks Automation**: Convert remaining manual Markdown runbooks into executable Python scripts.
