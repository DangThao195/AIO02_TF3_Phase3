#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
chart="$repo_root/phase3 - information/techx-corp-chart"
values="$repo_root/phase3 - information/deploy/values-prod.yaml"
rendered=$(mktemp)
default_rendered=$(mktemp)
trap 'rm -f "$rendered" "$default_rendered"' EXIT

dependency_overrides=(
  --set opentelemetry-collector.enabled=false
  --set jaeger.enabled=false
  --set prometheus.enabled=false
  --set grafana.enabled=false
  --set opensearch.enabled=false
)

helm template techx-corp "$chart" \
  --namespace techx-tf3 \
  --values "$values" \
  "${dependency_overrides[@]}" > "$rendered"

helm template techx-corp "$chart" \
  --namespace techx-tf3 \
  "${dependency_overrides[@]}" > "$default_rendered"

for workload in ad cart currency frontend frontend-proxy product-catalog product-reviews recommendation; do
  replicas=$(yq -r "select(.kind == \"Deployment\" and .metadata.name == \"$workload\") | .spec.replicas // \"absent\"" "$rendered")
  test "$replicas" = "absent" || {
    echo "$workload must omit spec.replicas while HPA owns scale" >&2
    exit 1
  }
done

checkout_replicas=$(yq -r 'select(.kind == "Rollout" and .metadata.name == "checkout-rollout") | .spec.replicas // "absent"' "$rendered")
test "$checkout_replicas" = "absent" || {
  echo "checkout-rollout must omit spec.replicas while HPA owns scale" >&2
  exit 1
}

payment_replicas=$(yq -r 'select(.kind == "Deployment" and .metadata.name == "payment") | .spec.replicas // "absent"' "$rendered")
test "$payment_replicas" != "absent" || {
  echo "payment must retain spec.replicas because it has no HPA" >&2
  exit 1
}

default_frontend_replicas=$(yq -r 'select(.kind == "Deployment" and .metadata.name == "frontend") | .spec.replicas // "absent"' "$default_rendered")
test "$default_frontend_replicas" != "absent" || {
  echo "default chart must retain spec.replicas when external ownership is disabled" >&2
  exit 1
}

echo "HPA replica ownership render test passed"
