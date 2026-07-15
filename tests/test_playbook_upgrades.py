"""Tests cho các nâng cấp từ AIOPS-EXPERIENCE-PLAYBOOK (XBrain W1-W3).

Phủ: rca_guardrail (chaos failure-mode #4), score_candidates (retry-storm fix),
first_seen tracking, KB scoring heuristic, confidence routing, log template miner,
incident ROI model. Không cần cluster/LLM/AWS — mọi thứ fake được.
"""
from __future__ import annotations

import pytest

from ai_engine.aiops.action_policy import RemediationRoute, route_for_confidence
from ai_engine.aiops.correlator import Correlator, Incident
from ai_engine.aiops.cost_roi import incident_roi
from ai_engine.aiops.detector_burnrate import BurnSignal
from ai_engine.aiops.detector_logtemplate import (
    LogTemplateDetector,
    TemplateMiner,
    merge_multiline,
)
from ai_engine.aiops.kb_retriever import retrieve_scored, score_kb_chunk
from ai_engine.aiops.rca_assistant import RCAAssistant, score_candidates
from ai_engine.aiops.rca_guardrail import validate_llm_verdict
from ai_engine.common.schemas import Severity
from ai_engine.common.telemetry import TelemetryError


# ── helpers ──
def _burn(service="checkout", severity=Severity.CRITICAL, burn=14.4):
    return BurnSignal(
        service=service, sli="availability", severity=severity, burn_rate=burn,
        error_ratio=0.05, target=0.99, long_window="1h", short_window="5m",
    )


_GOOD_VERDICT = {
    "root_cause_service": "product-catalog",
    "incident_class": "connection_pool_exhaustion",
    "confidence": 0.9,
    "actions": ["scale product-catalog to 2"],
    "citations": ["INC-1: pool exhaustion khớp log signature"],
}
_CLUSTER = {"checkout", "product-catalog", "payment"}


# ── rca_guardrail ──
def test_guardrail_accepts_valid_verdict():
    v = validate_llm_verdict(_GOOD_VERDICT, cluster_services=_CLUSTER, fallback_candidate="checkout")
    assert v.method == "llm" and v.root_cause_service == "product-catalog"
    assert not v.violations


@pytest.mark.parametrize("patch,expected_reason", [
    ({"root_cause_service": "database-x"}, "not in cluster"),          # bịa service
    ({"incident_class": "quantum_flux"}, "not in RCA_CLASSES"),        # bịa class
    ({"confidence": 1.7}, "outside [0,1]"),
    ({"confidence": "hallucinated"}, "outside [0,1]"),
    ({"actions": []}, "actions empty"),
    ({"citations": []}, "citations empty"),                            # grounded confidence
])
def test_guardrail_rejects_each_violation(patch, expected_reason):
    raw = {**_GOOD_VERDICT, **patch}
    v = validate_llm_verdict(raw, cluster_services=_CLUSTER, fallback_candidate="checkout")
    assert v.method == "graph-fallback" and v.root_cause_service == "checkout"
    assert v.incident_class == "other"
    assert any(expected_reason in viol for viol in v.violations)


def test_guardrail_llm_dead_falls_back():
    v = validate_llm_verdict(None, cluster_services=_CLUSTER, fallback_candidate="checkout")
    assert v.method == "graph-fallback" and v.actions


# ── score_candidates (0.6 structural + 0.4 temporal) ──
def test_earliest_mover_ranks_first():
    fs = {"checkout": 100.0, "product-catalog": 40.0, "payment": 80.0}
    scored = score_candidates("checkout", ["payment", "product-catalog"], fs)
    assert scored[0][0] == "product-catalog" and scored[0][1] == 1.0


def test_candidate_moving_after_primary_is_victim():
    # Retry storm: payment bắn alert SAU khi checkout đã vỡ → temporal 0, score 0.6
    fs = {"checkout": 100.0, "payment": 160.0}
    scored = score_candidates("checkout", ["payment"], fs)
    svc, score, note = scored[0]
    assert score == 0.6 and "victim" in note


