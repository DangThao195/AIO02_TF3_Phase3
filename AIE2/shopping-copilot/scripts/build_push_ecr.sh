#!/usr/bin/env bash
# build_push_ecr.sh — Build và push Docker image shopping-copilot lên AWS ECR
#
# Cách dùng:
#   chmod +x scripts/build_push_ecr.sh
#   ./scripts/build_push_ecr.sh [TAG]
#
# Ví dụ:
#   ./scripts/build_push_ecr.sh v1.0.0
#   ./scripts/build_push_ecr.sh latest

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-197826770971}"
ECR_REPO="shopping-copilot"
IMAGE_TAG="${1:-latest}"

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
FULL_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"

# ── Script chạy từ thư mục shopping-copilot ──────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "================================================="
echo " Building Shopping Copilot Docker Image"
echo "  Registry : ${ECR_REGISTRY}"
echo "  Image    : ${ECR_REPO}:${IMAGE_TAG}"
echo "================================================="

# ── Step 1: Tạo ECR repo nếu chưa có ─────────────────────────────────────────
echo "[1/4] Ensuring ECR repository exists..."
aws ecr describe-repositories \
    --repository-names "${ECR_REPO}" \
    --region "${AWS_REGION}" > /dev/null 2>&1 || \
aws ecr create-repository \
    --repository-name "${ECR_REPO}" \
    --region "${AWS_REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256

# ── Step 2: Authenticate Docker với ECR ──────────────────────────────────────
echo "[2/4] Authenticating Docker with ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# ── Step 3: Build image ───────────────────────────────────────────────────────
echo "[3/4] Building Docker image..."
docker build \
    --platform linux/amd64 \
    -t "${ECR_REPO}:${IMAGE_TAG}" \
    -t "${FULL_IMAGE}" \
    "${PROJECT_DIR}"

# ── Step 4: Push lên ECR ─────────────────────────────────────────────────────
echo "[4/4] Pushing image to ECR..."
docker push "${FULL_IMAGE}"

echo ""
echo "✅ Done! Image pushed:"
echo "   ${FULL_IMAGE}"
echo ""
echo "📋 Thông tin để gửi CDO:"
echo "   ECR Image URI: ${FULL_IMAGE}"
echo "   Region       : ${AWS_REGION}"
echo "   Account ID   : ${AWS_ACCOUNT_ID}"
