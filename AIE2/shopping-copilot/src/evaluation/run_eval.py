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
COPILOT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")

# ── Token Cost Table (USD per 1K tokens — Amazon Bedrock pricing) ──
TOKEN_COST_TABLE = {
    "apac.amazon.nova-lite-v1:0":      {"input": 0.00006, "output": 0.00024},
    "amazon.nova-lite-v1:0":           {"input": 0.00006, "output": 0.00024},
    "amazon.nova-micro-v1:0":          {"input": 0.000035, "output": 0.00014},
    "amazon.nova-pro-v1:0":            {"input": 0.0008,  "output": 0.0032},
    "meta.llama3-1-70b-instruct-v1:0": {"input": 0.00099, "output": 0.00099},
    "default":                         {"input": 0.0003,  "output": 0.0012},
}


def estimate_tokens(text: str) -> int:
    """Ước lượng token count (heuristic: ~1.1 token/word cho mixed VI/EN)."""
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.1))


def compute_token_cost(input_text: str, reply: str, model_id: str = "default") -> Dict[str, Any]:
    """
    Tính ước lượng token usage + cost cho 1 request (Mandate #14: token/cost per request).

    Ưu tiên dùng token thật nếu API trả về `usage`; nếu không có thì fallback ước lượng.
    """
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(reply)
    total_tokens = input_tokens + output_tokens

    rates = TOKEN_COST_TABLE.get(model_id, TOKEN_COST_TABLE["default"])
    input_cost = (input_tokens / 1000) * rates["input"]
    output_cost = (output_tokens / 1000) * rates["output"]

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_cost_usd": round(input_cost, 8),
        "output_cost_usd": round(output_cost, 8),
        "total_cost_usd": round(input_cost + output_cost, 8),
        "model_id": model_id,
        "source": "estimated",
    }


def resolve_token_cost(res_data: Dict[str, Any], input_text: str, reply: str, model_id: str) -> Dict[str, Any]:
    """
    Lấy token/cost cho 1 request. Nếu API response có field `usage`
    (input_tokens/output_tokens thật từ Bedrock) → dùng số thật; nếu không → ước lượng.
    """
    usage = res_data.get("usage") or {}
    it = usage.get("input_tokens") or usage.get("inputTokens")
    ot = usage.get("output_tokens") or usage.get("outputTokens")

    if isinstance(it, int) and isinstance(ot, int):
        rates = TOKEN_COST_TABLE.get(model_id, TOKEN_COST_TABLE["default"])
        input_cost = (it / 1000) * rates["input"]
        output_cost = (ot / 1000) * rates["output"]
        return {
            "input_tokens": it,
            "output_tokens": ot,
            "total_tokens": it + ot,
            "input_cost_usd": round(input_cost, 8),
            "output_cost_usd": round(output_cost, 8),
            "total_cost_usd": round(input_cost + output_cost, 8),
            "model_id": model_id,
            "source": "api_usage",
        }
    return compute_token_cost(input_text, reply, model_id)