def test_no_timestamps_is_neutral():
    scored = score_candidates("checkout", ["payment"], {})
    assert scored[0][1] == 0.8  # 0.6×1.0 + 0.4×0.5


# ── correlator first_seen ──
def test_correlator_records_first_seen_across_ticks():
    t = [1000.0]
    corr = Correlator(clock=lambda: t[0])
    # tick 1: chỉ anomaly trên product-catalog (layer 2 bắt sớm)
    from ai_engine.aiops.detector_anomaly import AnomalySignal
    from ai_engine.common.schemas import SourceLayer
    anom = AnomalySignal(service="product-catalog", sli="latency_p95",
                         severity=Severity.WARNING, current_value=900, baseline_median=100,
                         z_score=8.0, confidence=0.9, source_layer=SourceLayer.ML_ANOMALY)
    corr.correlate([], [anom])
    # tick 2 (60s sau): burn-rate checkout vỡ
    t[0] = 1060.0
    incidents = corr.correlate([_burn()], [anom])
    burn_inc = next(i for i in incidents if i.primary.service == "checkout")
    assert burn_inc.first_seen["product-catalog"] == 1000.0
    assert burn_inc.first_seen["checkout"] == 1060.0


# ── KB scoring heuristic ──
def test_kb_chunk_scoring():
    inc1 = ("INC-1 checkout chậm. product-catalog cạn pool. "
            "kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2. vỡ SLO")
    s = score_kb_chunk(inc1, cluster_services={"checkout", "product-catalog"},
                       severity="critical")
    # +0.4 (root deploy/product-catalog ∈ cluster) +0.4 (2 service trùng) +0.2 (sev) = 1.0
    assert s == 1.0
    assert score_kb_chunk("hôm nay trời đẹp", cluster_services={"checkout"},
                          severity="critical") == 0.0


async def test_retrieve_scored_filters_below_threshold():
    class FakeKB:
        async def retrieve(self, query, top_k=3):
            return [
                {"text": "scale deploy/product-catalog checkout vỡ SLO", "score": 0.9},
                {"text": "nội dung không liên quan gì", "score": 0.8},
            ]
    kept = await retrieve_scored(FakeKB(), query="q",
                                 cluster_services={"checkout", "product-catalog"},
                                 severity="critical")
    assert len(kept) == 1 and kept[0][0] >= 0.2


# ── confidence routing ──
@pytest.mark.parametrize("conf,route", [
    (1.0, RemediationRoute.AUTO_QUEUE),
    (0.86, RemediationRoute.AUTO_QUEUE),
    (0.85, RemediationRoute.INVESTIGATE),   # biên: không auto ở đúng ngưỡng
    (0.6, RemediationRoute.INVESTIGATE),
    (0.59, RemediationRoute.ESCALATE),
    (0.0, RemediationRoute.ESCALATE),
])
def test_route_for_confidence(conf, route):
    assert route_for_confidence(conf) is route


# ── log template detector ──
def test_merge_multiline_folds_stack_trace():
    lines = [
        "ERROR NullPointerException in OrderService",
        "  at com.techx.OrderService.place(OrderService.java:42)",
        "  at com.techx.Api.handle(Api.java:10)",
        "Caused by: java.sql.SQLException pool exhausted",
        "INFO order 123 placed",
    ]
    events = merge_multiline(lines)
    assert len(events) == 2 and "Caused by" in events[0]


def test_miner_groups_similar_lines_into_one_template():
    m = TemplateMiner()
    _, new1 = m.add("connection to 10.0.0.1 timed out after 30ms", 0)
    tpl, new2 = m.add("connection to 10.0.0.9 timed out after 55ms", 0)
    assert new1 is True and new2 is False
    assert "<*>" in tpl.text() and m.template_count == 1


