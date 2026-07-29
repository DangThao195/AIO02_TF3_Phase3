"""
scripts/analyze_failures.py — Phân tích các case FAIL theo human để hướng dẫn cải thiện hệ thống
"""
import sys, json
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
sheet = json.load(open(BASE / "src/evaluation/reports/labeling_sheet.json", encoding="utf-8"))
report_data = json.load(open(BASE / "src/evaluation/reports/labeled_testcases_report.json", encoding="utf-8"))
report = {r["id"]: r for r in report_data["detailed_results"]}

failed = [s for s in sheet if s.get("human_pass") == False]
passed = [s for s in sheet if s.get("human_pass") == True]

print(f"=== TỔNG SỐ CASE FAIL (human): {len(failed)}/{len(sheet)} ===\n")
print(f"=== TỔNG SỐ CASE PASS (human): {len(passed)}/{len(sheet)} ===\n")

# Nhóm theo kind
by_kind = defaultdict(list)
for s in failed:
    by_kind[s["case_kind"]].append(s)

print("=== PHÂN TÍCH THẤT BẠI THEO CATEGORY ===")
for kind, cases in sorted(by_kind.items()):
    print(f"\n--- [{kind.upper()}] {len(cases)} CASE FAIL ---")
    for s in cases:
        cid = s["id"]
        r = report.get(cid, {})
        ev = r.get("evidence", {})
        # Xác định root cause
        tool_calls = [k for k in ev.keys() if not k.startswith("__")]
        tool_info = []
        for tc in tool_calls:
            t = ev[tc]
            total = t.get("total", "?")
            err = t.get("error", None)
            tool_info.append(f"{tc}(total={total}{'|ERR:' + err if err else ''})")

        print(f"  [{cid}] score={s['human_score']}")
        print(f"    Input   : {s['input_text'][:100]}")
        print(f"    Reply   : {s['reply'][:130]}")
        print(f"    Reason  : {s['human_reason'][:120]}")
        print(f"    Tools   : {', '.join(tool_info) if tool_info else 'N/A'}")

print("\n\n=== DANH SÁCH ROOT CAUSE TỔNG HỢP ===")

# Root cause classification
root_causes = {
    "price_rounding": [],
    "abstain_when_data_available": [],
    "incomplete_list": [],
    "category_mismatch": [],
    "missing_context_resolve": [],
    "placeholder_bug": [],
    "tool_returns_empty": [],
    "other": [],
}

for s in failed:
    reason = s["human_reason"].lower()
    cid = s["id"]
    r = report.get(cid, {})
    ev = r.get("evidence", {})

    if "làm tròn" in reason or "lệch" in reason or "khác" in reason and "giá" in reason:
        root_causes["price_rounding"].append(cid)
    elif "không có thông tin" in s["reply"].lower() and ("có sẵn" in reason or "bỏ sót" in reason or "matched" in reason):
        root_causes["abstain_when_data_available"].append(cid)
    elif "placeholder" in reason or "[list" in s["reply"].lower() or "$ctm" in s["reply"].lower() or "$prev" in s["reply"].lower():
        root_causes["placeholder_bug"].append(cid)
    elif "bỏ sót" in reason or "thiếu" in reason or "đủ" in reason:
        root_causes["incomplete_list"].append(cid)
    elif "category" in reason or "phụ kiện" in reason and "kính thiên văn" in s["input_text"].lower():
        root_causes["category_mismatch"].append(cid)
    elif any(ev.get(k, {}).get("total", -1) == 0 for k in ev if not k.startswith("__")):
        root_causes["tool_returns_empty"].append(cid)
    else:
        root_causes["other"].append(cid)

for cause, ids in root_causes.items():
    if ids:
        print(f"\n[{cause}] ({len(ids)} case): {', '.join(ids)}")
