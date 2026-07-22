"""
src/evaluation/run_eval.py — Mandate #14 CLI Evaluation Harness for Shopping Copilot.

Script nhận file dataset có nhãn từ bên ngoài (--input), gửi request tới Copilot API,
gọi LLM-as-a-Judge đánh giá, tính p95 Latency và xuất bảng khớp Judge ↔ Human Alignment.

Sử dụng:
  python -m src.evaluation.run_eval --input src/evaluation/labeled_testcases.json
  python -m src.evaluation.run_eval --input hidden_cases.json --output hidden_report.json
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.evaluation.llm_judge import LLMJudge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("evaluation.run_eval")

DEFAULT_API_URL = os.getenv("COPILOT_API_URL", "http://localhost:8001/api/chat")


def compute_p95(latencies: List[float]) -> float:
    """Tính giá trị percentile 95 từ danh sách latency."""
    if not latencies:
        return 0.0
    sorted_lat = sorted(latencies)
    idx = int(0.95 * len(sorted_lat))
    idx = min(idx, len(sorted_lat) - 1)
    return round(sorted_lat[idx], 3)


def run_mandate14_harness(
    input_file: Path,
    output_file: Optional[Path] = None,
    api_url: str = DEFAULT_API_URL,
    judge_model: Optional[str] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Harness chính để thực thi bộ ca kiểm thử trên Shopping Copilot.
    """
    if not input_file.exists():
        raise FileNotFoundError(f"File testcase không tồn tại: {input_file}")

    with open(input_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    logger.info(f"🚀 Bắt đầu Mandate #14 Evaluation Harness: {input_file.name} ({len(cases)} cases)")
    logger.info(f"   Target Endpoint: {api_url}")
    
    # Khởi tạo LLM Judge
    judge = LLMJudge(model_id=judge_model)
    logger.info(f"   Judge Model: {judge.model_id}")

    import requests

    results = []
    latencies = []
    kind_stats: Dict[str, Dict[str, Any]] = {}
    
    agreed_with_human = 0
    cases_with_human_label = 0

    start_total_time = time.time()

    for idx, case in enumerate(cases):
        case_id = case.get("id", f"TC_{idx+1:03d}")
        case_kind = case.get("case_kind", case.get("kind", "single_intent"))
        input_text = case.get("input_text", case.get("user_input", ""))
        
        # Đọc nhãn con người (nếu có)
        human_pass = case.get("human_pass")
        human_score = case.get("human_score")

        if case_kind not in kind_stats:
            kind_stats[case_kind] = {"total": 0, "judge_passed": 0, "scores": []}
        kind_stats[case_kind]["total"] += 1

        req_body = {
            "message": input_text,
            "session_id": f"mandate14_eval_{case_id}",
            "user_id": f"eval_user_{case_id}",
        }

        # Xử lý context đặc thù nếu là multi-turn / contextual
        if case_kind == "contextual":
            setup_req = {
                "message": "Tìm một vài sản phẩm kính thiên văn giúp tôi",
                "session_id": req_body["session_id"],
                "user_id": req_body["user_id"],
            }
            try:
                requests.post(api_url, json=setup_req, timeout=30)
            except Exception as e:
                logger.warning(f"Context setup error for {case_id}: {e}")

        # Gửi request sang Copilot API và bấm giờ
        t0 = time.time()
        try:
            res = requests.post(api_url, json=req_body, timeout=45)
            res_data = res.json()
            status_code = res.status_code
        except Exception as e:
            res_data = {"status": "error", "reply": f"API request error: {e}", "steps": []}
            status_code = 500
        
        elapsed = time.time() - t0
        latencies.append(elapsed)

        reply = res_data.get("reply", "")
        status = res_data.get("status", "error" if status_code != 200 else "ok")
        intent = res_data.get("intent")
        evidence = res_data.get("evidence")

        # LLM Judge đánh giá
        verdict = judge.judge(
            case_kind=case_kind,
            user_input=input_text,
            reply=reply,
            status=status,
            intent=intent,
            evidence=evidence
        )

        judge_pass = verdict.get("pass", False)
        judge_score = verdict.get("score", 0)
        judge_reason = verdict.get("reason", "")

        if judge_pass:
            kind_stats[case_kind]["judge_passed"] += 1
        kind_stats[case_kind]["scores"].append(judge_score)

        # Tính độ khớp với con người (Judge ↔ Human Alignment)
        aligned = None
        if human_pass is not None:
            cases_with_human_label += 1
            aligned = (judge_pass == human_pass)
            if aligned:
                agreed_with_human += 1

        case_result = {
            "id": case_id,
            "case_kind": case_kind,
            "input_text": input_text,
            "reply": reply,
            "status": status,
            "latency_sec": round(elapsed, 3),
            "human_pass": human_pass,
            "human_score": human_score,
            "judge_pass": judge_pass,
            "judge_score": judge_score,
            "judge_reason": judge_reason,
            "aligned_with_human": aligned
        }
        results.append(case_result)

        if verbose:
            icon = "✅" if judge_pass else "❌"
            align_str = f"| Match Human: {'YES' if aligned else 'NO'}" if aligned is not None else ""
            print(f"[{idx+1}/{len(cases)}] {icon} {case_id} ({case_kind}) -> Judge Pass: {judge_pass} Score: {judge_score}/10 {align_str}")
            if not judge_pass:
                print(f"    Input:  {input_text}")
                print(f"    Reply:  {reply[:120]}...")
                print(f"    Reason: {judge_reason}\n")

    total_time = round(time.time() - start_total_time, 2)
    total_cases = len(cases)
    total_judge_passed = sum(1 for r in results if r["judge_pass"])
    overall_pass_rate = round((total_judge_passed / total_cases * 100), 2) if total_cases > 0 else 0.0
    p95_latency = compute_p95(latencies)
    avg_latency = round(sum(latencies) / len(latencies), 3) if latencies else 0.0

    agreement_rate = round((agreed_with_human / cases_with_human_label * 100), 2) if cases_with_human_label > 0 else 0.0

    # Phân tích theo từng tiêu chí kind
    per_kind_summary = {}
    for k, stats in kind_stats.items():
        k_tot = stats["total"]
        k_pass = stats["judge_passed"]
        k_scores = stats["scores"]
        per_kind_summary[k] = {
            "total": k_tot,
            "passed": k_pass,
            "pass_rate_pct": round((k_pass / k_tot * 100), 1) if k_tot > 0 else 0.0,
            "avg_score": round(sum(k_scores) / len(k_scores), 2) if k_scores else 0.0
        }

    report = {
        "mandate": "MANDATE #14 - AI Evaluation Standard",
        "input_dataset": input_file.name,
        "judge_model": judge.model_id,
        "total_cases": total_cases,
        "total_passed": total_judge_passed,
        "overall_pass_rate_pct": overall_pass_rate,
        "latency_metrics": {
            "p95_latency_sec": p95_latency,
            "avg_latency_sec": avg_latency,
            "total_eval_time_sec": total_time
        },
        "judge_human_alignment": {
            "human_labeled_cases": cases_with_human_label,
            "agreed_cases": agreed_with_human,
            "agreement_rate_pct": agreement_rate
        },
        "per_kind_metrics": per_kind_summary,
        "detailed_results": results
    }

    if output_file is None:
        reports_dir = Path(__file__).resolve().parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_file = reports_dir / f"{input_file.stem}_report.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n" + "="*60)
    print("📊 BÁO CÁO KẾT QUẢ EVALUATION (MANDATE #14)")
    print("="*60)
    print(f"Tổng số test case    : {total_cases}")
    print(f"Tỷ lệ Pass (Judge)    : {overall_pass_rate}% ({total_judge_passed}/{total_cases})")
    print(f"Độ khớp Judge ↔ Human : {agreement_rate}% ({agreed_with_human}/{cases_with_human_label})")
    print(f"Latency P95           : {p95_latency}s (Avg: {avg_latency}s)")
    print("-" * 60)
    print("Chi tiết từng nhóm chỉ số:")
    for k, m in per_kind_summary.items():
        bar = "█" * int(m["pass_rate_pct"] / 10) + "░" * (10 - int(m["pass_rate_pct"] / 10))
        print(f"  [{bar}] {k:<23} {m['pass_rate_pct']:>5.1f}% | Score: {m['avg_score']:>4.1f}/10")
    print("="*60)
    print(f"📁 Báo cáo chi tiết đã lưu tại: {output_file}\n")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mandate #14 Evaluation Harness CLI")
    parser.add_argument("--input", "-i", type=str, default="src/evaluation/datasets/labeled_testcases.json", help="Đường dẫn file testcases input JSON")
    parser.add_argument("--output", "-o", type=str, default=None, help="Đường dẫn lưu file report JSON kết quả")
    parser.add_argument("--api-url", type=str, default=DEFAULT_API_URL, help="URL API Copilot")
    parser.add_argument("--judge-model", type=str, default=None, help="Override ID model cho LLM Judge")

    args = parser.parse_args()

    inp_path = Path(args.input)
    out_path = Path(args.output) if args.output else None

    run_mandate14_harness(
        input_file=inp_path,
        output_file=out_path,
        api_url=args.api_url,
        judge_model=args.judge_model
    )