def test_new_template_signal_only_after_warmup():
    det = LogTemplateDetector(warmup_windows=2)
    assert det.observe_window("checkout", ["pool exhausted for db main"]) == []
    assert det.observe_window("checkout", ["pool exhausted for db main"]) == []
    sigs = det.observe_window("checkout", ["BRAND NEW breaker OPEN state stuck"])
    assert any(s.sli == "log_new_template" for s in sigs)
    assert all(s.severity is Severity.WARNING for s in sigs)  # layer 2: không critical


def test_template_count_spike_detected():
    det = LogTemplateDetector(warmup_windows=0, spike_min_history=10)
    for _ in range(11):
        det.observe_window("checkout", ["pool exhausted for db main"] * 3)
    sigs = det.observe_window("checkout", ["pool exhausted for db main"] * 60)
    spike = [s for s in sigs if s.sli == "log_template_spike"]
    assert spike and spike[0].current_value == 60.0


def test_template_silence_detected():
    """W1-D2 inter-arrival: template đều đặn bỗng câm = tín hiệu mà count-spike bỏ sót."""
    det = LogTemplateDetector(warmup_windows=0, spike_min_history=10)
    for _ in range(11):
        det.observe_window("checkout", ["heartbeat ok from worker 1"] * 3)
    sigs = det.observe_window("checkout", [])  # service câm hẳn
    silence = [s for s in sigs if s.sli == "log_template_silence"]
    assert silence and silence[0].current_value == 0.0
    assert silence[0].severity is Severity.WARNING


# ── IsolationForest (feature engineering bắt buộc — W1-D1) ──
def test_build_features_shape_and_content():
    from ai_engine.aiops.detector_iforest import build_features
    series = [float(i) for i in range(30)]
    rows = build_features(series, window=12, lag_k=12)
    assert len(rows) == 18 and len(rows[0]) == 6  # ≥5 feature theo playbook
    # hàng đầu (i=12): value=12, lag_1=11, lag_k=0, rate=1
    assert rows[0][0] == 12.0 and rows[0][4] == 11.0 and rows[0][5] == 0.0 and rows[0][3] == 1.0


def test_iforest_flags_spike_and_passes_normal():
    import math
    from ai_engine.aiops.detector_iforest import IForestSeriesDetector
    det = IForestSeriesDetector()
    if not det.available:
        pytest.skip("sklearn not installed ([ml] extra)")
    baseline = [10.0 + 0.5 * math.sin(i) for i in range(200)]
    spike = det.evaluate_series([*baseline, 50.0])
    # normal = điểm TIẾP NỐI thật của chuỗi (sin(200)) — không phải giá trị bịa gần đúng;
    # iforest đủ nhạy để phạt điểm lệch quỹ đạo, nên "normal" phải normal thật.
    normal = det.evaluate_series([*baseline, 10.0 + 0.5 * math.sin(200)])
    assert spike is not None and spike.is_anomaly and spike.confidence >= 0.7
    assert normal is not None and not normal.is_anomaly


def test_iforest_catches_pattern_anomaly_zscore_misses():
    """Điểm cuối GIÁ TRỊ bình thường (10.0) nhưng vừa rơi từ 50 → rate-of-change/lag
    bất thường: multivariate feature bắt được, z-score điểm đơn thì không."""
    import math
    from ai_engine.aiops.detector_iforest import IForestSeriesDetector
    det = IForestSeriesDetector()
    if not det.available:
        pytest.skip("sklearn not installed ([ml] extra)")
    baseline = [10.0 + 0.5 * math.sin(i) for i in range(200)]
    verdict = det.evaluate_series([*baseline, 50.0, 10.0])  # value cuối = 10 (bình thường)
    assert verdict is not None and verdict.is_anomaly


