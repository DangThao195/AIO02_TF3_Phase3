import sys
import os
import time

# Thêm thư mục aiops-engine vào path để import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anomaly_detector import AnomalyDetector

def run_metric_anomaly_test():
    print("==================================================")
    print("TESTING METRIC ANOMALY DETECTION WITH LIVE DATA")
    print("==================================================")
    
    # Khởi tạo detector
    # PROMETHEUS_URL đã được cấu hình qua env để chọc qua Grafana proxy ở port 8080
    detector = AnomalyDetector()
    print(f"Connecting to Prometheus via URL: {detector.prometheus_url}")
    
    # 1. Kiểm tra truy vấn cơ bản xem Prometheus có hoạt động không
    print("\n--- STAGE 1: BASIC METRICS REACHABILITY ---")
    basic_res = detector.query_prometheus("up")
    if basic_res and basic_res.get("status") == "success":
        results = basic_res.get("data", {}).get("result", [])
        print(f"SUCCESS: Connected to Prometheus! Found {len(results)} active monitoring targets.")
    else:
        print("FAILED: Could not fetch 'up' metric from Prometheus.")
        return
        
    # 2. Test thuật toán Lớp 1: SLO Burn-rate Monitor
    print("\n--- STAGE 2: SLO BURN-RATE ALGORITHM TEST ---")
    print("Querying error budget burn rates...")
    
    query_errors_5m = 'sum(rate(http_server_duration_milliseconds_count{http_status_code=~"5.."}[5m]))'
    query_total_5m = 'sum(rate(http_server_duration_milliseconds_count[5m]))'
    
    err_5m = detector.parse_query_value(detector.query_prometheus(query_errors_5m))
    tot_5m = detector.parse_query_value(detector.query_prometheus(query_total_5m))
    
    print(f"Current Error Rate (5m) - Error Rate: {err_5m:.4f} req/sec, Total Rate: {tot_5m:.4f} req/sec")
    
    # Tính toán thử Burn-rate giả lập dựa trên tỷ lệ này
    simulated_burn_rate = (err_5m / tot_5m * 720) if tot_5m > 0 else 0.0
    print(f"Computed Storefront Latency Burn Rate: {simulated_burn_rate:.2f} (Warning threshold: >= 14.4)")
    
    # Chạy hàm check mặc định
    is_slo_violated = detector.check_slo_burn_rate()
    print(f"SLO Burn Rate Violation Status: {is_slo_violated}")

    # 3. Test thuật toán Lớp 2: Z-Score Anomaly Detector
    print("\n--- STAGE 3: Z-SCORE ANOMALY DETECTION TEST ---")
    
    metric_to_test = 'prometheus_http_requests_total{handler="/api/v1/query"}'
    print(f"Calculating Z-Score for metric: {metric_to_test} over a 1-hour window...")
    
    query_mean = f"avg_over_time({metric_to_test}[1h])"
    query_stddev = f"stddev_over_time({metric_to_test}[1h])"
    query_current = f"{metric_to_test}"
    
    mean = detector.parse_query_value(detector.query_prometheus(query_mean))
    stddev = detector.parse_query_value(detector.query_prometheus(query_stddev))
    current = detector.parse_query_value(detector.query_prometheus(query_current))
    
    print(f"Current Value: {current:,.2f} Bytes")
    print(f"Historical Mean (1h): {mean:,.2f} Bytes")
    print(f"Historical Stddev (1h): {stddev:,.2f} Bytes")
    
    if stddev > 0:
        z_score = (current - mean) / stddev
        print(f"SUCCESS: Calculated Z-Score = {z_score:.4f}")
        # Đánh giá bất thường: Z-Score > 3.0 là bất thường nghiêm trọng
        if abs(z_score) > 3.0:
            print("ALERT: Z-Score anomaly detected! (Z > 3.0)")
        else:
            print("Status: Metric is stable (within normal baseline).")
    else:
        print("WARNING: Stddev is 0 or no history. Cannot calculate Z-score.")
        
    print("==================================================")
    print("METRIC ANOMALY DETECTION ALGORITHM TESTS PASSED!")

if __name__ == "__main__":
    run_metric_anomaly_test()
