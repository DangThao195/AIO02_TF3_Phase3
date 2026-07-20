"""
TDD Test Suite for AlertCorrelator — 2 bug fixes:
  - Bug 1: Time Window Clustering (alerts trong cùng window phải gộp chung)
  - Bug 2: Upstream Graph Traversal (select_rca_candidate phải duyệt upstream)

Chạy:  python -m pytest aiops-engine/tests/test_alert_correlator.py -v
"""
import time
import sys
import os
import json
import pytest


# Đưa thư mục aiops-engine vào sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alert_correlator import AlertCorrelator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
SERVICES_JSON = os.path.join(os.path.dirname(__file__), "..", "services.json")


def make_alert(service: str, alertname: str = "HighLatency",
               severity: str = "critical", trace_id: str = "trace-abc",
               fired_at_override: float = None) -> dict:
    return {
        "labels": {"service": service, "alertname": alertname, "severity": severity},
        "annotations": {"trace_id": trace_id},
        "fired_at": fired_at_override if fired_at_override is not None else time.time(),
    }


# ===========================================================================
# BUG 1 — Time Window Clustering
# ===========================================================================

class TestTimeWindowClustering:
    """
    Alert của product-catalog (t=0) và checkout (t+10s) phải được gộp vào
    CÙNG 1 cluster khi chênh lệch thời gian <= window_seconds.
    """

    def test_two_alerts_within_window_produce_one_cluster(self):
        """
        Khi product-catalog và checkout đến trong cùng time window (10s < 60s),
        correlator phải trả về ĐÚNG 1 cluster, không phải 2.
        """
        corr = AlertCorrelator(config_path=SERVICES_JSON, window_seconds=60)
        t0 = time.time()

        alert1 = make_alert("product-catalog", fired_at_override=t0)
        alert2 = make_alert("checkout", fired_at_override=t0 + 10)

        clusters = corr.correlate_alerts_windowed([alert1, alert2])

        assert len(clusters) == 1, (
            f"Mong đợi 1 cluster (cascade), nhận được {len(clusters)}. "
            "Bug 1: correlator đang tạo 2 incident riêng biệt thay vì gộp chung."
        )

    def test_alerts_outside_window_produce_separate_clusters(self):
        """
        Khi 2 alert cách nhau > window_seconds và không liên quan topology,
        chúng phải được xử lý thành 2 cluster riêng.
        """
        corr = AlertCorrelator(config_path=SERVICES_JSON, window_seconds=60)
        t0 = time.time()

        alert1 = make_alert("product-catalog", fired_at_override=t0)
        alert2 = make_alert("accounting",      fired_at_override=t0 + 300)

        clusters = corr.correlate_alerts_windowed([alert1, alert2])

        assert len(clusters) == 2, (
            f"Mong đợi 2 clusters (cách nhau 300s, không liên quan), nhận {len(clusters)}."
        )

    def test_three_cascade_alerts_within_window_become_one_cluster(self):
        """
        frontend → checkout → product-catalog đều bị alert trong 30s
        phải gộp thành 1 cluster duy nhất.
        """
        corr = AlertCorrelator(config_path=SERVICES_JSON, window_seconds=60)
        t0 = time.time()

        alerts = [
            make_alert("product-catalog", fired_at_override=t0),
            make_alert("checkout",        fired_at_override=t0 + 10),
            make_alert("frontend",        fired_at_override=t0 + 20),
        ]

        clusters = corr.correlate_alerts_windowed(alerts)

        assert len(clusters) == 1, (
            f"3 alert cascade trong 30s phải cho 1 cluster, nhận {len(clusters)}."
        )


# ===========================================================================
# BUG 2 — Upstream Graph Traversal (NetworkX)
# ===========================================================================

# Graph kiểm thử có cạnh checkout → product-catalog (checkout gọi catalog để check stock)
TOPOLOGY_FOR_BUG2 = {
    "frontend": ["checkout", "cart"],
    "checkout": ["payment", "product-catalog"],   # checkout phụ thuộc product-catalog
    "product-catalog": ["postgresql"],
    "payment": ["payments-db"],
}

@pytest.fixture
def tmp_services_json(tmp_path):
    p = tmp_path / "services.json"
    p.write_text(json.dumps(TOPOLOGY_FOR_BUG2))
    return str(p)