# ── incident ROI ──
def test_roi_worth_and_engineer_cost_included():
    r = incident_roi(downtime_hours_per_month=4, mttr_reduction=0.5,
                     downtime_cost_per_hour_usd=10_000,
                     infra_llm_cost_monthly_usd=500,
                     engineer_hours_per_month=40, engineer_hourly_usd=75)
    assert r.monthly_cost_usd == 3500.0          # 500 + 40×75 — công engineer PHẢI tính
    assert r.monthly_value_usd == 20000.0
    assert r.verdict == "worth" and r.payback_months < 1


def test_roi_not_worth_when_downtime_cheap():
    r = incident_roi(downtime_hours_per_month=1, mttr_reduction=0.3,
                     downtime_cost_per_hour_usd=500,
                     infra_llm_cost_monthly_usd=200,
                     engineer_hours_per_month=10)
    assert r.verdict == "not-worth"


def test_roi_rejects_bad_reduction():
    with pytest.raises(ValueError):
        incident_roi(downtime_hours_per_month=1, mttr_reduction=40,
                     downtime_cost_per_hour_usd=1, infra_llm_cost_monthly_usd=1)


# ── RCAAssistant integration: guardrail + KB + timestamp trong build() ──
class _FakeJaeger:
    async def find_error_traces(self, service, limit=5):
        return []


class _FakeOS:
    async def search(self, index, body):
        return {}


class _DeadKB:
    async def retrieve(self, query, top_k=3):
        raise TelemetryError("kb down")


async def test_build_validates_hallucinated_llm_verdict():
    hallucinating = lambda ctx: {  # noqa: E731
        "root_cause_service": "service-does-not-exist",
        "incident_class": "other", "confidence": 0.95,
        "actions": ["restart everything"], "citations": ["trust me"],
    }
    rca = RCAAssistant(None, _FakeOS(), _FakeJaeger(), llm_diagnoser=hallucinating)
    # KHÔNG có first_seen → temporal trung tính → H1 score 0.8 < 0.9 → LLM được gọi
    incident = Incident(
        incident_id="TF3-test-checkout", primary=_burn(),
        correlated_signals=["product-catalog availability burn 6x (critical)"],
        blast_radius=["checkout"],
    )
    pack = await rca.build(incident)
    assert pack.llm_verdict["method"] == "graph-fallback"
    assert pack.llm_verdict["violations"]
    assert pack.hypotheses[0].rank_score == 0.8
    assert "Guardrail loại" in pack.to_markdown()


async def test_build_skips_llm_when_graph_confident():
    """W2-D3 conditional skipping: graph+temporal score ≥0.9 → LLM không được gọi."""
    called = []
    diagnoser = lambda ctx: called.append(1) or {}  # noqa: E731
    rca = RCAAssistant(None, _FakeOS(), _FakeJaeger(), llm_diagnoser=diagnoser)
    incident = Incident(
        incident_id="TF3-test-skip", primary=_burn(),
        correlated_signals=["product-catalog availability burn 6x (critical)"],
        blast_radius=["checkout"],
        first_seen={"product-catalog": 10.0, "checkout": 50.0},  # causal order rõ → 1.0
    )
    pack = await rca.build(incident)
    assert called == []  # LLM KHÔNG được gọi — cost 0
    assert pack.llm_verdict["method"] == "graph-high-confidence"
    assert pack.llm_verdict["root_cause_service"] == "product-catalog"
    assert pack.llm_verdict["citations"]  # grounded như mọi verdict khác


async def test_build_kb_dead_marks_incomplete_but_ships():
    rca = RCAAssistant(None, _FakeOS(), _FakeJaeger(), kb_retriever=_DeadKB())
    incident = Incident(incident_id="TF3-test-kb", primary=_burn(), blast_radius=["checkout"])
    pack = await rca.build(incident)
    assert any("kb" in i for i in pack.incomplete)
    assert pack.to_markdown()  # pack vẫn ship (C3)
