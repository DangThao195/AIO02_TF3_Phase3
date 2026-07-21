#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Mock LLM & Product Reviews gRPC Benchmark Script
Dành cho TICKET 1 (Khoa) - Nhóm AIE1

Script này sử dụng thư viện chuẩn của Python và grpcio để thực hiện gọi gRPC đồng loạt
nhằm đo đạc chính xác các thông số Latency (Average, p95, p99) và tỷ lệ lỗi.
"""

import time
import os
import sys
import grpc

# Thêm đường dẫn tới thư mục chứa demo_pb2 và demo_pb2_grpc
sys.path.append(os.path.join(os.path.dirname(__file__), "../techx-corp-platform/src/product-reviews"))
try:
    import demo_pb2
    import demo_pb2_grpc
except ImportError:
    print("[!] Lỗi: Không tìm thấy file demo_pb2.py. Vui lòng chạy lệnh sau tại thư mục gốc trước:")
    print("    make docker-generate-protobuf")
    sys.exit(1)

# Địa chỉ cổng gRPC của product-reviews (mặc định map trong docker-compose là 3551)
PRODUCT_REVIEWS_ADDR = os.environ.get("PRODUCT_REVIEWS_ADDR", "localhost:3551")

def calculate_percentile(sorted_list, percentile):
    """Tính phân vị không cần sử dụng numpy"""
    if not sorted_list:
        return 0.0
    index = (len(sorted_list) - 1) * percentile
    lower = int(index)
    upper = lower + 1
    weight = index - lower
    if upper < len(sorted_list):
        return sorted_list[lower] * (1 - weight) + sorted_list[upper] * weight
    return sorted_list[lower]

def run_benchmark(num_requests=50):
    print("=" * 60)
    print(f"[*] Bắt đầu đo đạc (Benchmark) {num_requests} requests tới {PRODUCT_REVIEWS_ADDR}...")
    print("=" * 60)
    
    # Thiết lập kênh gRPC
    try:
        channel = grpc.insecure_channel(PRODUCT_REVIEWS_ADDR)
        stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
    except Exception as e:
        print(f"[!] Lỗi kết nối gRPC channel: {e}")
        return

    latencies = []
    error_count = 0

    for i in range(num_requests):
        start_time = time.perf_counter()
        try:
            # Gửi yêu cầu RAG tóm tắt đánh giá sản phẩm test
            request = demo_pb2.AskProductAIAssistantRequest(
                product_id="L9ECAV7KIM",
                question="Can you summarize the product reviews?"
            )
            response = stub.AskProductAIAssistant(request, timeout=10.0)
            duration = (time.perf_counter() - start_time) * 1000 # Chuyển sang mili-giây (ms)
            
            # Kiểm tra xem phản hồi có hợp lệ không hay trả về chuỗi rỗng
            if not response.response:
                error_count += 1
            else:
                latencies.append(duration)
                
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            error_count += 1
            # Thêm độ trễ của cuộc gọi lỗi vào danh sách để phản ánh đúng thực tế
            latencies.append(duration)
            print(f"[!] Request {i+1}/{num_requests} thất bại: {e}")
            
        # Nghỉ 1.5 giây giữa các request để tránh làm overload OpenAI Rate Limit (RPM)
        time.sleep(5)

    if not latencies:
        print("[!] Không có cuộc gọi nào thành công hoặc ghi nhận được dữ liệu.")
        return

    # Sắp xếp để tính phần trăm độ trễ
    sorted_latencies = sorted(latencies)
    avg_latency = sum(latencies) / len(latencies)
    p95_latency = calculate_percentile(sorted_latencies, 0.95)
    p99_latency = calculate_percentile(sorted_latencies, 0.99)
    error_rate = (error_count / num_requests) * 100

    print("\n" + "=" * 60)
    print("KẾT QUẢ ĐO ĐẠC BASELINE:")
    print("=" * 60)
    print(f"-> Tổng số request gửi đi:     {num_requests}")
    print(f"-> Độ trễ trung bình (Average): {avg_latency:.2f} ms")
    print(f"-> Độ trễ phân vị p95:         {p95_latency:.2f} ms")
    print(f"-> Độ trễ phân vị p99:         {p99_latency:.2f} ms")
    print(f"-> Tỉ lệ cuộc gọi lỗi (%):      {error_rate:.2f} %")
    print("=" * 60)
    print("[Gợi ý] Hãy sao chép các con số trên để điền vào AI_BASELINE_EVAL.md!")
    print("=" * 60)

if __name__ == "__main__":
    # Nhận số lượng request từ đối số dòng lệnh nếu có (mặc định là 50)
    requests = 50
    if len(sys.argv) > 1:
        try:
            requests = int(sys.argv[1])
        except ValueError:
            pass
            
    run_benchmark(requests)
