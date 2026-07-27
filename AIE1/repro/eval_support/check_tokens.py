#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script kiểm thử độc lập đo đạc số lượng Token tiêu thụ (Cost Estimation)
Dành cho TICKET 1 - Đo đạc chi phí RAG đầu-cuối của product-reviews
"""

import os
import sys
from openai import OpenAI

def check_token_usage():
    # Lấy thông tin cấu hình từ biến môi trường
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")

    if not api_key or not base_url or not model:
        print("[!] Lỗi: Thiếu biến môi trường. Vui lòng chạy lệnh export trước.")
        print("Ví dụ:")
        print("  export LLM_BASE_URL=\"https://api.groq.com/openai/v1\"")
        print("  export LLM_MODEL=\"llama-3.3-70b-versatile\"")
        print("  export OPENAI_API_KEY=\"gsk_...\"")
        sys.exit(1)

    print("=" * 60)
    print(f"[*] Đang thực hiện cuộc gọi mô phỏng RAG 2-turn tới:")
    print(f"    - Base URL: {base_url}")
    print(f"    - Model:    {model}")
    print("=" * 60)

    client = OpenAI(base_url=base_url, api_key=api_key)

    # ----------------------------------------------------
    # TURN 1: Gửi Prompt ban đầu và nhận yêu cầu gọi Tool
    # ----------------------------------------------------
    system_prompt = (
        "You are a helpful assistant that answers related to a specific product. "
        "Use tools as needed to fetch the product reviews and product information. "
        "Keep the response brief with no more than 1-2 sentences. "
        "If you don't know the answer, just say you don't know."
    )
    user_prompt = "Answer the following question about product ID:L9ECAV7KIM: Can you summarize the product reviews?"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_product_reviews",
                "description": "Executes a SQL query to retrieve reviews for a particular product.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "The product ID to fetch product reviews for.",
                        }
                    },
                    "required": ["product_id"],
                },
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_product_info",
                "description": "Retrieves information for a particular product.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "The product ID to fetch information for.",
                        }
                    },
                    "required": ["product_id"],
                },
            }
        }
    ]

    print("[*] Turn 1: Đang gửi prompt ban đầu để lấy tool calls...")
    try:
        response_1 = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
    except Exception as e:
        print(f"[!] Lỗi Turn 1: {e}")
        sys.exit(1)

    usage_1 = response_1.usage
    print(f"    -> Token sử dụng ở Turn 1:")
    print(f"       + Input (Prompt):      {usage_1.prompt_tokens} tokens")
    print(f"       + Output (Completion): {usage_1.completion_tokens} tokens")
    print(f"       + Total:               {usage_1.total_tokens} tokens")

    # Kiểm tra xem mô hình có gọi tool hay không
    choice = response_1.choices[0]
    if not choice.message.tool_calls:
        print("[!] Cảnh báo: Mô hình không yêu cầu gọi tool. Kết thúc sớm.")
        return

    print("[*] Phát hiện yêu cầu gọi tool thành công!")

    # ----------------------------------------------------
    # TURN 2: Mô phỏng nạp kết quả trả về của Tool vào hội thoại
    # ----------------------------------------------------
    
    # 1. Thêm tin nhắn phản hồi của Assistant chứa tool calls
    messages.append(choice.message)

    # 2. Mock kết quả của fetch_product_reviews (5 review gốc của L9ECAV7KIM trong DB)
    mock_reviews = (
        "[{\"username\": \"clean_optics\", \"description\": \"This kit is a lifesaver for all my optics. The brush and wipes work perfectly without leaving any residue. My lenses have never been cleaner.\", \"score\": 5.0},"
        "{\"username\": \"photog_pro\", \"description\": \"Essential for any photographer or telescope owner. It safely removes dust and fingerprints. A high-quality cleaning solution.\", \"score\": 4.5},"
        "{\"username\": \"daily_cleaner\", \"description\": \"I use this on my binoculars, camera lenses, and even my phone screen. It is very effective and gentle. A versatile cleaning kit.\", \"score\": 4.0},"
        "{\"username\": \"tech_maintenance\", \"description\": \"Great value for money. The different cleaning options cover all needs. Keeps my expensive equipment in pristine condition.\", \"score\": 5.0},"
        "{\"username\": \"sharp_view\", \"description\": \"Works as advertised, my telescope views are much clearer after using this. The fluid and cloth are excellent. Definitely recommend.\", \"score\": 4.5}]"
    )

    # 3. Mock kết quả của fetch_product_info
    mock_info = (
        "{\"id\": \"L9ECAV7KIM\", \"name\": \"Lens Cleaning Kit\", \"price_usd\": 19.99, "
        "\"description\": \"Professional cleaning kit for telescopes, camera lenses, and binoculars. "
        "Includes cleaning fluid, micro-fiber cloth, brush, and air blower.\"}"
    )

    # Đưa các phản hồi của tool vào hội thoại
    for tool_call in choice.message.tool_calls:
        content = ""
        if tool_call.function.name == "fetch_product_reviews":
            content = mock_reviews
        elif tool_call.function.name == "fetch_product_info":
            content = mock_info
        
        messages.append({
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": tool_call.function.name,
            "content": content
        })

    # Thêm câu lệnh dẫn hướng cuối cùng của User
    messages.append({
        "role": "user",
        "content": "Based on the tool results, answer the original question about product ID:L9ECAV7KIM. Keep the response brief with no more than 1-2 sentences."
    })

    print("[*] Turn 2: Đang gửi kết quả của tools để tóm tắt và sinh câu trả lời cuối...")
    try:
        response_2 = client.chat.completions.create(
            model=model,
            messages=messages
        )
    except Exception as e:
        print(f"[!] Lỗi Turn 2: {e}")
        sys.exit(1)

    usage_2 = response_2.usage
    print(f"    -> Token sử dụng ở Turn 2:")
    print(f"       + Input (Prompt):      {usage_2.prompt_tokens} tokens")
    print(f"       + Output (Completion): {usage_2.completion_tokens} tokens")
    print(f"       + Total:               {usage_2.total_tokens} tokens")

    # ----------------------------------------------------
    # TỔNG HỢP VÀ ƯỚC TÍNH CHI PHÍ (gpt-4o-mini rates)
    # ----------------------------------------------------
    total_prompt = usage_1.prompt_tokens + usage_2.prompt_tokens
    total_completion = usage_1.completion_tokens + usage_2.completion_tokens
    
    # Giá gpt-4o-mini: Input: $0.15/1M, Output: $0.60/1M
    cost_input = (total_prompt / 1000000) * 0.15
    cost_output = (total_completion / 1000000) * 0.60
    cost_per_req = cost_input + cost_output
    cost_10k = cost_per_req * 10000

    print("=" * 60)
    print("TỔNG HỢP ĐO ĐẠC TOKEN & CHI PHÍ:")
    print("=" * 60)
    print(f"-> Tổng Input (Prompt) Tokens:      {total_prompt} tokens")
    print(f"-> Tổng Output (Completion) Tokens:  {total_completion} tokens")
    print(f"-> Tổng Token tiêu thụ/request:      {total_prompt + total_completion} tokens")
    print("-" * 60)
    print(f"-> Ước tính chi phí (áp dụng giá gpt-4o-mini):")
    print(f"   + Cho 1 request:    ${cost_per_req:.6f} USD")
    print(f"   + Cho 10,000 reqs:  ${cost_10k:.4f} USD")
    print("=" * 60)
    print("[Gợi ý] Sử dụng các con số trên để điền vào Mục 2 của AI_BASELINE_EVAL.md!")
    print("=" * 60)

if __name__ == "__main__":
    check_token_usage()
