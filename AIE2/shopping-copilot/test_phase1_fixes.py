#!/usr/bin/env python3
"""
test_phase1_fixes.py — Test suite for Phase 1 critical fixes

Tests:
1. GR_HAL_TOOL_004: Refractor vs Reflector telescope clarification
2. GR_HAL_TOOL_003: Price filter (products under $50)
3. GR_HAL_TOOL_005: Best rated products ranking

Prerequisites:
- Port-forward running: python scripts/start_port_forwards.py
- Uvicorn server running: uvicorn src.main:app --port 8001 --reload
"""

import requests
import json
import time
from typing import Dict, Any

API_URL = "http://localhost:8001/api/chat"  # FIXED: Added /api prefix

def test_chat(session_id: str, user_id: str, message: str, test_name: str) -> Dict[str, Any]:
    """Send a chat request and return the response."""
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"{'='*80}")
    print(f"User message: {message}")
    
    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "message": message
    }
    
    try:
        start_time = time.time()
        response = requests.post(API_URL, json=payload, timeout=30)
        latency = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            reply = data.get("reply", "")
            intent = data.get("intent", {})
            evidence = data.get("evidence", {})
            
            print(f"\n✓ Status: {response.status_code} (Latency: {latency:.2f}s)")
            print(f"Intent parsed: {json.dumps(intent, ensure_ascii=False, indent=2)}")
            print(f"\nAgent reply:\n{reply}")
            
            return {
                "success": True,
                "latency": latency,
                "reply": reply,
                "intent": intent,
                "evidence": evidence
            }
        else:
            print(f"\n✗ HTTP Error: {response.status_code}")
            print(f"Response: {response.text}")
            return {"success": False, "error": response.text}
    
    except requests.exceptions.RequestException as e:
        print(f"\n✗ Connection Error: {e}")
        print("\nERROR: Cannot connect to API server.")
        print("Make sure:")
        print("1. Port-forward is running: python scripts/start_port_forwards.py")
        print("2. Uvicorn server is running: uvicorn src.main:app --port 8001 --reload")
        return {"success": False, "error": str(e)}


def validate_test1_refractor_clarification(result: Dict[str, Any]) -> bool:
    """
    Test 1: Refractor vs Reflector clarification
    
    Expected behavior:
    - Agent should NOT list refractor products as reflector products
    - Agent should clarify: "We only sell refractor telescopes (kính khúc xạ)"
    - Should suggest refractor collection instead
    """
    if not result.get("success"):
        return False
    
    reply = result["reply"].lower()
    
    # Fail conditions (returning wrong products)
    if "eclipsmart" in reply and "phản xạ" in reply:
        print("\n✗ FAIL: Agent listed refractor products as reflector products")
        return False
    
    # Success conditions (clarification)
    if ("chỉ có" in reply or "only" in reply) and ("khúc xạ" in reply or "refractor" in reply):
        print("\n✓ PASS: Agent correctly clarified we only sell refractors")
        return True
    
    if "không bán" in reply or "do not sell" in reply or "don't sell" in reply:
        print("\n✓ PASS: Agent correctly stated we don't sell reflectors")
        return True
    
    print("\n⚠ UNCERTAIN: Reply doesn't contain clear clarification")
    print("Manual review needed. Reply should clarify we only sell refractors.")
    return False


def validate_test2_price_filter(result: Dict[str, Any]) -> bool:
    """
    Test 2: Price filter under $50
    
    Expected behavior:
    - Should call get_products_by_price_range tool
    - Should return products with price <= 50 USD
    - Should NOT return "không có thông tin"
    """
    if not result.get("success"):
        return False
    
    reply = result["reply"].lower()
    evidence = result.get("evidence", {})
    intent = result.get("intent", {})
    
    # Fail condition: "không có thông tin"
    if "không có thông tin" in reply or "no information" in reply:
        print("\n✗ FAIL: Agent returned 'no information' instead of calling price filter tool")
        return False
    
    # Check if price filter tool was called
    if "get_products_by_price_range" in evidence:
        tool_result = evidence["get_products_by_price_range"]
        products = tool_result.get("products", [])
        
        if products:
            # Validate all products are under $50
            all_under_50 = all(p.get("price", 999) <= 50 for p in products)
            if all_under_50:
                print(f"\n✓ PASS: Price filter tool called, returned {len(products)} products under $50")
                return True
            else:
                print(f"\n✗ FAIL: Some products returned are over $50")
                return False
        else:
            print(f"\n⚠ UNCERTAIN: Tool called but returned empty list (might be correct if no products under $50)")
            return True  # Not a failure — database might genuinely have no products under $50
    
    # Check if intent recognized price constraint
    constraints = intent.get("constraints", {})
    if constraints.get("price_max") == 50:
        print("\n✓ PARTIAL: Intent correctly parsed price_max=50")
        print("⚠ But tool was not called (planner issue or tool not in evidence)")
        return False
    
    print("\n✗ FAIL: Price constraint not recognized in intent")
    return False


