import unittest
import os
import sys
import asyncio

# Ensure aiops-engine is in sys.path
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

from anomaly_detector import AnomalyDetector
from main import simulate_long_running, LongRunningPayload, LongRunningScenarioItem, detector


class TestLongRunningIncidentDirective28(unittest.TestCase):
    def setUp(self):
        self.detector = AnomalyDetector()

    def test_real_baseline_freezing_mechanism(self):
        """
        [DIRECTIVE #28 - Test 1]
        Kiểm tra cơ chế đóng băng Baseline thực sự (Explicit Baseline Freezing).
        Khi service 'payment' có sự cố kéo dài, baseline model của payment bị đóng băng thực sự.
        """
        self.assertFalse(self.detector.is_baseline_frozen("payment"))
        
        # Đóng băng baseline cho payment
        self.detector.freeze_baseline("payment")
        self.assertTrue(self.detector.is_baseline_frozen("payment"), "Baseline for payment MUST be frozen during active incident")

        # Giải phóng đóng băng sau sự cố
        self.detector.unfreeze_baseline("payment")
        self.assertFalse(self.detector.is_baseline_frozen("payment"))

    def test_streaming_alert_timeline_output(self):
        """
        [DIRECTIVE #28 - Test 2]
        Kiểm tra Replay Gateway POST /simulate/long_running xuất đúng Dòng Cảnh Báo Theo Thời Gian (Streaming Alert Timeline).
        """
        # Giả lập kịch bản payment bị lỗi liên tục kéo dài 20 phút (T+0m -> T+20m)
        payment_data = [
            {"service": "payment", "timestamp": "2026-07-28T20:00:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.05, "error_rate": 0.00, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 0},
            {"service": "payment", "timestamp": "2026-07-28T20:05:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.45, "error_rate": 0.12, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
            {"service": "payment", "timestamp": "2026-07-28T20:10:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.50, "error_rate": 0.15, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
            {"service": "payment", "timestamp": "2026-07-28T20:15:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.48, "error_rate": 0.14, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
            {"service": "payment", "timestamp": "2026-07-28T20:20:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.05, "error_rate": 0.00, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 0}
        ]

        # Giả lập kịch bản shipping bị lỗi nổ chồng ở T+10m
        shipping_data = [
            {"service": "shipping", "timestamp": "2026-07-28T20:00:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.04, "error_rate": 0.00, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 0},
            {"service": "shipping", "timestamp": "2026-07-28T20:05:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.04, "error_rate": 0.00, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 0},
            {"service": "shipping", "timestamp": "2026-07-28T20:10:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.60, "error_rate": 0.20, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
            {"service": "shipping", "timestamp": "2026-07-28T20:15:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.55, "error_rate": 0.18, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 1},
            {"service": "shipping", "timestamp": "2026-07-28T20:20:00Z", "rps": 150.0, "cpu_usage": 0.15, "memory_usage": 50.0, "latency_p90": 0.04, "error_rate": 0.00, "client_error_rate": 0.0, "kafka_lag": 0.0, "label": 0}
        ]

        payload = LongRunningPayload(scenarios=[
            LongRunningScenarioItem(service="payment", data=payment_data),
            LongRunningScenarioItem(service="shipping", data=shipping_data)
        ])

        res = asyncio.run(simulate_long_running(payload))

        self.assertEqual(res["status"], "evaluated")
        self.assertTrue(res["continuous_detection_verified"])
        self.assertIn("alert_timeline", res)

        timeline = res["alert_timeline"]
        self.assertGreater(len(timeline), 0, "Alert timeline MUST contain streaming event records")

        # Kiểm tra sự kiện mở sự cố (INCIDENT_OPENED) cho payment và shipping
        events = [e["alert_event"] for e in timeline]
        self.assertIn("INCIDENT_OPENED", events)
        self.assertIn("INCIDENT_STILL_ACTIVE", events)
        self.assertIn("INCIDENT_RESOLVED", events)

        # Kiểm tra baseline_frozen = True thực sự cho payment và shipping
        incidents = res["active_isolated_incidents"]
        self.assertTrue(any(inc["service"] == "payment" and inc["baseline_frozen"] for inc in incidents))
        self.assertTrue(any(inc["service"] == "shipping" and inc["baseline_frozen"] for inc in incidents))


if __name__ == "__main__":
    unittest.main()
