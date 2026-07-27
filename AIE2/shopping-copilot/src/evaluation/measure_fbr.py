#!/usr/bin/env python3
"""
Measure False Block Rate (FBR) for guardrails.
Run negative test cases (valid requests) through the system.
If system blocks/refuses valid request = False Positive = contributes to FBR.
"""
import os
import sys
import json
import logging
import asyncio
from dotenv import load_dotenv

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.agent.copilot_agent import CopilotAgent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("measure_fbr")

async def measure_false_block_rate():
    # Load negative test cases - use absolute path
    test_cases_path = os.path.join(os.path.dirname(__file__), "datasets", "negative_testcases.json")
    with open(test_cases_path, "r", encoding="utf-8") as f:
        negative_cases = json.load(f)
    
    agent = CopilotAgent()
    results = {
        "metric": "False Block Rate (FBR)",
        "description": "Ratio of valid requests incorrectly blocked/refused",
        "total_negative_cases": len(negative_cases),
        "false_positives": [],
        "true_negatives": [],
        "summary": {}
    }
    
    print("=" * 70)
    print("FALSE BLOCK RATE (FBR) MEASUREMENT")
    print("=" * 70)
    print(f"Testing {len(negative_cases)} valid requests for false blocks...\n")
    
    # Group by category
    by_category = {}
    for tc in negative_cases:
        cat = tc.get("case_kind", "unknown")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(tc)
    
    # Test each case
    for category, cases in by_category.items():
        print(f"\n[{category.upper()}] Testing {len(cases)} cases...")
        print("-" * 70)
        
        false_positives_in_cat = 0
        
        for i, tc in enumerate(cases, 1):
            tc_id = tc.get("id", "unknown")
            user_input = tc.get("input_text", "")
            should_pass = tc.get("should_pass", True)
            
            try:
                # Execute through copilot
                logger.info(f"[{tc_id}] Processing: {user_input[:60]}...")
                
                # Call agent chat (simulate)
                # Note: In real scenario, would call HTTP API or agent.aexecute()
                # For now, we'll check if input triggers guardrails
                
                from src.guardrails import check_input, check_input_bedrock
                from src.guardrails import filter_output
                
                # Check if input is blocked
                input_result = check_input(user_input)
                
                if not input_result.is_safe:
                    # Input was blocked by guardrail
                    if should_pass:
                        # False positive! Valid request was blocked
                        false_positives_in_cat += 1
                        results["false_positives"].append({
                            "tc_id": tc_id,
                            "input": user_input[:100],
                            "reason": input_result.reason,
                            "category": category
                        })
                        print(f"  [X] {tc_id}: FALSELY BLOCKED")
                        print(f"    Input: {user_input[:60]}")
                        print(f"    Reason: {input_result.reason}")
                    else:
                        # Correctly blocked
                        print(f"  [OK] {tc_id}: Correctly blocked (as expected)")
                else:
                    # Input passed guardrail check
                    if should_pass:
                        # Correctly allowed
                        results["true_negatives"].append({
                            "tc_id": tc_id,
                            "input": user_input[:100],
                            "category": category
                        })
                        print(f"  [OK] {tc_id}: Correctly allowed")
                    else:
                        # Should have been blocked but wasn't
                        print(f"  [X] {tc_id}: Should have been blocked but wasn't")
            
            except Exception as e:
                print(f"  [!] {tc_id}: Error during test: {e}")
        
        # Summary for category
        cat_summary = {
            "total": len(cases),
            "false_positives": false_positives_in_cat,
            "false_block_rate": round(false_positives_in_cat / len(cases) * 100, 2) if cases else 0,
            "true_negatives": len(cases) - false_positives_in_cat
        }
        results["summary"][category] = cat_summary
        print(f"  Summary: {cat_summary['true_negatives']}/{len(cases)} allowed | {cat_summary['false_positives']} false blocks | FBR: {cat_summary['false_block_rate']}%")
    
    # Overall summary
    total_fps = len(results["false_positives"])
    overall_fbr = round(total_fps / len(negative_cases) * 100, 2) if negative_cases else 0
    
    results["overall"] = {
        "total_cases": len(negative_cases),
        "false_positives": total_fps,
        "true_negatives": len(results["true_negatives"]),
        "false_block_rate_pct": overall_fbr,
        "true_allow_rate_pct": round((len(results["true_negatives"]) / len(negative_cases) * 100), 2)
    }
    
    # Print overall results
    print("\n" + "=" * 70)
    print("OVERALL FALSE BLOCK RATE (FBR)")
    print("=" * 70)
    print(f"Total Valid Requests: {results['overall']['total_cases']}")
    print(f"Correctly Allowed: {results['overall']['true_negatives']}")
    print(f"Falsely Blocked: {results['overall']['false_positives']}")
    print(f"\n[OK] True Allow Rate: {results['overall']['true_allow_rate_pct']}%")
    print(f"[X] False Block Rate (FBR): {results['overall']['false_block_rate_pct']}%")
    print("=" * 70)
    
    # Save results - use absolute path
    output_path = os.path.join(os.path.dirname(__file__), "reports", "fbr_measurement.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to: {output_path}")
    
    return results

if __name__ == "__main__":
    asyncio.run(measure_false_block_rate())
