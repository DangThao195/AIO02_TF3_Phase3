#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script kiểm thử lấy nhanh phản hồi tóm tắt AI từ product-reviews gRPC server
Dành cho mục đích chứng minh tính năng cắm LLM thật không cần sửa code.
"""

import sys
import os
import grpc

# Thêm đường dẫn tới thư mục chứa demo_pb2 và demo_pb2_grpc
sys.path.append(os.path.join(os.path.dirname(__file__), "../techx-corp-platform/src/product-reviews"))
try:
    import demo_pb2
    import demo_pb2_grpc
except ImportError:
    print("[!] Không thể import code gRPC generated. Hãy kiểm tra thư mục product-reviews.")
    sys.exit(1)

PRODUCT_REVIEWS_ADDR = "localhost:3551"

def get_ai_summary():
    print(f"[*] Đang gửi yêu cầu gRPC tới {PRODUCT_REVIEWS_ADDR}...")
    try:
        channel = grpc.insecure_channel(PRODUCT_REVIEWS_ADDR)
        stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
        
        request = demo_pb2.AskProductAIAssistantRequest(
            product_id="L9ECAV7KIM",
            question="Can you summarize the product reviews?"
        )
        
        response = stub.AskProductAIAssistant(request, timeout=15.0)
        
        print("\n" + "=" * 60)
        print("PHẢN HỒI TỪ AI ASSISTANT:")
        print("=" * 60)
        print(response.response)
        print("=" * 60 + "\n")
        
    except grpc.RpcError as e:
        print(f"[!] Lỗi gRPC: {e.code()} - {e.details()}")
    except Exception as e:
        print(f"[!] Lỗi hệ thống: {e}")

if __name__ == "__main__":
    get_ai_summary()
