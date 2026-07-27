"""Action policy tests — đề xuất action ĐÚNG theo service khi flood/quá tải (C6)."""
from __future__ import annotations

from ai_engine.aiops.action_policy import propose_for
from ai_engine.common.schemas import ActionType


def test_checkout_scales():
    p = propose_for("checkout")
    assert p is not None and p.action is ActionType.SCALE
    assert p.target == "deployment/checkout"
    assert p.rollback_plan  # bắt buộc có rollback


def test_frontend_flood_scales():
    # loadGeneratorFloodHomepage / latency p95 vỡ -> scale frontend (không tắt flag)
    p = propose_for("frontend")
    assert p is not None and p.action is ActionType.SCALE
    assert p.target == "deployment/frontend"


def test_frontend_proxy_alias_scales():
    p = propose_for("frontend-proxy")
    assert p is not None and p.target == "deployment/frontend"


def test_kafka_scales_consumer():
    p = propose_for("kafka")
    assert p is not None and p.action is ActionType.SCALE
    assert "consumer" in p.target


def test_cart_never_auto_proposes():
    # INC-2: cart single-replica — KHÔNG auto-restart/scale, để tránh mất giỏ
    assert propose_for("cart") is None


def test_unknown_service_no_action():
    # mặc định an toàn: chỉ alert/RCA, không mutate
    assert propose_for("some-random-svc") is None
    assert propose_for("email") is None
    assert propose_for("ad") is None


def test_every_proposal_has_rollback():
    # C6 invariant: mọi action đề xuất phải có rollback_plan
    for svc in ("checkout", "frontend", "kafka"):
        p = propose_for(svc)
        assert p and p.rollback_plan.strip()
