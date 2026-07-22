#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script kiểm thử độc lập đo đạc số lượng Token và Chi phí (Cost Estimation) trên AWS Bedrock
Dành cho nhóm AIE1 - Đo đạc chi phí RAG đầu-cuối của product-reviews sử dụng Nova Lite/Micro.
"""

import os
import sys
import time

try:
    import boto3
except ImportError:
    print("[!] Lỗi: Thiếu thư viện boto3. Vui lòng cài đặt: pip install boto3")
    sys.exit(1)

def check_bedrock_token_usage(model_id="amazon.nova-lite-v1:0"):
    # Cấu hình AWS Credentials từ biến môi trường
    aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")

    if not aws_access_key or not aws_secret_key:
        print("[!] Lỗi: Thiếu AWS Credentials. Vui lòng chạy lệnh export AWS keys trước.")
        sys.exit(1)

    print("=" * 60)
    print(f"[*] Bắt đầu gửi RAG request tới AWS Bedrock:")
    print(f"    - Model ID: {model_id}")
    print(f"    - Region:   {aws_region}")
    print("=" * 60)

    # Khởi tạo Bedrock client
    try:
        client = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )
    except Exception as e:
        print(f"[!] Lỗi khởi tạo Bedrock client: {e}")
        sys.exit(1)

    # 1. Chuẩn bị system prompt và user prompt RAG giả lập
    system_prompt = (
        "You are a product review assistant for TechX Corp. "
        "Your ONLY job is to answer questions about a specific product based on its reviews and product info. "
        "Use tools as needed to fetch product reviews and product information. "
        "Keep responses brief (1-2 sentences). "
        "STRICT RULES — you MUST follow these without exception:\n"
        "1. If the question is NOT about this product (e.g. math, general knowledge, coding, weather, anything unrelated to the product): respond with exactly 'OUT_OF_SCOPE'.\n"
        "2. If the question IS about the product but the reviews/info do not contain the answer: respond with exactly 'NO_INFO'.\n"
        "3. Never make up or infer information not present in the provided reviews or product data."
    )

    question = "Can you summarize the product reviews?"
    
    # Giả lập reviews & catalog info của sản phẩm L9ECAV7KIM
    mock_reviews = (
        "[[\"clean_optics\", \"This kit is a lifesaver for all my optics. The brush and wipes work perfectly without leaving any residue. My lenses have never been cleaner.\", 5.0],"
        "[\"photog_pro\", \"Essential for any photographer or telescope owner. It safely removes dust and fingerprints. A high-quality cleaning solution.\", 4.5],"
        "[\"daily_cleaner\", \"I use this on my binoculars, camera lenses, and even my phone screen. It's very effective and gentle. A versatile cleaning kit.\", 4.0],"
        "[\"tech_maintenance\", \"Great value for money. The different cleaning options cover all needs. Keeps my expensive equipment in pristine condition.\", 5.0],"
        "[\"sharp_view\", \"Works as advertised, my telescope views are much clearer after using this. The fluid and cloth are excellent. Definitely recommend.\", 4.5]]"
    )
    
    mock_info = (
        "{\"id\": \"L9ECAV7KIM\", \"name\": \"Lens Cleaning Kit\", \"price_usd\": 19.99, "
        "\"description\": \"Professional cleaning kit for telescopes, camera lenses, and binoculars. "
        "Includes cleaning fluid, micro-fiber cloth, brush, and air blower.\"}"
    )

    user_prompt = (
        f"Question: {question}\n\n"
        f"Product info JSON:\n{mock_info}\n\n"
        f"Filtered product reviews JSON:\n{mock_reviews}\n\n"
        "Answer only from the provided product info and reviews. "
        "If the answer is not present in the provided data, respond with exactly 'NO_INFO'. "
        "If the question is unrelated to the product, respond with exactly 'OUT_OF_SCOPE'. "
        "Keep the response brief with no more than 1-2 sentences."
    )

    # 2. Gọi AWS Bedrock converse API và tính thời gian
    start_time = time.perf_counter()
    try:
        response = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}]
                }
            ],
            inferenceConfig={"temperature": 0.0, "maxTokens": 500}
        )
    except Exception as e:
        print(f"[!] Lỗi gọi Bedrock Converse: {e}")
        sys.exit(1)
    
    duration = (time.perf_counter() - start_time) * 1000  # ms

    # 3. Trích xuất thông tin sử dụng token và latency từ Bedrock
    usage = response.get("usage", {})
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)
    total_tokens = usage.get("totalTokens", 0)
    
    output_text = response['output']['message']['content'][0]['text']

    # 4. Tính toán chi phí thực tế của các dòng mô hình Nova
    # Nova Lite: Input $0.06/1M, Output $0.24/1M
    # Nova Micro: Input $0.035/1M, Output $0.14/1M
    is_micro = "micro" in model_id.lower()
    input_rate = 0.035 if is_micro else 0.06
    output_rate = 0.14 if is_micro else 0.24
    
    cost_input = (input_tokens / 1000000) * input_rate
    cost_output = (output_tokens / 1000000) * output_rate
    cost_per_req = cost_input + cost_output
    cost_10k = cost_per_req * 10000

    print("\n" + "=" * 60)
    print("PHẢN HỒI TỪ BEDROCK:")
    print("=" * 60)
    print(f"Response: '{output_text}'")
    print(f"Latency:  {duration:.2f} ms")
    print("-" * 60)
    print("CHI PHÍ & TOKEN TIÊU THỤ (AWS BEDROCK BILLING):")
    print("=" * 60)
    print(f"-> Input (Prompt) Tokens:      {input_tokens} tokens")
    print(f"-> Output (Completion) Tokens:  {output_tokens} tokens")
    print(f"-> Total Tokens:                {total_tokens} tokens")
    print("-" * 60)
    print(f"-> Đơn giá áp dụng ({'Nova Micro' if is_micro else 'Nova Lite'}):")
    print(f"   + Input Rate:   ${input_rate}/1M tokens")
    print(f"   + Output Rate:  ${output_rate}/1M tokens")
    print(f"   + Chi phí/1 req:   ${cost_per_req:.6f} USD")
    print(f"   + Chi phí/10k reqs: ${cost_10k:.4f} USD")
    print("=" * 60)

if __name__ == "__main__":
    target_model = sys.argv[1] if len(sys.argv) > 1 else "amazon.nova-lite-v1:0"
    check_bedrock_token_usage(target_model)
