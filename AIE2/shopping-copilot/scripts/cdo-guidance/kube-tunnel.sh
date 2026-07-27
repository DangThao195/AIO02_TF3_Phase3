#!/usr/bin/env bash
# Helper script to manage local SSM Bastion Tunnel for EKS access.
# This script manages EKS tunnel access for the team.

set -euo pipefail

LOCAL_PORT=8443
BASTION_ID="i-02a8d3e39b87180ce"
ENDPOINT="ADA05FFC84146C0AED730F78786EB320.gr7.ap-southeast-1.eks.amazonaws.com"
CLUSTER_NAME="techx-corp-tf3"
REGION="ap-southeast-1"
LOG_FILE="/tmp/eks_ssm_tunnel.log"

echo "=== EKS SSM Bastion Tunnel Manager ==="

# 1. Check if tunnel is already active
if lsof -i :$LOCAL_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✔ Port $LOCAL_PORT is already in use. Assuming tunnel is already open."
else
    echo "▶ Opening SSM Tunnel to EKS API through bastion $BASTION_ID..."
    # Start SSM session in the background
    aws ssm start-session \
        --target "$BASTION_ID" \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters host="$ENDPOINT",portNumber="443",localPortNumber="$LOCAL_PORT" \
        --region "$REGION" > "$LOG_FILE" 2>&1 &

    # Wait for the tunnel to establish
    sleep 3

    if ! lsof -i :$LOCAL_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "❌ Failed to open tunnel. Check logs in $LOG_FILE:"
        cat "$LOG_FILE"
        exit 1
    fi
    echo "✔ Tunnel successfully opened on port $LOCAL_PORT."
fi

# 2. Configure kubectl kubeconfig
echo "▶ Updating kubeconfig and setting context to localhost:$LOCAL_PORT..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"

# Configure the cluster to use the local tunnel
CLUSTER_ARN="arn:aws:eks:${REGION}:197826770971:cluster/${CLUSTER_NAME}"
kubectl config set-cluster "$CLUSTER_ARN" --server="https://localhost:$LOCAL_PORT" --insecure-skip-tls-verify=true

# 3. Verify EKS connectivity
echo "▶ Verifying connection to cluster..."
if kubectl get ns >/dev/null 2>&1; then
    echo "✔ Successfully connected to EKS cluster."
    echo "✔ Active Context: $(kubectl config current-context)"

    # 4. Print all project dashboard and UI access links
    echo ""
    echo "=== ACTIVE SERVICES & DASHBOARDS ACCESS LINKS ==="
    echo "🌐 Storefront Public (CloudFront): https://d2tn71186d7ilz.cloudfront.net"
    echo "📊 Grafana Dashboard:             https://grafana.arthur-ngo.org"
    echo "🔍 Jaeger UI Trace:              https://jaeger.arthur-ngo.org/jaeger/ui/"
    echo "🐙 ArgoCD UI (GitOps):           https://argocd.arthur-ngo.org"
    echo "⚓ Kubectl Cloudflare Endpoint:    kubectl.arthur-ngo.org"
    echo "================================================="
else
    echo "❌ Connection failed. Check SSM logs in $LOG_FILE"
    exit 1
fi