class TestUpstreamGraphTraversal:
    """
    Khi checkout bị alert nhưng product-catalog (upstream của checkout)
    cũng bị alert trong cùng time-window, RCA phải chọn product-catalog
    DỰA TRÊN TOPOLOGY (upstream traversal), không phải chỉ first-drift.
    """

    def test_upstream_topology_wins_over_local_trigger(self, tmp_services_json):
        """
        Topo: checkout → product-catalog (checkout phụ thuộc product-catalog).
        product-catalog fired CÙNG LÚC checkout (t0 == t0).
        Không có first-drift advantage — topology phải quyết định.
        Culprit phải là product-catalog (upstream), không phải checkout (victim).
        """
        corr = AlertCorrelator(config_path=tmp_services_json, window_seconds=60)
        t0 = time.time()

        alerts = [
            make_alert("checkout",        fired_at_override=t0),    # victim
            make_alert("product-catalog", fired_at_override=t0),    # upstream, CÙNG lúc
        ]

        clusters = corr.correlate_alerts_windowed(alerts)
        assert len(clusters) == 1, "2 alerts liên quan topology phải gộp 1 cluster"

        culprit = clusters[0]["culprit_service"]
        assert culprit == "product-catalog", (
            f"product-catalog là upstream của checkout (checkout→product-catalog), "
            f"phải là culprit ngay cả khi fired_at bằng nhau. Nhận: '{culprit}'. "
            "Bug 2: thuật toán không dùng NetworkX traversal upstream."
        )

    def test_upstream_topology_wins_even_if_victim_fires_first(self, tmp_services_json):
        """
        Topo: checkout → product-catalog.
        checkout fired TRƯỚC product-catalog (t0 < t0+5).
        Dù checkout fired trước, product-catalog vẫn phải là culprit vì là UPSTREAM.
        (First-drift không được override topology khi có quan hệ upstream rõ ràng.)
        """
        corr = AlertCorrelator(config_path=tmp_services_json, window_seconds=60)
        t0 = time.time()

        alerts = [
            make_alert("checkout",        fired_at_override=t0),       # victim nhưng fired trước
            make_alert("product-catalog", fired_at_override=t0 + 5),   # upstream fired sau
        ]

        clusters = corr.correlate_alerts_windowed(alerts)
        assert len(clusters) == 1

        culprit = clusters[0]["culprit_service"]
        assert culprit == "product-catalog", (
            f"product-catalog là upstream trực tiếp của checkout → phải là culprit "
            f"dù fired_at muộn hơn. Nhận: '{culprit}'."
        )

    def test_select_rca_candidate_picks_upstream_over_downstream(self, tmp_services_json):
        """
        Gọi trực tiếp select_rca_candidate_scored với graph checkout→product-catalog.
        product-catalog fired CÙNG LÚC (tie-break bằng topology, không first-drift).
        """
        corr = AlertCorrelator(config_path=tmp_services_json, window_seconds=60)
        t0 = time.time()
        winner = corr.select_rca_candidate_scored([
            ("checkout",        t0),
            ("product-catalog", t0),   # same fired_at → topology must decide
        ])
        assert winner == "product-catalog", (
            f"NetworkX upstream traversal: product-catalog là ancestor của checkout "
            f"→ upstream_score=1 phải lớn hơn checkout upstream_score=0. Nhận: '{winner}'."
        )

    def test_first_drift_time_breaks_tie_when_no_upstream_relation(self, tmp_services_json):
        """
        payment và postgresql đều không phải upstream của nhau.
        Tie-break bằng first-drift: payment fired trước → payment là culprit.
        """
        corr = AlertCorrelator(config_path=tmp_services_json, window_seconds=60)
        t0 = time.time()
        winner = corr.select_rca_candidate_scored([
            ("payment",     t0),
            ("postgresql",  t0 + 5),
        ])
        assert winner == "payment", (
            f"Không có upstream relation → first-drift quyết định. Nhận: '{winner}'."
        )

    def test_single_service_always_culprit(self, tmp_services_json):
        """Edge case: 1 service → luôn là culprit."""
        corr = AlertCorrelator(config_path=tmp_services_json, window_seconds=60)
        alerts = [make_alert("recommendation")]
        clusters = corr.correlate_alerts_windowed(alerts)
        assert clusters[0]["culprit_service"] == "recommendation"
