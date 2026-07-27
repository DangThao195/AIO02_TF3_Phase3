#!/usr/bin/env python3
"""Test a single request and print detailed debug info"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import json

async def main():
    from src.agent.copilot_agent import CopilotAgent
    
    agent = CopilotAgent()
    
    print("=" * 80)
    print("SINGLE REQUEST DEBUG TEST")
    print("=" * 80)
    
    test_message = "Cho tôi xem các sản phẩm đánh giá cao nhất"
    print(f"\nUser message: {test_message}")
    
    result = await agent.chat(
        session_id="debug-test",
        user_id="debug-user",
        user_message=test_message
    )
    
    print("\n" + "=" * 80)
    print("RESULT")
    print("=" * 80)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Check evidence
    if "evidence" in result:
        print("\n" + "=" * 80)
        print("EVIDENCE DATA")
        print("=" * 80)
        for key, value in result["evidence"].items():
            if key == "__intent_meta__":
                continue
            print(f"\n[{key}]")
            if isinstance(value, dict):
                print(json.dumps(value, indent=2, ensure_ascii=False)[:500])
            else:
                print(str(value)[:500])

if __name__ == "__main__":
    asyncio.run(main())
