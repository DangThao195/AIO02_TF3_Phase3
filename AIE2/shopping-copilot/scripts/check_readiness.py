"""
scripts/check_readiness.py — Kiểm tra:
1. False-block-rate coverage trong testcase dataset
2. Tool connectivity để biết tool nào thật sự lỗi do service vs LLM từ chối sai
"""
import sys, json, asyncio
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# ── 1. Load datasets ─────────────────────────────────────────────────────────
dataset = json.load(open(BASE / "src/evaluation/datasets/labeled_testcases.json", encoding="utf-8"))
sheet   = json.load(open(BASE / "src/evaluation/reports/labeling_sheet.json", encoding="utf-8"))
report_data = json.load(open(BASE / "src/evaluation/reports/labeled_testcases_report.json", encoding="utf-8"))
report  = {r["id"]: r for r in report_data["detailed_results"]}

# ── 2. FALSE-BLOCK-RATE ANALYSIS ─────────────────────────────────────────────
print("=" * 70)
print("PHẦN 1: FALSE-BLOCK-RATE COVERAGE")
print("=" * 70)

# Cases được thiết kế để test false-positive (benign bị block sai)
false_positive_kinds = {"prompt_injection"}  # có case benign trong đó
benign_markers = [
    "tìm kính thiên văn có hệ thống dẫn đường",  # TC_INJ_010
    "override my previous order",               # TC_INJ_011
    "ignore the shipping cost",                 # TC_INJ_012
]

benign_cases = []
for d in dataset:
    reason = (d.get("human_reason") or "").lower()
    inp = (d.get("input_text") or "").lower()
    # Detect benign test (false positive test)
    is_benign_test = (
        "false-positive" in reason
        or "false positive" in reason
        or "benign" in reason
        or "câu hỏi benign" in reason
        or any(marker in inp for marker in benign_markers)
    )
    if is_benign_test:
        benign_cases.append(d)

print(f"\n▸ Tổng testcase: {len(dataset)}")
print(f"▸ Case được thiết kế để test false-positive (benign bị block): {len(benign_cases)}")
print(f"\nDanh sách case false-positive test:")
for d in benign_cases:
    cid = d["id"]
    r = report.get(cid, {})
    sh = next((s for s in sheet if s["id"] == cid), {})
    print(f"  [{cid}] Pass={d.get('human_pass')} Score={d.get('human_score')}")
    print(f"    Input: {d['input_text'][:80]}")
    print(f"    Reason: {d.get('human_reason','')[:100]}")

# Phân tích false-block: benign query bị system từ chối sai
false_blocked = [d for d in benign_cases if not d.get("human_pass")]
print(f"\n▸ False-block xảy ra (benign bị từ chối SAI): {len(false_blocked)}")
for d in false_blocked:
    print(f"  → [{d['id']}] {d['input_text'][:80]}")

print(f"\n▸ False-block-rate: {len(false_blocked)}/{len(benign_cases)} = {len(false_blocked)/max(len(benign_cases),1)*100:.1f}%")

# ── 3. TOOL CONNECTIVITY CHECK ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PHẦN 2: TOOL CONNECTIVITY — LỖI DO SERVICE HAY LLM BỊ OAN?")
print("=" * 70)

# Lấy tất cả case FAIL mà human xác nhận evidence có data (LLM bị oan)
print("\n▸ Cases FAIL vì LLM từ chối dù evidence CÓ DATA (LLM bị oan):")
llm_oan = []
for s in sheet:
    if s.get("human_pass") == False:
        reason = (s.get("human_reason") or "").lower()
        cid = s["id"]
        r = report.get(cid, {})
        ev = r.get("evidence", {})
        
        # Check if tools returned data but LLM refused anyway
        has_data = any(
            ev.get(k, {}).get("total", 0) > 0 or
            len(ev.get(k, {}).get("products", [])) > 0 or
            (isinstance(ev.get(k), dict) and ev.get(k, {}).get("matched") == True)
            for k in ev if not k.startswith("__")
        )
        
        # Human reason says evidence has data but reply is wrong
        evidence_has_data_phrases = [
            "evidence có", "evidence match", "dữ liệu có sẵn", "matched: true",
            "evidence chính xác", "rõ ràng có", "evidence có sẵn"
        ]
        human_says_data_available = any(p in reason for p in evidence_has_data_phrases)
        
        if human_says_data_available or has_data:
            llm_oan.append((s, r, ev))

for s, r, ev in llm_oan:
    cid = s["id"]
    tool_names = [k for k in ev if not k.startswith("__")]
    tool_statuses = {k: ev[k].get("status", "?") if isinstance(ev[k], dict) else "?" for k in tool_names}
    tool_errors  = {k: ev[k].get("error", "") for k in tool_names if isinstance(ev[k], dict) and ev[k].get("error")}
    print(f"\n  [{cid}] Score={s.get('human_score')}")
    print(f"    Input: {s['input_text'][:80]}")
    print(f"    Tools called: {tool_statuses}")
    if tool_errors:
        print(f"    Tool errors: {tool_errors}")
    print(f"    Human reason: {s['human_reason'][:120]}")

print("\n▸ Cases FAIL vì tool thật sự lỗi / service unavailable:")
service_errors = []
for s in sheet:
    if s.get("human_pass") == False:
        cid = s["id"]
        r = report.get(cid, {})
        ev = r.get("evidence", {})
        
        for k in ev:
            if k.startswith("__"):
                continue
            tool_ev = ev.get(k, {})
            if isinstance(tool_ev, dict):
                err = tool_ev.get("error", "")
                if err and any(kw in err.lower() for kw in ["grpc", "connection refused", "unavailable", "wsagetoverlappedresult", "validation error"]):
                    service_errors.append((s, k, err))
                    break

for s, tool_name, err in service_errors:
    print(f"  [{s['id']}] Tool={tool_name}")
    print(f"    Error: {err[:120]}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"  False-block testcases:     {len(benign_cases)} cases")
print(f"  False-block-rate hiện tại: {len(false_blocked)}/{len(benign_cases)} = {len(false_blocked)/max(len(benign_cases),1)*100:.1f}%")
print(f"  LLM bị oan (có data, fail): {len(llm_oan)} cases")
print(f"  Service thật sự lỗi:       {len(service_errors)} cases")
print(f"  → Cần fix trong code:      {len(llm_oan) - len(service_errors)} cases thực sự do LLM/prompt")
