"""
evaluation/eval_baselines.py — Evaluation runner với LLM-as-a-Judge.

Thay thế toàn bộ hardcoded keyword matching bằng LLM Judge (Nova Micro).
Fallback về heuristic nếu Bedrock không khả dụng.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import json
import time
import requests
import logging
from pathlib import Path
from typing import Optional

# Add project root to sys.path to resolve 'src' imports
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.evaluation.llm_judge import LLMJudge, HeuristicJudge

logger = logging.getLogger("evaluation.eval_baselines")

API_URL = "http://localhost:8001/api/chat"


def run_evaluation(
    file_path: Path,
    use_llm_judge: bool = True,
    judge_model_id: Optional[str] = None,
    max_cases: Optional[int] = None,
    session_prefix: str = "eval",
    verbose: bool = True,
):
    """
    Chạy evaluation trên một file baseline JSON.

    Args:
        file_path:       Đường dẫn tới file baseline (JSON array of cases).
        use_llm_judge:   True → dùng LLM judge; False → dùng keyword fallback.
        judge_model_id:  Override model ID cho judge (default: env JUDGE_MODEL_ID).
        max_cases:       Giới hạn số case chạy (None = chạy tất cả).
        session_prefix:  Prefix cho session_id để tránh va chạm giữa các run.
        verbose:         In chi tiết từng case FAIL.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if max_cases:
        cases = cases[:max_cases]

    total = len(cases)
    passed = 0
    results = []
    judge_method_counts = {"llm": 0, "fallback": 0, "llm_parse_error": 0}

    judge = LLMJudge(model_id=judge_model_id) if use_llm_judge else None

    print(f"\n🚀 Bắt đầu đánh giá: {file_path.name} ({total} cases)")
    print(f"   Judge: {'LLM (' + (judge_model_id or 'default') + ')' if use_llm_judge else 'Keyword Fallback'}\n")
    start_time = time.time()

    kind_stats: dict[str, dict] = {}

    for idx, case in enumerate(cases):
        case_kind = case.get("case_kind") or case.get("kind", "single_intent")
        if case_kind not in kind_stats:
            kind_stats[case_kind] = {"total": 0, "passed": 0, "scores": []}
        kind_stats[case_kind]["total"] += 1

        req_body = {
            "message": case["input_text"],
            "session_id": f"{session_prefix}_session_{case['id']}",
            "user_id": f"eval_user_{case['id']}",
        }

        # ── Setup Context for Contextual Cases ──
        setup_evidence = None
        setup_query = case.get("setup_query")
        
        if setup_query:
            setup_req = {
                "message": setup_query,
                "session_id": req_body["session_id"],
                "user_id": req_body["user_id"],
            }
            try:
                setup_res = requests.post(API_URL, json=setup_req, timeout=45)
                if setup_res.status_code == 200:
                    setup_evidence = setup_res.json().get("evidence")
            except Exception as e:
                logger.error(f"Setup context failed for {case['id']}: {e}")

        t0 = time.time()
        try:
            res = requests.post(API_URL, json=req_body, timeout=45)
            data = res.json()
        except Exception as e:
            data = {"status": "error", "reply": f"Request failed: {e}", "steps": []}
        latency = time.time() - t0

        reply = data.get("reply", "")
        status = data.get("status", "error")
        intent = data.get("intent")
        evidence = data.get("evidence")

        # Combine setup_evidence into evidence if available so Judge has ground truth of prior turn
        if setup_evidence and isinstance(evidence, dict):
            evidence = {**setup_evidence, **evidence}

        # ── Đánh giá bằng LLM Judge ──
        if judge:
            verdict = judge.judge(
                case_kind=case_kind,
                user_input=case["input_text"],
                reply=reply,
                status=status,
                intent=intent,
                evidence=evidence,
            )
        else:
            h_judge = HeuristicJudge()
            verdict = h_judge.judge(case, reply, status)

        is_pass = verdict.get("pass", False)
        score = verdict.get("score", 0)
        reason = verdict.get("reason", "")
        jmethod = verdict.get("judge_method", "heuristic")
        judge_method_counts[jmethod] = judge_method_counts.get(jmethod, 0) + 1

        if is_pass:
            passed += 1
            kind_stats[case_kind]["passed"] += 1
        kind_stats[case_kind]["scores"].append(score)

        if verbose and not is_pass:
            print(f"  ❌ FAIL [{case['id']}] kind={case_kind}")
            print(f"      Input : {case['input_text'][:80]}")
            print(f"      Reply : {reply[:120]}...")
            print(f"      Reason: {reason}")
            print(f"      Score : {score}/10\n")

        results.append({
            "id": case["id"],
            "kind": case_kind,
            "passed": is_pass,
            "score": score,
            "latency_sec": round(latency, 2),
            "judge_reason": reason,
            "judge_method": jmethod,
            # Full content for PM review
            "input_text": case["input_text"],
            "reply": reply,
            "reply_preview": reply[:200],
        })

        if (idx + 1) % 10 == 0:
            print(f"  Tiến độ: {idx + 1}/{total} | Passed: {passed}/{idx + 1} ({passed/(idx+1)*100:.0f}%)")

    # ── Metrics tổng hợp ──
    total_time = time.time() - start_time
    accuracy = passed / total if total > 0 else 0
    avg_latency = sum(r["latency_sec"] for r in results) / total if total > 0 else 0
    avg_score = sum(r["score"] for r in results) / total if total > 0 else 0

    # Metrics theo kind
    per_kind = {}
    for kind, stats in kind_stats.items():
        k_total = stats["total"]
        k_pass = stats["passed"]
        scores = stats["scores"]
        per_kind[kind] = {
            "total": k_total,
            "passed": k_pass,
            "accuracy": round(k_pass / k_total, 3) if k_total > 0 else 0,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        }

    report = {
        "file": file_path.name,
        "judge_model": judge.model_id if judge else "keyword_heuristic",
        "total_cases": total,
        "passed_cases": passed,
        "metrics": {
            "accuracy_rate": round(accuracy, 3),
            "avg_score_10": round(avg_score, 2),
            "avg_latency_sec": round(avg_latency, 3),
            "total_time_sec": round(total_time, 2),
        },
        "judge_method_distribution": judge_method_counts,
        "per_kind_metrics": per_kind,
        # Chi tiết từng case: câu hỏi, câu trả lời đầy đủ, kết quả judge
        "all_samples": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "passed": r["passed"],
                "score": r["score"],
                "input_text": r["input_text"],
                "reply": r["reply"],
                "judge_reason": r["judge_reason"],
                "judge_method": r["judge_method"],
                "latency_sec": r["latency_sec"],
            }
            for r in results
        ],
        "failed_samples": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "input_text": r["input_text"],
                "reply": r["reply"],
                "judge_reason": r["judge_reason"],
                "score": r["score"],
            }
            for r in results if not r["passed"]
        ][:20],
    }

    reports_dir = file_path.parent.parent / "reports" if file_path.parent.name == "datasets" else file_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_file = reports_dir / (file_path.stem + "_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ── Summary print ──
    print(f"\n{'='*60}")
    print(f"✅ Kết quả: {file_path.name}")
    print(f"   Tỷ lệ PASS    : {accuracy*100:.1f}% ({passed}/{total})")
    print(f"   Avg Score     : {avg_score:.1f}/10")
    print(f"   Avg Latency   : {avg_latency:.2f}s")
    print(f"   Judge method  : {judge_method_counts}")
    print(f"\n   Per-kind breakdown:")
    for kind, m in per_kind.items():
        bar = "█" * int(m["accuracy"] * 10) + "░" * (10 - int(m["accuracy"] * 10))
        print(f"   [{bar}] {kind:<20} {m['accuracy']*100:.0f}% ({m['passed']}/{m['total']}) score={m['avg_score']:.1f}")
    print(f"\n   Report lưu tại: {out_file.name}")
    print(f"{'='*60}\n")

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Shopping Copilot Evaluation Runner")
    parser.add_argument("--llm", action="store_true", help="Bật LLM judge (Bedrock), mặc định dùng Heuristic Rule-based")
    parser.add_argument("--max", type=int, default=None, help="Giới hạn số case chạy")
    parser.add_argument("--model", type=str, default=None, help="Override judge model ID")
    parser.add_argument("--file", type=str, default=None, help="Chỉ chạy 1 file cụ thể")
    args = parser.parse_args()

    base_dir = Path(__file__).parent
    datasets_dir = base_dir / "datasets"
    use_llm = True  # Luôn dùng LLM Judge theo yêu cầu

    if args.file:
        files = [Path(args.file) if Path(args.file).exists() else datasets_dir / args.file]
    else:
        files = [
            datasets_dir / "baseline_guardrails.json",
            datasets_dir / "labeled_testcases.json",
        ]


    for fp in files:
        if fp.exists():
            run_evaluation(
                fp,
                use_llm_judge=use_llm,
                judge_model_id=args.model,
                max_cases=args.max,
                verbose=True,
            )
        else:
            print(f"⚠️  File không tồn tại: {fp}")
