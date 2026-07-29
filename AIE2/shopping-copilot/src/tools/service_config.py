"""
Centralised service address resolution.

Toggle all backend gRPC/REST endpoints between real (K8s) and test (local) with
a single env var:

    USE_TEST_SERVER=true   → resolve to TEST_* addresses (localhost:test-port)
    USE_TEST_SERVER=false  → resolve to REAL_* addresses (K8s service DNS)

Each address can still be overridden individually via its env var
(e.g. CART_ADDR=my-custom:9999 for ad-hoc debugging).
"""

import os

from dotenv import load_dotenv

load_dotenv()

_USE_TEST = os.environ.get("USE_TEST_SERVER", "false").lower() in (
    "true", "1", "yes",
)


# ── Real (K8s cluster) address defaults ──
_REAL: dict[str, str] = {
    "CATALOG": "product-catalog:3550",
    "CART": "cart:7070",
    "REVIEWS": "product-reviews:9090",
    "RECOMMENDATION": "recommendation:8080",
    "CURRENCY": "currency:7001",
    "SHIPPING": "http://shipping:50051",
}

# ── Test (local / server-test) address defaults ──
_TEST: dict[str, str] = {
    "CATALOG": "localhost:3550",
    "CART": "localhost:7070",
    "REVIEWS": "localhost:9090",
    "RECOMMENDATION": "localhost:8081",
    "CURRENCY": "localhost:7001",
    "SHIPPING": "http://localhost:50052",
}


def _resolve(service_key: str) -> str:
    env_var = f"{service_key}_ADDR"
    explicit = os.environ.get(env_var)
    if explicit is not None:
        return explicit
    return _TEST[service_key] if _USE_TEST else _REAL[service_key]


# ── Public constants (flat, drop-in replacement for current os.getenv calls) ──

CATALOG_ADDR: str = _resolve("CATALOG")
CART_ADDR: str = _resolve("CART")
REVIEWS_ADDR: str = _resolve("REVIEWS")
RECO_ADDR: str = _resolve("RECOMMENDATION")
CURRENCY_ADDR: str = _resolve("CURRENCY")
SHIPPING_ADDR: str = _resolve("SHIPPING")

# ── Module-level flag for runtime introspection ──

USE_TEST_SERVER: bool = _USE_TEST
