#!/usr/bin/env bash
# Helper script to manage local SSM Bastion Tunnel for EKS access using .env configuration.

set -euo pipefail

# 1. Load configuration from .env if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "▶ Loading configuration from .env..."
    set -a
    source <(grep -v '^#' "$PROJECT_ROOT/.env" | grep -v '^$')
    set +a
fi

# Config variables driven from .env (fallback to defaults)
REGION="${AWS_REGION:-ap-southeast-1}"
CLUSTER_NAME="${EKS_CLUSTER_NAME:-techx-corp-tf3}"
BASTION_TAG_NAME="${BASTION_TAG_NAME:-techx-corp-tf3-bastion}"
LOCAL_PORT="${EKS_LOCAL_TUNNEL_PORT:-8443}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-197826770971}"
LOG_FILE="/tmp/eks_ssm_tunnel.log"

echo "=== EKS SSM Bastion Tunnel Manager ==="
echo "▶ Cluster: $CLUSTER_NAME | Region: $REGION | Bastion Tag: $BASTION_TAG_NAME"

# 2. Query active Bastion ID dynamically from AWS EC2 API
BASTION_ID=$(aws ec2 describe-instances \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=$BASTION_TAG_NAME" \
            "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" --output text)

if [ -z "$BASTION_ID" ]; then
    echo "❌ Error: Could not resolve active Bastion ID for tag Name=$BASTION_TAG_NAME"
    exit 1
fi

echo "✔ Resolved Active Bastion ID: $BASTION_ID"

# 3. Query EKS private API endpoint dynamically
ENDPOINT=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" \
  --query "cluster.endpoint" --output text | sed 's~^https://~~')

if [ -z "$ENDPOINT" ]; then
    echo "❌ Error: Could not resolve EKS cluster endpoint for $CLUSTER_NAME"
    exit 1
fi

# 4. Check if tunnel is already active
if lsof -i :$LOCAL_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✔ Port $LOCAL_PORT is already in use. Assuming tunnel is already open."
else
    echo "▶ Opening SSM Tunnel to EKS API ($ENDPOINT) through bastion $BASTION_ID..."
    aws ssm start-session \
        --target "$BASTION_ID" \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters host="$ENDPOINT",portNumber="443",localPortNumber="$LOCAL_PORT" \
        --region "$REGION" > "$LOG_FILE" 2>&1 &

    sleep 3

    if ! lsof -i :$LOCAL_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "❌ Failed to open tunnel. Check logs in $LOG_FILE:"
        cat "$LOG_FILE"
        exit 1
    fi
    echo "✔ Tunnel successfully opened on port $LOCAL_PORT."
fi

# 5. Configure kubectl kubeconfig
echo "▶ Updating kubeconfig and setting context to localhost:$LOCAL_PORT..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"

CLUSTER_ARN="arn:aws:eks:${REGION}:${ACCOUNT_ID}:cluster/${CLUSTER_NAME}"
kubectl config set-cluster "$CLUSTER_ARN" --server="https://localhost:$LOCAL_PORT" --insecure-skip-tls-verify=true

# 6. Verify EKS connectivity
echo "▶ Verifying connection to cluster..."
if kubectl get ns >/dev/null 2>&1; then
    echo "✔ Successfully connected to EKS cluster."
    echo "✔ Active Context: $(kubectl config current-context)"
else
    echo "❌ Connection failed. Check SSM logs in $LOG_FILE"
    exit 1
fi
