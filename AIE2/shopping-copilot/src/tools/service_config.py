"""
tools/service_config.py — Địa chỉ gRPC/HTTP của các microservices backend.

Tất cả địa chỉ đọc từ env vars, fallback sang localhost defaults (cho dev local).
"""

import os

CATALOG_ADDR = os.environ.get("CATALOG_ADDR", "localhost:3550")
CART_ADDR    = os.environ.get("CART_ADDR",    "localhost:7070")
REVIEWS_ADDR = os.environ.get("REVIEWS_ADDR", "localhost:9090")
RECO_ADDR    = os.environ.get("RECO_ADDR",    "localhost:8081")
CURRENCY_ADDR = os.environ.get("CURRENCY_ADDR", "localhost:7001")
SHIPPING_ADDR = os.environ.get("SHIPPING_ADDR", "http://localhost:50052")
