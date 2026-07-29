"""
tests/cache-test/test_api_cache_metadata.py — Harness kiểm tra Metadata Response Flag & Invalidation
Kiểm chứng 3 tính năng:
1. First Call: cache == "miss"
2. Repeat Call: cache == "hit"
3. Invalidation API: POST /api/v1/cache/invalidate -> next call: cache == "miss"
"""

import sys
import json
import requests

API_URL = "http://localhost:8001"

def run_test():
    print("=" * 60)
    print("🧪 HARNESS KIỂM TRA API CACHE METADATA & INVALIDATION")
    print("=" * 60)

    # Reset cache for clean state
    try:
        requests.post(f"{API_URL}/api/v1/cache/clear", timeout=10)
        print("🧹 Cleared cache for clean baseline.")
    except Exception as e:
        print(f"⚠️ Cache clear warning: {e}")

    session_id = "test_meta_sess_001"
    user_id = "user_meta_tester"
    product_id = "OLJCESPC7Z"
    message = f"tìm product {product_id}"

    # Step 1: Cold Call
    print(f"\n1️⃣ Step 1: Lần gọi đầu tiên (Cold Call)...")
    res1 = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_id, "session_id": session_id, "message": message},
        timeout=60,
    ).json()
    cache1 = res1.get("cache")
    print(f"   Response cache flag: '{cache1}'")
    assert cache1 == "miss", f"Expected 'miss', got '{cache1}'"
    print("   ✅ PASS: Lần gọi đầu tiên trả về 'cache: miss'")

    # Step 2: Repeat Call (Hot Call)
    print(f"\n2️⃣ Step 2: Lần gọi lặp lại (Hot Call)...")
    res2 = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_id, "session_id": session_id, "message": message},
        timeout=60,
    ).json()
    cache2 = res2.get("cache")
    print(f"   Response cache flag: '{cache2}'")
    assert cache2 == "hit", f"Expected 'hit', got '{cache2}'"
    print("   ✅ PASS: Lần gọi thứ hai trả về 'cache: hit'")

    # Step 3: Invalidate Source Record
    print(f"\n3️⃣ Step 3: Gọi API Invalidation cho product {product_id}...")
    inv_res = requests.post(
        f"{API_URL}/api/v1/cache/invalidate",
        json={"entity_type": "product", "entity_id": product_id},
        timeout=10,
    ).json()
    print(f"   Invalidate response: {inv_res}")
    assert inv_res.get("status") == "ok", "Invalidation API failed"
    print("   ✅ PASS: API Invalidation hoạt động thành công")

    # Step 4: Call After Invalidation
    print(f"\n4️⃣ Step 4: Lần gọi lại sau Invalidation...")
    res3 = requests.post(
        f"{API_URL}/api/chat",
        json={"user_id": user_id, "session_id": "test_meta_sess_002", "message": message},
        timeout=60,
    ).json()
    cache3 = res3.get("cache")
    print(f"   Response cache flag: '{cache3}'")
    assert cache3 == "miss", f"Expected 'miss' after invalidation, got '{cache3}'"
    print("   ✅ PASS: Sau khi invalidate nguồn, request tự động 'cache: miss'")

    print("\n" + "=" * 60)
    print("🎉 TẤT CẢ PHÉP THỬ METADATA & INVALIDATION ĐỀU ĐẠT 100%!")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\n❌ FAIL: Harness gặp lỗi: {e}")
        sys.exit(1)
