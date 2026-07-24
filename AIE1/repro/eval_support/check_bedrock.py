#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script kiểm thử độc lập kết nối tới Amazon Bedrock
Sử dụng thư viện boto3 và Bedrock Converse API để kiểm tra tính hợp lệ của tài khoản.
"""

import sys
import boto3
from botocore.exceptions import ClientError

def test_bedrock_connection(model_id="amazon.nova-lite-v1:0"):
    print("=" * 60)
    print(f"[*] Đang khởi tạo kết nối tới Amazon Bedrock...")
    print(f"    - Region: us-east-1")
    print(f"    - Model:  {model_id}")
    print("=" * 60)

    try:
        # Khởi tạo client bedrock-runtime sử dụng credentials đã cấu hình trong AWS CLI
        client = boto3.client('bedrock-runtime', region_name='us-east-1')
        
        prompt = "Explain in one brief sentence why using RAG is useful for LLMs."
        
        print(f"[*] Đang gửi Prompt tới Bedrock: '{prompt}'...")
        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    'role': 'user',
                    'content': [{'text': prompt}]
                }
            ]
        )
        
        # Trích xuất phản hồi
        output_text = response['output']['message']['content'][0]['text']
        
        print("\n" + "=" * 60)
        print("PHẢN HỒI THÀNH CÔNG TỪ AMAZON BEDROCK:")
        print("=" * 60)
        print(output_text)
        print("=" * 60 + "\n")
        
    except ClientError as e:
        print(f"[!] Lỗi AWS Bedrock Client: {e}")
        print("[Gợi ý] Hãy chắc chắn tài khoản của bạn đã được AWS cấp quyền truy cập (Model Access) cho model này.")
    except Exception as e:
        print(f"[!] Lỗi không xác định: {e}")

if __name__ == "__main__":
    # Cho phép truyền Model ID làm đối số dòng lệnh, mặc định là Nova Lite
    target_model = sys.argv[1] if len(sys.argv) > 1 else "amazon.nova-lite-v1:0"
    test_bedrock_connection(target_model)
