"""Tests cho replay harness — MANDATE #15 (cửa nhận input ngoài, chấm detect đáng tin)."""
from __future__ import annotations

from ai_engine.aiops.replay_harness import render_report, replay


def _scn(name, windows, ground_truth, tick_s=30):
    return {"name": name, "tick_seconds": tick_s, "windows": windows, "ground_truth": ground_truth}


async def test_real_incident_detected_with_mttd():
    scn = _scn("real",
        [{"tick": 1, "anomalies": [{"service": "product-catalog", "z": 8, "confidence": 0.85}]},
         {"tick": 2, "burns": [{"service": "checkout", "burn_rate": 14.4, "severity": "critical"}],
          "anomalies": [{"service": "product-catalog", "z": 9, "confidence": 0.9}]}],
        [{"service": "product-catalog", "starts_tick": 1, "kind": "real"}])
    r = await replay(scn)
    assert r.recall == 1.0
    assert r.mttd_s["product-catalog"] == 30  # bắt ngay tick 1


async def test_busy_healthy_not_fired():
    """Tải cao (z thấp, confidence <0.7) KHÔNG được kêu — gate confidence chặn trước correlator."""
    scn = _scn("busy",
        [{"tick": 1, "anomalies": [{"service": "frontend", "z": 2.5, "confidence": 0.5}]},
         {"tick": 2, "anomalies": [{"service": "frontend", "z": 2.8, "confidence": 0.55}]}],
        [{"service": "frontend", "starts_tick": 1, "kind": "busy-healthy"}])
    r = await replay(scn)
    assert r.busy_ok is True           # không kêu oan
    assert not r.fired                  # không incident nào
    assert r.detection == {}            # busy-healthy không tính vào recall


async def test_masking_mild_incident_still_caught():
    """Spike nhiễu lớn (ad) KHÔNG che sự cố nhẹ thật (kafka lag)."""
    scn = _scn("masking",
        [{"tick": 1, "anomalies": [
            {"service": "ad", "z": 12, "confidence": 0.95, "note": "spike nhiễu"},
            {"service": "kafka", "sli": "consumer_lag", "z": 5, "confidence": 0.8, "note": "lag thật"}]},
         {"tick": 2, "anomalies": [{"service": "kafka", "sli": "consumer_lag", "z": 6, "confidence": 0.85}]}],
        [{"service": "kafka", "starts_tick": 1, "kind": "masking-real"}])
    r = await replay(scn)
    assert r.masking_ok is True         # sự cố nhẹ vẫn bắt được
    assert r.detection["kafka"] is not None


async def test_low_confidence_anomaly_filtered():
    """Anomaly confidence < 0.7 bị chặn (C2 gate) — không tạo incident."""
    scn = _scn("lowconf",
        [{"tick": 1, "anomalies": [{"service": "email", "z": 3, "confidence": 0.6}]}],
        [])
    r = await replay(scn)
    assert not r.fired


async def test_bug2_mttd_not_zero_when_detected_before_starts():
    """BUG#2: anomaly cảnh báo ở tick 1 nhưng sự cố starts_tick=2 → MTTD ≥ 1 tick, KHÔNG =0."""
    scn = _scn("early",
        [{"tick": 1, "anomalies": [{"service": "product-catalog", "z": 8, "confidence": 0.85}]},
         {"tick": 2, "anomalies": [{"service": "product-catalog", "z": 9, "confidence": 0.9}]}],
        [{"service": "product-catalog", "starts_tick": 2, "kind": "real"}])
    r = await replay(scn)
    assert r.mttd_s["product-catalog"] == 30  # 1 tick × 30s, không phải 0


async def test_bug3_masking_noise_not_penalizing_precision():
    """BUG#3: spike nhiễu kind masking-noise KHÔNG tính false-fire → precision không bị phạt oan."""
    scn = _scn("noise",
        [{"tick": 1, "anomalies": [
            {"service": "ad", "z": 12, "confidence": 0.95, "note": "spike nhiễu hợp lệ"},
            {"service": "kafka", "sli": "consumer_lag", "z": 6, "confidence": 0.85}]}],
        [{"service": "kafka", "starts_tick": 1, "kind": "masking-real"},
         {"service": "ad", "kind": "masking-noise"}])
    r = await replay(scn)
    assert r.false_fires == []          # ad không tính false
    assert r.precision == 1.0            # không bị phạt oan
    assert r.masking_ok is True          # kafka vẫn bắt


async def test_report_renders_verdict_and_mttd():
    scn = _scn("real",
        [{"tick": 1, "anomalies": [{"service": "product-catalog", "z": 8, "confidence": 0.85}]}],
        [{"service": "product-catalog", "starts_tick": 1, "kind": "real"}])
    r = await replay(scn)
    report = render_report([r], baseline_mttd_s=900)
    assert "VERDICT" in report
    assert "MTTD" in report
    assert "giảm" in report  # % cải thiện so baseline
