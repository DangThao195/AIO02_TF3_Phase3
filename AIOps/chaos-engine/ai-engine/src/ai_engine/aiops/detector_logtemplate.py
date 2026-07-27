"""Log template detector — C2 layer 2 mở rộng: tín hiệu từ LOG, không chỉ metric.

Drain-style fixed-depth template miner tự viết (W1-D2), không kéo dependency nặng:
nhóm log theo (số token, token đầu) rồi so khớp token-by-token, similarity ≥ 0.45
thì gộp vào template (token lệch → <*>), không thì mở template mới. Depth-4-equivalent
và O(1)/dòng như Drain gốc — đủ cho scale TF3 (100–500 template/service là lành mạnh).

Hai tín hiệu rẻ nhất trước (playbook §1.2):
  1. Template MỚI — "log chưa từng thấy" báo deploy/config đổi/attack. Có warmup
     (grace period) để không flood alert lúc mới bật hoặc ngay sau deploy.
  2. Template-count SPIKE — đếm theo cửa sổ 5 phút, robust z-score (median+MAD) trên
     lịch sử ≥10 cửa sổ, cùng họ với detector_anomaly để giải thích được cho on-call.

Bắt buộc merge multiline TRƯỚC khi parse: stack trace 10–50 dòng là MỘT event —
không merge thì mỗi frame thành một template rác (bài học W1-D2).

Là detector-of-context như mọi layer 2: WARNING tối đa, không bao giờ page critical;
signal đi vào Correlator y hệt AnomalySignal metric (không sửa correlator).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..common.schemas import Severity, SourceLayer
from .detector_anomaly import AnomalySignal, robust_zscore

SIM_THRESHOLD = 0.45
MAX_TEMPLATES_PER_SERVICE = 500

_MASKS = (
    re.compile(r"\b\d+\.\d+\.\d+\.\d+\b"),                        # IPv4
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),  # UUID
    re.compile(r"\b0x[0-9a-f]+\b", re.I),                          # hex
    re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|kb|mb|gb)?\b", re.I),      # số + đơn vị
)

_CONTINUATION = re.compile(r"^(\s+|at\s|\.{3}|Caused by|Traceback|File \")")


def merge_multiline(lines: list[str]) -> list[str]:
    """Gộp dòng continuation (stack frame, caused-by, traceback) vào event trước đó."""
    events: list[str] = []
    for line in lines:
        if events and _CONTINUATION.match(line):
            events[-1] += " " + line.strip()
        else:
            events.append(line.rstrip())
    return [e for e in events if e.strip()]


def _mask_tokens(message: str) -> list[str]:
    masked = message
    for pat in _MASKS:
        masked = pat.sub("<*>", masked)
    return masked.split()


@dataclass
class _Template:
    template_id: int
    tokens: list[str]
    count_current_window: int = 0
    history: list[int] = field(default_factory=list)  # count per closed window
    born_window: int = 0

    def text(self) -> str:
        return " ".join(self.tokens)


class TemplateMiner:
    """Drain-style miner cho MỘT service. Group key = (n_tokens, first_token)."""

    def __init__(self, sim_threshold: float = SIM_THRESHOLD):
        self._sim = sim_threshold
        self._groups: dict[tuple[int, str], list[_Template]] = {}
        self._next_id = 0
        self.template_count = 0

    def add(self, message: str, window_index: int) -> tuple[_Template, bool]:
        """Trả (template, is_new). Wildcard <*> luôn match (Drain rule)."""
        tokens = _mask_tokens(message)
        if not tokens:
            tokens = ["<empty>"]
        key = (len(tokens), tokens[0] if tokens[0] != "<*>" else "<*>")
        group = self._groups.setdefault(key, [])

        best, best_sim = None, 0.0
        for tpl in group:
            same = sum(1 for a, b in zip(tpl.tokens, tokens) if a == b or a == "<*>")
            sim = same / len(tokens)
            if sim > best_sim:
                best, best_sim = tpl, sim

        if best is not None and best_sim >= self._sim:
            best.tokens = [a if a == b else "<*>" for a, b in zip(best.tokens, tokens)]
            best.count_current_window += 1
            return best, False

        # Cap: quá 500 template/service là dấu hiệu threshold sai hoặc log phi cấu trúc —
        # gộp cưỡng bức vào template gần nhất thay vì nổ cardinality.
        if self.template_count >= MAX_TEMPLATES_PER_SERVICE and best is not None:
            best.count_current_window += 1
            return best, False

        tpl = _Template(template_id=self._next_id, tokens=tokens, born_window=window_index,
                        count_current_window=1)
        self._next_id += 1
        self.template_count += 1
        group.append(tpl)
        return tpl, True

    def close_window(self) -> list[_Template]:
        """Chốt cửa sổ: đẩy count hiện tại vào history, reset. Trả mọi template."""
        all_tpls = [t for grp in self._groups.values() for t in grp]
        for t in all_tpls:
            t.history.append(t.count_current_window)
            t.count_current_window = 0
        return all_tpls


class LogTemplateDetector:
    """Stateful qua các cửa sổ (mặc định 5 phút — caller quyết nhịp gọi observe_window)."""

    Z_SPIKE = 4.0
    NEW_TEMPLATE_CONFIDENCE = 0.75
    SILENCE_PRESENCE_MIN = 0.8   # template phải "đều đặn" (≥80% cửa sổ) mới đáng báo khi câm
    SILENCE_CONFIDENCE = 0.75

    def __init__(self, warmup_windows: int = 3, spike_min_history: int = 10):
        self._warmup = warmup_windows
        self._spike_min = spike_min_history
        self._miners: dict[str, TemplateMiner] = {}
        self._window_index: dict[str, int] = {}

    def observe_window(self, service: str, raw_lines: list[str]) -> list[AnomalySignal]:
        """Nạp trọn một cửa sổ log của service, trả các AnomalySignal (WARNING max)."""
        miner = self._miners.setdefault(service, TemplateMiner())
        widx = self._window_index.get(service, 0)
        signals: list[AnomalySignal] = []

        new_templates: list[_Template] = []
        for event in merge_multiline(raw_lines):
            tpl, is_new = miner.add(event, widx)
            if is_new:
                new_templates.append(tpl)

        # Tín hiệu 1 — template mới (sau warmup, tránh flood lúc cold start / ngay sau deploy)
        if widx >= self._warmup:
            for tpl in new_templates:
                signals.append(AnomalySignal(
                    service=service, sli="log_new_template", severity=Severity.WARNING,
                    current_value=1.0, baseline_median=0.0, z_score=0.0,
                    confidence=self.NEW_TEMPLATE_CONFIDENCE,
                    source_layer=SourceLayer.ML_ANOMALY,
                    note=f"log template mới: \"{tpl.text()[:100]}\" — nghi deploy/config/attack",
                ))

        # Tín hiệu 2 — count spike · Tín hiệu 3 — inter-arrival/silence: template "đều đặn"
        # bỗng câm (W1-D2: sự VẮNG MẶT báo khác low-count — count-based bỏ sót hoàn toàn;
        # service degrade thường im lặng trước khi chết).
        for tpl in miner.close_window():
            hist = tpl.history[:-1]  # cửa sổ vừa chốt là giá trị hiện tại
            current = tpl.history[-1]
            if len(hist) < self._spike_min:
                continue
            z, median = robust_zscore(float(current), [float(h) for h in hist])
            presence = sum(1 for h in hist if h >= 1) / len(hist)
            if z >= self.Z_SPIKE:
                signals.append(AnomalySignal(
                    service=service, sli="log_template_spike", severity=Severity.WARNING,
                    current_value=float(current), baseline_median=median,
                    z_score=round(z, 2),
                    confidence=round(min(0.95, 0.7 + z / 40), 2),
                    source_layer=SourceLayer.ML_ANOMALY,
                    note=f"template \"{tpl.text()[:80]}\" spike {current} vs median {median:.0f} (z={z:.1f})",
                ))
            elif current == 0 and presence >= self.SILENCE_PRESENCE_MIN and median >= 1:
                signals.append(AnomalySignal(
                    service=service, sli="log_template_silence", severity=Severity.WARNING,
                    current_value=0.0, baseline_median=median, z_score=0.0,
                    confidence=self.SILENCE_CONFIDENCE,
                    source_layer=SourceLayer.ML_ANOMALY,
                    note=(f"template \"{tpl.text()[:80]}\" IM LẶNG bất thường "
                          f"(có mặt {presence:.0%} cửa sổ, median {median:.0f} → 0)"),
                ))

        self._window_index[service] = widx + 1
        return signals
