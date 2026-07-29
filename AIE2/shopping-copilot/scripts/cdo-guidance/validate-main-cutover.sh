#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_REVISION:?set EXPECTED_REVISION to deploy/account-migration-gitops or main}"

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

revision_files=(
  gitops/bootstrap/application.yaml
  gitops/apps/flagd-secret-sync-app.yaml
  gitops/apps/infrastructure-app.yaml
  gitops/apps/karpenter-nodepool-app.yaml
  gitops/apps/kyverno-policies-app.yaml
  gitops/apps/techx-corp.yaml
  gitops/apps/techx-edge.yaml
)

for file in "${revision_files[@]}"; do
  grep -Eq "^[[:space:]]*targetRevision:[[:space:]]*${EXPECTED_REVISION}([[:space:]]|$)" "$file"
done

test "$(rg -l "^[[:space:]]*targetRevision:[[:space:]]*${EXPECTED_REVISION}([[:space:]]|$)" "${revision_files[@]}" | wc -l)" -eq 7
grep -Fq 'path: phase3 - information/techx-corp-chart' gitops/apps/techx-corp.yaml
grep -Fq -- '- ../deploy/values-flagd-sync.yaml' gitops/apps/techx-corp.yaml
grep -Fq -- '- ../deploy/values-prod.yaml' gitops/apps/techx-corp.yaml
grep -Fq '197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp' gitops/apps/techx-corp.yaml
grep -Fq '197826770971.dkr.ecr.ap-southeast-1.amazonaws.com' .github/workflows/build-push-ecr.yml
grep -Fq 'resource "aws_ecr_repository" "techx_corp"' infra/live/production/ecr.tf
grep -Fq 'prevent_destroy = true' infra/live/production/ecr.tf
grep -Fq 'repository = aws_ecr_repository.techx_corp.name' infra/live/production/ecr.tf
grep -Eq '^enable_cloudflare_access[[:space:]]*=[[:space:]]*true$' infra/live/production/production.auto.tfvars
grep -Eq '^cloudflare_zone_name[[:space:]]*=[[:space:]]*"arthur-ngo.org"$' infra/live/production/production.auto.tfvars
grep -Eq '^cloudflare_tunnel_hostname[[:space:]]*=[[:space:]]*"kubectl.arthur-ngo.org"$' infra/live/production/production.auto.tfvars

for workflow in .github/workflows/terraform-plan.yml .github/workflows/terraform-apply.yml; do
  grep -Fq 'CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}' "$workflow"
  grep -Fq 'TF_VAR_cloudflare_account_id: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}' "$workflow"
  grep -Fq 'TF_VAR_cloudflare_zone_id: ${{ vars.CLOUDFLARE_ZONE_ID }}' "$workflow"
  grep -Fq 'TF_VAR_cloudflare_allowed_emails: ${{ vars.CLOUDFLARE_ALLOWED_EMAILS_JSON }}' "$workflow"
done

grep -Fq 'variable "terraform_plan_subjects"' infra/bootstrap/github-oidc/variables.tf
grep -Fq 'repo:tuu-ngo/Phase3-TF3-Infra-Sentinel:ref:refs/heads/main' infra/bootstrap/github-oidc/variables.tf
grep -Fq 'repo:tuu-ngo/Phase3-TF3-Infra-Sentinel:pull_request' infra/bootstrap/github-oidc/variables.tf
grep -Fq 'repo:tuu-ngo/Phase3-TF3-Infra-Sentinel:environment:production' infra/bootstrap/github-oidc/variables.tf
grep -Fq '"token.actions.githubusercontent.com:sub" = var.terraform_plan_subjects' infra/bootstrap/github-oidc/main.tf
grep -Fq '"token.actions.githubusercontent.com:sub" = var.terraform_apply_subject' infra/bootstrap/github-oidc/main.tf
grep -Eq '^[[:space:]]+environment:[[:space:]]+production$' .github/workflows/terraform-apply.yml

if rg -n '012619468490' .github infra gitops 'phase3 - information/deploy/values-prod.yaml'; then
  echo 'old AWS account found in an active production path' >&2
  exit 1
fi

echo "cutover repository validation passed for ${EXPECTED_REVISION}"
