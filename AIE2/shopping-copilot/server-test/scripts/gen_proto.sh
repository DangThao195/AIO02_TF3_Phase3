#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python -m grpc_tools.protoc \
  -I proto \
  --python_out=server \
  --grpc_python_out=server \
  proto/product_reviews.proto \
  proto/products.proto \
  proto/accounting.proto
