#!/usr/bin/env python3
"""
mini_test.py — Diagnostic test to find root cause of 500 error

Run: python mini_test.py
"""
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*80)
print("MINI DIAGNOSTIC TEST")
print("="*80)

# Test 1: Import modules
print("\n[1/5] Testing imports...")
try:
    from src.agent.copilot_agent import CopilotAgent
    print("✓ CopilotAgent imported")
except Exception as e:
    print(f"✗ FAIL: Cannot import CopilotAgent")
    print(f"  Error: {e}")
    sys.exit(1)

try:
    from src.tools import all_shopping_tools
    print(f"✓ all_shopping_tools imported ({len(all_shopping_tools)} tools)")
except Exception as e:
    print(f"✗ FAIL: Cannot import all_shopping_tools")
    print(f"  Error: {e}")
    sys.exit(1)

# Test 2: Check new tools are registered
print("\n[2/5] Checking tool registration...")
tool_names = [t.name for t in all_shopping_tools]
required_tools = [
    "get_products_by_price_range",
    "get_best_reviewed_products_tool",
    "get_worst_reviewed_products_tool"
]
for tool_name in required_tools:
    if tool_name in tool_names:
        print(f"✓ {tool_name} registered")
    else:
        print(f"✗ MISSING: {tool_name} not in all_shopping_tools")

# Test 3: Check TOOLS_MAP
print("\n[3/5] Checking TOOLS_MAP...")
try:
    TOOLS_MAP = {t.name: t for t in all_shopping_tools}
    for tool_name in required_tools:
        if tool_name in TOOLS_MAP:
            print(f"✓ {tool_name} in TOOLS_MAP")
        else:
            print(f"✗ {tool_name} NOT in TOOLS_MAP")
except Exception as e:
    print(f"✗ FAIL: Cannot create TOOLS_MAP")
    print(f"  Error: {e}")

# Test 4: Try to initialize CopilotAgent
print("\n[4/5] Initializing CopilotAgent...")
try:
    agent = CopilotAgent()
    print("✓ CopilotAgent initialized")
except Exception as e:
    print(f"✗ FAIL: Cannot initialize CopilotAgent")
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Try a simple intent parsing (without LLM)
print("\n[5/5] Testing fallback intent parser...")
try:
    # Create a fake session
    session = {
        "session_id": "test",
        "user_id": "test-user",
        "context": {},
        "messages": []
    }
    
    # Test price filter intent
    test_intent = {
        "task_type": "search",
        "constraints": {"price_max": 50},
        "product_query": "cheap products"
    }
    
    plan = agent._build_plan_from_intent(test_intent, "test-user")
    print(f"✓ Generated plan with {len(plan)} steps:")
    for i, step in enumerate(plan):
        print(f"  {i+1}. {step['name']}({step.get('args', {})})")
    
    # Check if price filter tool is used
    if any(s['name'] == 'get_products_by_price_range' for s in plan):
        print("✓ Price filter tool IS called in plan")
    else:
        print("✗ WARNING: Price filter tool NOT called in plan")
        
except Exception as e:
    print(f"✗ FAIL: Intent parsing failed")
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("DIAGNOSTIC COMPLETE")
print("="*80)
print("\nIf all checks passed, the issue is likely:")
print("  1. Bedrock LLM connection (check AWS credentials)")
print("  2. Database connection (check port-forward)")
print("  3. SQL syntax error (check get_products_by_price_range)")
print("\nNext: Check uvicorn logs for detailed error stack trace")
