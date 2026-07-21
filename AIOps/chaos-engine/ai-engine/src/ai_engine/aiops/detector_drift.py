"""Drift detector chuyên biệt — AIOps mở rộng (RULES §4 "phát hiện drift").

Khác các detector khác ở CÂU HỎI nó trả lời:
  - `detector_anomaly` hỏi: "điểm NÀY có lạ so với baseline không?" (point anomaly)
  - `detector_iforest` hỏi: "pattern này có lạ không?" (contextual anomaly)
  - **drift hỏi: "PHÂN PHỐI đã đổi chưa?"** — không có điểm nào lạ cả, nhưng cả đám đã
    dịch sang chỗ khác. Đây là thứ z-score/iforest bỏ sót vì baseline trôi theo.

Vì sao AIOps cần drift (không chỉ là chuyện ML):
  1. **Data drift trên telemetry**: p95 latency tuần này lệch hẳn tuần trước dù chưa vỡ SLO
     → hệ đang xấu dần, error budget sẽ cháy. Bắt sớm = sửa trước khi page.
  2. **Model drift của chính engine**: baseline (median/MAD) học từ 1 tuần cũ; nếu phân phối
     đổi mà baseline không đổi → detector báo nhầm liên tục HOẶC điếc hoàn toàn. Drift là
     tín hiệu "đến lúc re-baseline" — tự giám sát chính mình.

Phương pháp: **PSI (Population Stability Index)** — chuẩn công nghiệp cho drift, rẻ, giải
thích được:
    PSI = Σ (actual% − expected%) × ln(actual% / expected%)
Ngưỡng quy ước (Siddiqi, dùng rộng rãi trong credit-risk và ML monitoring):
    PSI < 0.1        → ổn định
    0.1 ≤ PSI < 0.25 → drift nhẹ (INFO — theo dõi)
    PSI ≥ 0.25       → drift đáng kể (WARNING — cần re-baseline / điều tra)

Chọn PSI thay vì KS-test vì: không cần scipy (thuần Python), cho ra một CON SỐ có ngưỡng
quy ước (KS cho p-value — khó giải thích với on-call), và ổn định với mẫu vừa (~100-2000).

Kỷ luật layer-2: WARNING tối đa, không page. Thiếu dữ liệu → im lặng, không đoán.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from ..common.schemas import Severity, SourceLayer
from .detector_anomaly import AnomalySignal

log = logging.getLogger("ai_engine.detector_drift")

PSI_MINOR = 0.1      # dưới ngưỡng này = ổn định
PSI_MAJOR = 0.25     # trên ngưỡng này = drift đáng kể
DEFAULT_BINS = 10
MIN_SAMPLES = 50     # < 50 mẫu mỗi bên thì PSI nhiễu, không đáng tin
_EPS = 1e-6          # chặn ln(0) khi một bin rỗng


@dataclass(frozen=True)
class DriftResult:
    psi: float
    drifted: bool          # PSI ≥ PSI_MAJOR
    severity: str          # "stable" | "minor" | "major"
    n_expected: int
    n_actual: int

    def to_dict(self) -> dict:
        return {"psi": self.psi, "drifted": self.drifted, "severity": self.severity,
                "n_expected": self.n_expected, "n_actual": self.n_actual}


def _quantile_edges(values: list[float], bins: int) -> list[float]:
    """Chia bin theo PHÂN VỊ của baseline (không phải khoảng đều) — quan trọng với dữ liệu
    lệch phải như latency: khoảng đều sẽ dồn 99% mẫu vào 1 bin, PSI mất ý nghĩa."""
    s = sorted(values)
    n = len(s)
    edges = [s[0]]
    for i in range(1, bins):
        idx = int(i * n / bins)
        edges.append(s[min(idx, n - 1)])
    edges.append(s[-1])
    # loại edge trùng (chuỗi nhiều giá trị giống nhau) để không tạo bin rỗng vô nghĩa
    dedup = [edges[0]]
    for e in edges[1:]:
        if e > dedup[-1]:
            dedup.append(e)
    return dedup


def _bin_ratios(values: list[float], edges: list[float]) -> list[float]:
    """Tỉ lệ mẫu rơi vào từng bin [edge_i, edge_i+1). Giá trị NGOÀI biên baseline (v < min hoặc
    v > max của expected) dồn vào bin biên gần nhất — đây CHÍNH LÀ tín hiệu drift ta muốn bắt
    (actual dịch ra ngoài dải baseline), nên gom vào biên là đúng, không phải mất mát. Lưu ý:
    nếu actual có nhiều outlier cùng phía, chúng dồn 1 bin biên → PSI phóng đại về phía đó
    (drift mạnh) — đúng hướng, nhưng đọc số nhớ đây là 'dịch ra ngoài dải', không phải 'đổi hình dạng giữa dải'."""
    counts = [0] * (len(edges) - 1)
    for v in values:
        placed = False
        for i in range(len(counts)):
            lo, hi = edges[i], edges[i + 1]
            if (lo <= v < hi) or (i == len(counts) - 1 and v == hi):
                counts[i] += 1
                placed = True
                break
        if not placed:  # v < min baseline → bin 0; v > max baseline → bin cuối
            counts[0 if v < edges[0] else -1] += 1
    total = sum(counts) or 1
    return [c / total for c in counts]


def population_stability_index(
    expected: list[float], actual: list[float], bins: int = DEFAULT_BINS
) -> DriftResult | None:
    """PSI giữa baseline (`expected`) và cửa sổ hiện tại (`actual`).
    None = không đủ mẫu để kết luận (im lặng còn hơn đoán)."""
    if len(expected) < MIN_SAMPLES or len(actual) < MIN_SAMPLES:
        return None

    edges = _quantile_edges(expected, bins)
    if len(edges) < 3:  # baseline gần như hằng số → PSI vô nghĩa
        return None

    exp_ratios = _bin_ratios(expected, edges)
    act_ratios = _bin_ratios(actual, edges)

    psi = 0.0
    for e, a in zip(exp_ratios, act_ratios):
        e_safe = max(e, _EPS)
        a_safe = max(a, _EPS)
        psi += (a_safe - e_safe) * math.log(a_safe / e_safe)

    psi = round(psi, 4)
    if psi >= PSI_MAJOR:
        sev = "major"
    elif psi >= PSI_MINOR:
        sev = "minor"
    else:
        sev = "stable"
    return DriftResult(psi=psi, drifted=psi >= PSI_MAJOR, severity=sev,
                       n_expected=len(expected), n_actual=len(actual))


@dataclass(frozen=True)
class DriftMetric:
    """So phân phối cửa sổ gần (`actual_query`) với baseline dài (`baseline_query`)."""

    name: str
    service: str
    baseline_query: str   # vd chuỗi 1 tuần TRƯỚC cửa sổ hiện tại
    actual_query: str     # vd chuỗi 1 ngày gần nhất
    unit: str = ""


class DriftDetector:
    """Phát hiện phân phối telemetry đã dịch. Emit AnomalySignal đi chung đường Correlator."""

    def __init__(self, prom, metrics: list[DriftMetric]):
        self._prom = prom
        self._metrics = metrics

    async def evaluate(self) -> list[AnomalySignal]:
        from ..common.telemetry import TelemetryError

        signals: list[AnomalySignal] = []
        for m in self._metrics:
            try:
                baseline = await self._series(m.baseline_query)
                actual = await self._series(m.actual_query)
            except TelemetryError:
                continue

            res = population_stability_index(baseline, actual)
            if res is None or res.severity == "stable":
                continue

            # minor → INFO, major → WARNING. Không bao giờ CRITICAL (burn-rate độc quyền page).
            severity = Severity.WARNING if res.severity == "major" else Severity.INFO
            confidence = round(min(0.95, 0.7 + min(res.psi, 1.0) * 0.25), 2)
            if confidence < 0.7:
                continue

            signals.append(AnomalySignal(
                service=m.service,
                sli=f"{m.name}_drift",
                severity=severity,
                current_value=res.psi,
                baseline_median=0.0,
                z_score=0.0,
                confidence=confidence,
                source_layer=SourceLayer.ML_ANOMALY,
                note=(f"{m.name}: phân phối đã dịch (PSI={res.psi}, {res.severity}) — "
                      f"baseline {res.n_expected} mẫu vs hiện tại {res.n_actual} mẫu. "
                      f"Cân nhắc re-baseline detector nếu đây là 'bình thường mới'."),
            ))
        return signals

    async def _series(self, query: str) -> list[float]:
        results = await self._prom.instant(query)
        values: list[float] = []
        for r in results:
            points = r.get("values")
            if points:
                for p in points:
                    try:
                        values.append(float(p[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
        return values


def default_drift_metrics() -> list[DriftMetric]:
    """So 1 tuần trước (baseline) với 1 ngày gần nhất (actual) trên service doanh thu."""
    def p95(service: str, window: str) -> str:
        return ("histogram_quantile(0.95, sum by (le) (rate("
                f'traces_span_metrics_duration_milliseconds_bucket{{service_name="{service}"}}[{window}])))')

    metrics: list[DriftMetric] = []
    for svc in ("checkout", "frontend", "cart"):
        metrics.append(DriftMetric(
            name=f"{svc}_latency_p95",
            service=svc,
            baseline_query=f"({p95(svc, '5m')})[7d:5m] offset 1d",
            actual_query=f"({p95(svc, '5m')})[1d:5m]",
            unit="ms",
        ))
    return metrics
