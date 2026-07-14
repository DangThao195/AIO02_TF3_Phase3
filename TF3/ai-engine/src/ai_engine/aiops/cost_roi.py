"""Cost model ROI cho AIOps engine — số liệu bảo vệ đầu tư tại Service Health Readout.

Công thức W3-D3:
    monthly_value = downtime_hours_per_month × mttr_reduction × downtime_cost_per_hour
    roi           = monthly_value / monthly_cost
    payback       = monthly_cost / monthly_value   (tháng)

Verdict: ROI > 1.5 → worth · 1.0 < ROI ≤ 1.5 → marginal · ≤ 1.0 → not-worth.

Cạm bẫy được model hoá tường minh: chi phí PHẢI gồm công engineer (thiếu là hụt 3–5×),
không chỉ tiền hạ tầng + token LLM (cái đó `cost_report.py` đã đo). Đây là tầng trên:
cost_report trả lời "engine tốn bao nhiêu", module này trả lời "engine ĐÁNG bao nhiêu".
"""
from __future__ import annotations

from dataclasses import dataclass

WORTH_THRESHOLD = 1.5
MARGINAL_THRESHOLD = 1.0


@dataclass(frozen=True)
class ROIResult:
    monthly_value_usd: float
    monthly_cost_usd: float
    roi: float
    payback_months: float | None  # None nếu value = 0 (không bao giờ hoàn vốn)
    verdict: str  # "worth" | "marginal" | "not-worth"

    def to_markdown(self) -> str:
        payback = f"{self.payback_months:.1f} tháng" if self.payback_months is not None else "∞"
        return "\n".join([
            "| Chỉ số | Giá trị |",
            "|---|---|",
            f"| Giá trị/tháng (MTTR giảm × giờ downtime × chi phí/giờ) | ${self.monthly_value_usd:,.0f} |",
            f"| Chi phí/tháng (hạ tầng + LLM + công engineer) | ${self.monthly_cost_usd:,.0f} |",
            f"| ROI | {self.roi:.2f} |",
            f"| Hoàn vốn | {payback} |",
            f"| Verdict | **{self.verdict}** (worth >1.5 · marginal 1.0–1.5 · not-worth ≤1.0) |",
        ])


def incident_roi(
    *,
    downtime_hours_per_month: float,
    mttr_reduction: float,
    downtime_cost_per_hour_usd: float,
    infra_llm_cost_monthly_usd: float,
    engineer_hours_per_month: float = 0.0,
    engineer_hourly_usd: float = 75.0,
) -> ROIResult:
    """`mttr_reduction` là tỉ lệ [0,1] (vd 0.4 = engine cắt 40% thời gian khắc phục).
    `engineer_hours_per_month` = công xây + vận hành engine — bắt buộc khai, mặc định 0
    chỉ để test; bỏ qua nó là lỗi cost-model kinh điển (W3-D3)."""
    if not (0.0 <= mttr_reduction <= 1.0):
        raise ValueError(f"mttr_reduction must be in [0,1], got {mttr_reduction}")

    value = downtime_hours_per_month * mttr_reduction * downtime_cost_per_hour_usd
    cost = infra_llm_cost_monthly_usd + engineer_hours_per_month * engineer_hourly_usd

    roi = (value / cost) if cost > 0 else 0.0
    payback = (cost / value) if value > 0 else None

    if roi > WORTH_THRESHOLD:
        verdict = "worth"
    elif roi > MARGINAL_THRESHOLD:
        verdict = "marginal"
    else:
        verdict = "not-worth"

    return ROIResult(
        monthly_value_usd=round(value, 2),
        monthly_cost_usd=round(cost, 2),
        roi=round(roi, 2),
        payback_months=round(payback, 2) if payback is not None else None,
        verdict=verdict,
    )
