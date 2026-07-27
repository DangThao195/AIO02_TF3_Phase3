"""Correlation & dedup (C2 §Correlation) — many signals become ONE incident.

Two jobs:
  1. Dedup: a repeated fingerprint {service|sli|rule} within a window is folded, not re-paged.
  2. Correlate: signals on services in the same dependency chain within the same time window
     are grouped so on-call gets one page ("payment slow -> checkout failing"), not ten.

Dependency map is from onboarding/ARCHITECTURE.md. `blast_radius` answers "what else is
probably affected" — the field on-call reads first.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..common.schemas import Severity, SourceLayer
from .detector_anomaly import AnomalySignal
from .detector_burnrate import BurnSignal


DEPENDENCY_MAP: dict[str, list[str]] = {
    "checkout": ["cart", "product-catalog", "currency", "shipping", "quote", "payment", "email", "kafka"],
    "frontend": ["product-catalog", "recommendation", "ad", "cart", "product-reviews"],
    "cart": ["valkey-cart"],
    "product-reviews": ["product-catalog", "llm"],
    "accounting": ["kafka"],
    "fraud-detection": ["kafka"],
}


def _upstream_of(service: str) -> list[str]:
    return [parent for parent, deps in DEPENDENCY_MAP.items() if service in deps]


@dataclass
class Incident:
    incident_id: str
    primary: BurnSignal
    correlated_signals: list[str] = field(default_factory=list)
    blast_radius: list[str] = field(default_factory=list)
    # service -> unix ts của lần đầu thấy tín hiệu trên service đó trong cửa sổ hiện tại.
    # Cho causal-by-time ranking (W2-D2): cái gì động TRƯỚC thì khả nghi hơn cái động sau.
    first_seen: dict[str, float] = field(default_factory=dict)


class Correlator:
    def __init__(self, dedup_window_s: int = 900, clock=time.time):
        self._dedup_window = dedup_window_s
        self._clock = clock
        self._seen: dict[str, float] = {}
        # First-seen per SERVICE (khác _seen per-fingerprint): giữ mốc thời gian tín hiệu
        # đầu tiên trên mỗi service để RCA xếp hạng theo thứ tự nhân quả. Evict cùng cửa sổ.
        self._service_first_seen: dict[str, float] = {}

    @staticmethod
    def fingerprint(sig: BurnSignal) -> str:
        return f"{sig.service}|{sig.sli}|{sig.source_layer.value}"

    def correlate(
        self,
        signals: list[BurnSignal],
        anomalies: list[AnomalySignal] | None = None,
    ) -> list[Incident]:
        """Group signals into incidents via the dependency graph.

        - Burn-rate signals in the same cluster fold into one incident (worst = primary).
        - Anomalies in a burn-rate cluster ENRICH that incident (the "why" context on-call
          reads first) instead of paging separately.
        - Anomalies with NO burn-rate nearby become their own WARNING incident — this is the
          "catch the injected fault before the system dies" path. Never critical (layer 2).
        Deduped fingerprints (repeat within window) are dropped so a storm folds, not floods.
        """
        # Evict stale seen fingerprints to prevent memory leak
        now = self._clock()
        cutoff = now - self._dedup_window
        stale_keys = [k for k, t in self._seen.items() if t < cutoff]
        for k in stale_keys:
            self._seen.pop(k, None)
        for k in [k for k, t in self._service_first_seen.items() if t < cutoff]:
            self._service_first_seen.pop(k, None)

        anomalies = anomalies or []
        # Ghi mốc first-seen cho MỌI tín hiệu đến (kể cả bản dup sẽ bị fold) — mốc sớm nhất
        # là thông tin nhân quả, dedup chỉ là chính sách paging.
        for s in signals:
            self._service_first_seen.setdefault(s.service, now)
        for a in anomalies:
            self._service_first_seen.setdefault(a.service, now)
        fresh = [s for s in signals if not self._is_duplicate_burn(s)]
        sev_rank = {"critical": 0, "warning": 1, "info": 2}
        fresh.sort(key=lambda s: (sev_rank[s.severity.value], -s.burn_rate))

        incidents: list[Incident] = []
        claimed: set[str] = set()
        now = int(self._clock())


        for sig in fresh:
            if sig.service in claimed:
                continue
            cluster = self._cluster_services(sig.service)
            claimed |= cluster
            correlated = [
                f"{o.service} {o.sli} burn {o.burn_rate}x ({o.severity.value})"
                for o in fresh if o is not sig and o.service in cluster
            ]

            correlated += [
                f"[anomaly] {a.note} conf={a.confidence}"
                for a in anomalies if a.service in cluster
            ]
            incidents.append(Incident(
                incident_id=f"TF3-{now}-{sig.service}",
                primary=sig,
                correlated_signals=correlated,
                blast_radius=self._blast_radius(sig.service),
                first_seen={s: t for s, t in self._service_first_seen.items() if s in cluster},
            ))
            self._seen[self.fingerprint(sig)] = self._clock()


        for a in anomalies:
            if a.service in claimed or self._is_duplicate_anomaly(a):
                continue
            a_cluster = self._cluster_services(a.service)
            claimed |= a_cluster
            incidents.append(Incident(
                incident_id=f"TF3-{now}-{a.service}-anomaly",
                primary=self._anomaly_as_primary(a),
                correlated_signals=[f"[anomaly] {a.note} conf={a.confidence}"],
                blast_radius=self._blast_radius(a.service),
                first_seen={s: t for s, t in self._service_first_seen.items() if s in a_cluster},
            ))
            self._seen[self._anomaly_fp(a)] = self._clock()

        return incidents

    def _is_duplicate_burn(self, sig: BurnSignal) -> bool:
        last = self._seen.get(self.fingerprint(sig))
        return last is not None and (self._clock() - last) < self._dedup_window

    @staticmethod
    def _anomaly_fp(a: AnomalySignal) -> str:
        return f"{a.service}|{a.sli}|{a.source_layer.value}"

    def _is_duplicate_anomaly(self, a: AnomalySignal) -> bool:
        last = self._seen.get(self._anomaly_fp(a))
        return last is not None and (self._clock() - last) < self._dedup_window

    @staticmethod
    def _anomaly_as_primary(a: AnomalySignal) -> BurnSignal:
        """Adapt an anomaly into the BurnSignal shape so the emitter can build one AlertEvent
        type. burn_rate is not meaningful here, so 0.0; severity stays WARNING/INFO."""
        return BurnSignal(
            service=a.service, sli=a.sli, severity=a.severity, burn_rate=0.0,
            error_ratio=0.0, target=0.0, long_window="-", short_window="-",
            source_layer=SourceLayer.ML_ANOMALY,
        )

    def _cluster_services(self, service: str) -> set[str]:
        """A cluster = the service, its direct downstreams, and its direct upstreams."""
        return {service, *DEPENDENCY_MAP.get(service, []), *_upstream_of(service)}

    def _blast_radius(self, service: str) -> list[str]:
        """Who is probably affected: the service itself + upstream entry points that depend on it."""
        return sorted({service, *_upstream_of(service)})