def load_baseline(baseline_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Load baseline 'before' metrics để so sánh before/after (Mandate #14)."""
    if baseline_path is None:
        baseline_path = Path(__file__).resolve().parent / "reports" / "cost_latency_baseline.json"
    if baseline_path.exists():
        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Không đọc được baseline {baseline_path}: {e}")
    return None


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
    verbose: bool = True,
    save_baseline: bool = True,
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

    # Token/cost accumulators (Mandate #14)
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0
    per_request_costs: List[float] = []

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

        # ── Token/cost per request (Mandate #14) ──
        cost_info = resolve_token_cost(res_data, input_text, reply, COPILOT_MODEL_ID)
        total_input_tokens += cost_info["input_tokens"]
        total_output_tokens += cost_info["output_tokens"]
        total_cost_usd += cost_info["total_cost_usd"]
        per_request_costs.append(cost_info["total_cost_usd"])

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
            "tokens": {
                "input": cost_info["input_tokens"],
                "output": cost_info["output_tokens"],
                "total": cost_info["total_tokens"],
            },
            "cost_usd": cost_info["total_cost_usd"],
            "cost_source": cost_info["source"],
            "evidence": evidence,
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

    # ── Cost/Token metrics tổng hợp (Mandate #14) ──
    avg_cost_per_request = round(total_cost_usd / total_cases, 8) if total_cases > 0 else 0.0
    avg_tokens_per_request = round((total_input_tokens + total_output_tokens) / total_cases, 1) if total_cases > 0 else 0.0
    p95_cost = compute_p95(per_request_costs)
    cost_metrics = {
        "copilot_model_id": COPILOT_MODEL_ID,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "total_cost_usd": round(total_cost_usd, 6),
        "avg_tokens_per_request": avg_tokens_per_request,
        "avg_cost_per_request_usd": avg_cost_per_request,
        "p95_cost_per_request_usd": p95_cost,
    }

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

    # ── Before/After comparison (Mandate #14: cost/latency before/after) ──
    baseline = load_baseline()
    before_after = None
    if baseline:
        b_lat = baseline.get("latency_metrics", {})
        b_cost = baseline.get("cost_metrics", {})

        def _delta(after_v, before_v):
            if before_v in (None, 0):
                return None
            return round((after_v - before_v) / before_v * 100, 1)

        before_after = {
            "baseline_run": baseline.get("run_label", "baseline"),
            "p95_latency_sec": {
                "before": b_lat.get("p95_latency_sec"),
                "after": p95_latency,
                "delta_pct": _delta(p95_latency, b_lat.get("p95_latency_sec")),
            },
            "avg_latency_sec": {
                "before": b_lat.get("avg_latency_sec"),
                "after": avg_latency,
                "delta_pct": _delta(avg_latency, b_lat.get("avg_latency_sec")),
            },
            "avg_cost_per_request_usd": {
                "before": b_cost.get("avg_cost_per_request_usd"),
                "after": avg_cost_per_request,
                "delta_pct": _delta(avg_cost_per_request, b_cost.get("avg_cost_per_request_usd")),
            },
            "total_cost_usd": {
                "before": b_cost.get("total_cost_usd"),
                "after": round(total_cost_usd, 6),
                "delta_pct": _delta(total_cost_usd, b_cost.get("total_cost_usd")),
            },
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
        "cost_metrics": cost_metrics,
        "before_after_comparison": before_after,
        "judge_human_alignment": {
            "human_labeled_cases": cases_with_human_label,
            "agreed_cases": agreed_with_human,
            "agreement_rate_pct": agreement_rate
        },
        "per_kind_metrics": per_kind_summary,
        "detailed_results": results
    }

    # ── Lưu snapshot làm baseline 'before' cho lần chạy sau (nếu chưa có) ──
    baseline_path = Path(__file__).resolve().parent / "reports" / "cost_latency_baseline.json"
    if not baseline_path.exists() and save_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump({
                "run_label": f"baseline_{input_file.stem}",
                "input_dataset": input_file.name,
                "latency_metrics": report["latency_metrics"],
                "cost_metrics": cost_metrics,
            }, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Đã lưu baseline before-metrics tại: {baseline_path}")

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
    print(f"Token (in/out/total)  : {total_input_tokens}/{total_output_tokens}/{total_input_tokens + total_output_tokens} "
          f"(source: {'API' if any(r.get('cost_source') == 'api_usage' for r in results) else 'ước lượng'})")
    print(f"Chi phí ước tính      : ${cost_metrics['total_cost_usd']} tổng | ${avg_cost_per_request} / request (avg)")
    if before_after:
        print("-" * 60)
        print("📈 So sánh Before/After (baseline vs run này):")
        for metric, label in [
            ("avg_latency_sec", "Avg Latency (s)"),
            ("p95_latency_sec", "P95 Latency (s)"),
            ("avg_cost_per_request_usd", "Cost/request ($)"),
        ]:
            m = before_after.get(metric, {})
            delta = m.get("delta_pct")
            arrow = "→" if delta is None else ("🔻" if delta < 0 else "🔺")
            delta_str = "N/A" if delta is None else f"{delta:+.1f}%"
            print(f"  {label:<20}: {m.get('before')} → {m.get('after')}  {arrow} {delta_str}")
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