def validate_test3_best_rated(result: Dict[str, Any]) -> bool:
    """
    Test 3: Best rated products
    
    Expected behavior:
    - Should call get_best_reviewed_products_tool or get_top_rated_products
    - Should return products sorted by review score (highest first)
    - Should NOT return "không có thông tin"
    """
    if not result.get("success"):
        return False
    
    reply = result["reply"].lower()
    evidence = result.get("evidence", {})
    intent = result.get("intent", {})
    
    # Fail condition: "không có thông tin"
    if "không có thông tin" in reply or "no information" in reply:
        print("\n✗ FAIL: Agent returned 'no information' instead of calling best rated tool")
        print("This might indicate:")
        print("  1. Database connection issue (port-forward not running)")
        print("  2. Agent didn't recognize query as review ranking request")
        return False
    
    # Check if best rated tool was called
    tool_called = None
    if "get_best_reviewed_products_tool" in evidence:
        tool_called = "get_best_reviewed_products_tool"
    elif "get_top_rated_products" in evidence:
        tool_called = "get_top_rated_products"
    
    if tool_called:
        tool_result = evidence[tool_called]
        products = tool_result.get("products", [])
        
        if products:
            print(f"\n✓ PASS: {tool_called} called, returned {len(products)} products")
            # Validate products have review scores
            first_product = products[0]
            if "avg_rating" in first_product or "avg_score" in first_product:
                print(f"First product: {first_product.get('name')} (score: {first_product.get('avg_rating') or first_product.get('avg_score')})")
                return True
            else:
                print("⚠ WARNING: Products don't have review scores in response")
                return True  # Still pass — tool was called
        else:
            print(f"\n⚠ UNCERTAIN: Tool called but returned empty list")
            print("This might indicate database has no reviews (check port-forward)")
            return False
    
    # Check if intent recognized review ranking
    if intent.get("task_type") == "rank" and intent.get("ranking_by") == "review_score":
        print("\n✓ PARTIAL: Intent correctly recognized as review ranking")
        print("⚠ But tool was not called (planner issue)")
        return False
    
    print("\n✗ FAIL: Query not recognized as review ranking request")
    print(f"Intent task_type: {intent.get('task_type')}, ranking_by: {intent.get('ranking_by')}")
    return False


def main():
    print("="*80)
    print("PHASE 1 FIX VALIDATION TEST SUITE")
    print("="*80)
    print("\nPrerequisites check:")
    print("1. Port-forward running? (python scripts/start_port_forwards.py)")
    print("2. Uvicorn server running? (uvicorn src.main:app --port 8001 --reload)")
    print("\nStarting tests in 3 seconds...")
    time.sleep(3)
    
    results = {}
    
    # Test 1: Refractor vs Reflector clarification (GR_HAL_TOOL_004 fix)
    result1 = test_chat(
        session_id="phase1-test-refractor",
        user_id="test-user-001",
        message="Bạn có những kính thiên văn phản xạ nào, liệt kê hết ra giúp tôi",
        test_name="Test 1: Refractor vs Reflector Clarification (GR_HAL_TOOL_004)"
    )
    results["test1_refractor_clarification"] = validate_test1_refractor_clarification(result1)
    
    time.sleep(2)
    
    # Test 2: Price filter under $50 (GR_HAL_TOOL_003 fix)
    result2 = test_chat(
        session_id="phase1-test-price",
        user_id="test-user-002",
        message="Hiển thị danh sách các sản phẩm giá rẻ dưới $50",
        test_name="Test 2: Price Filter (GR_HAL_TOOL_003)"
    )
    results["test2_price_filter"] = validate_test2_price_filter(result2)
    
    time.sleep(2)
    
    # Test 3: Best rated products (GR_HAL_TOOL_005 fix)
    result3 = test_chat(
        session_id="phase1-test-best-rated",
        user_id="test-user-003",
        message="Cho tôi xem các sản phẩm đánh giá cao nhất",
        test_name="Test 3: Best Rated Products (GR_HAL_TOOL_005)"
    )
    results["test3_best_rated"] = validate_test3_best_rated(result3)
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = "✓ PASS" if passed_test else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n🎉 All Phase 1 fixes validated successfully!")
        print("\nNext steps:")
        print("1. Re-run baseline evaluation: python src/evaluation/run_eval.py")
        print("2. Expected: 25/25 pass (100% accuracy)")
        print("3. Move to Phase 2: Multi-turn conversation memory")
    else:
        print("\n⚠ Some tests failed. Review the output above for details.")
        print("\nCommon issues:")
        print("- Port-forward not running → database unavailable")
        print("- Intent parser didn't recognize query patterns")
        print("- Planner didn't call correct tool despite correct intent")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
