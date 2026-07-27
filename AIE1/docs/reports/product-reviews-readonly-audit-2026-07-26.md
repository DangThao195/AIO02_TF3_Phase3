# Product Reviews NetworkPolicy Promotion Clarifications

**Updated:** 2026-07-27  
**Policy:** `gitops/infrastructure/network-policy-staged/32-product-reviews.yaml`  
**Status:** staged and promotion-blocked

## Confirmed Facts

- AWS VPC CNI NetworkPolicy is enabled in `standard` mode. In-cluster service traffic is evaluated on the pod path after service DNAT; use pod selectors, not Service ClusterIP `/32` peers.
- Product Reviews listens on target port `3551` and is called by `frontend`.
- Required in-cluster egress is DNS, `product-catalog:8080`, `flagd:8013`, and `otel-gateway:4317`.
- RDS uses private VPC subnet CIDRs on `5432`; the three `/20` peers in the staged policy are intentional.
- IRSA trust is scoped to `techx-tf3/product-reviews-bedrock`. Its inline policy only permits model invocation for Nova Lite and Nova Micro in `us-east-1`.
- Bedrock Runtime and STS currently use public endpoints through NAT. The VPC is in `ap-southeast-1`, so it cannot host a same-VPC private endpoint for Bedrock Runtime in `us-east-1`.
- Guardrail `shopping-copilot-guardrail` exists in `us-east-1`, but Product Reviews does not currently configure its ID or have `bedrock:ApplyGuardrail` permission.
- `Converse` uses the existing model invocation permission; a separate `bedrock:Converse` grant is not required.

## Decisions Still Required

### 1. Bedrock Egress Architecture

Choose and document one option:

- **Preferred:** route Product Reviews through a GitOps-managed egress proxy with an FQDN allowlist for the required Bedrock and STS endpoints.
- **Temporary exception:** retain NAT HTTPS egress, with an owner, expiry date, monitoring and rollback criteria.
- **Regional migration:** change to models available in `ap-southeast-1`, then use a regional Bedrock Runtime endpoint. This requires model behavior, cost and availability validation.

The current `0.0.0.0/0:443` rule must remain a promotion blocker until one option is approved.

### 2. Guardrail

- If the application-level evaluator is sufficient, document that decision and keep IAM unchanged.
- If Bedrock Guardrail enforcement is required, configure Guardrail ID/version/region and grant only `bedrock:ApplyGuardrail` on its exact ARN.

### 3. STS Connectivity

Decide whether to create an STS interface endpoint in `ap-southeast-1`. If created, verify Private DNS, endpoint policy and Security Group access before removing public STS egress.

### 4. ServiceAccount Token Hardening

Render and deploy the chart change that disables the default Kubernetes API token. The new pod must retain the IRSA `aws-iam-token` volume and must not contain `kube-api-access-*`.

## Promotion Evidence Required

1. Helm lint/template and CI pass with `values-aio-llm.yaml`.
2. Argo CD is `Synced/Healthy`; Product Reviews remains ready with no restart regression.
3. Allowed flows pass: DNS, product-catalog, flagd, otel-gateway, RDS, STS and Bedrock Runtime.
4. Denied flows fail: payment or another unrelated service, plus arbitrary Internet egress after the approved egress design is active.
5. The Product Reviews `PolicyEndpoint` is present and matches the promoted policy.
6. Browse and product-review customer journeys remain healthy through the soak window.

Do not promote this policy or move it out of `network-policy-staged/` until all decisions and evidence above are complete. Do not include Secret values or credentials in evidence.
