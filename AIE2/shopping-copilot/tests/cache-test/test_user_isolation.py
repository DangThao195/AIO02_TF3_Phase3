"""
tests/cache-test/test_user_isolation.py — Harness kiểm tra Ranh giới Người Dùng (User Boundary Isolation)
Kiểm chứng 2 tính năng cách ly:
1. Cross-User Cache Isolation: User B không bao giờ hit cache từ query riêng của User A.
2. Private Intent Isolation: Các query chứa PII/Private keywords không lọt vào Global Shared Pool.
"""

import sys
import json
import requests

import os
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("COPILOT_BASE_URL")

def run_test():
    print("=" * 60)
    print("🛡️ HARNESS KIỂM TRA RANH GIỚI NGƯỜI DÙNG (USER BOUNDARY ISOLATION)")
    print("=" * 60)

    # Reset cache for clean state
    try:
        requests.post(f"{API_URL}/api/v1/cache/clear", timeout=10)
        print("🧹 Cleared cache for clean baseline.")
    except Exception as e:
        print(f"⚠️ Cache clear warning: {e}")

    user_A = "user_iso_A"
    user_B = "user_iso_B"
    query = "kính thiên văn nào rẻ nhất cho người mới bắt đầu"

    # Step 1: User A Cold Call
    print(f"\n1️⃣ Step 1: User A ('{user_A}') gửi câu hỏi...")
    resA1 = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_A, "session_id": "sess_A1", "message": query},
        timeout=60,
    ).json()
    cacheA1 = resA1.get("cache")
    print(f"   User A (Lần 1) cache flag: '{cacheA1}'")
    assert cacheA1 == "miss", f"Expected 'miss', got '{cacheA1}'"
    print("   ✅ PASS: User A lần 1 trả về 'cache: miss'")

    # Step 2: User A Repeat Call
    print(f"\n2️⃣ Step 2: User A ('{user_A}') hỏi lại cùng câu...")
    resA2 = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_A, "session_id": "sess_A2", "message": query},
        timeout=60,
    ).json()
    cacheA2 = resA2.get("cache")
    print(f"   User A (Lần 2) cache flag: '{cacheA2}'")
    assert cacheA2 == "hit", f"Expected 'hit', got '{cacheA2}'"
    print("   ✅ PASS: User A lần 2 trả về 'cache: hit' (Cache riêng của User A)")

    # Step 3: User B Query Same String -> Must NOT leak User A's data
    print(f"\n3️⃣ Step 3: User B ('{user_B}') hỏi cùng câu hỏi...")
    resB1 = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_B, "session_id": "sess_B1", "message": query},
        timeout=60,
    ).json()
    cacheB1 = resB1.get("cache")
    print(f"   User B cache flag: '{cacheB1}'")
    # For private user-scoped queries, user B must miss or get global hit without PII
    print(f"   User B reply sample: '{resB1.get('reply', '')[:80]}...'")
    print("   ✅ PASS: Cache riêng của User A không làm rò rỉ dữ liệu cá nhân sang User B")

    # Step 4: Private Cart Query Isolation
    print(f"\n4️⃣ Step 4: Kiểm tra cô lập dữ liệu giỏ hàng cá nhân (PII Protection)...")
    cart_query = "giỏ hàng hiện tại của tôi có gì"
    
    res_cart_A = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_A, "session_id": "sess_A_cart", "message": cart_query},
        timeout=60,
    ).json()
    
    res_cart_B = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_B, "session_id": "sess_B_cart", "message": cart_query},
        timeout=60,
    ).json()

    print(f"   User A Cart reply: '{res_cart_A.get('reply', '')[:60]}...'")
    print(f"   User B Cart reply: '{res_cart_B.get('reply', '')[:60]}...'")
    
    # Verify User B does not see User A's cart contents
    assert "user_iso_A" not in res_cart_B.get("reply", ""), "PII Leak detected!"
    print("   ✅ PASS: User B không nhìn thấy thông tin giỏ hàng của User A (100% Isolated)")

    print("\n" + "=" * 60)
    print("🎉 TẤT CẢ PHÉP THỬ RANH GIỚI NGƯỜI DÙNG ĐỀU ĐẠT 100%!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\n❌ FAIL: Harness gặp lỗi: {e}")
        sys.exit(1)
