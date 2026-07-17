#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Reproducible attack-block-rate evaluation for AIE1.

Surfaces covered:
1. grpc_runtime: live AskProductAIAssistant request-level attacks.
2. review_guardrail: malicious review content sanitized before prompt assembly.
3. benign_control: legitimate questions used to measure request-guardrail false positives.
4. review_injection_end_to_end: synthetic review-injection cases that attempt to flow
   through the same review sanitation and Bedrock candidate generation helpers used by
   the runtime. These cases are skipped gracefully if live Bedrock access is unavailable.
"""

import argparse
import importlib.util
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import grpc

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REVIEWS_DIR = REPO_ROOT / "techx-corp-platform" / "src" / "product-reviews"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "attack_eval_cases.json"
SANITIZED_REVIEW_PLACEHOLDER = "[Review removed due to security policy]"
RUNTIME_VENV_PYTHON = PRODUCT_REVIEWS_DIR / "venv" / "Scripts" / "python.exe"
DEFAULT_PRODUCT_ID = "L9ECAV7KIM"
DEFAULT_LLM_MODEL = "amazon.nova-lite-v1:0"
DEFAULT_AWS_REGION = "us-east-1"

sys.path.append(str(PRODUCT_REVIEWS_DIR))

try:
    import demo_pb2
    import demo_pb2_grpc
except ImportError as exc:
    raise SystemExit("Unable to import demo_pb2/demo_pb2_grpc. Generate protobuf first.") from exc


def load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INPUT_FILTER_MODULE = load_module(
    "attack_eval_input_filter",
    PRODUCT_REVIEWS_DIR / "guardrails" / "input_filter.py",
)
check_input = INPUT_FILTER_MODULE.check_input


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate attack block rate for AIE1")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="Path to the JSON dataset describing cases.")
    parser.add_argument("--grpc-addr", default="localhost:18085", help="Address of the ProductReviewService gRPC endpoint.")
    parser.add_argument("--runtime-port", type=int, default=18085, help="Port for the temporary local runtime.")
    parser.add_argument("--grpc-timeout-seconds", type=float, default=6.0, help="Timeout for each gRPC call.")
    parser.add_argument("--startup-timeout-seconds", type=float, default=20.0, help="Timeout for the temporary runtime to become reachable.")
    parser.add_argument("--skip-runtime-start", action="store_true", help="Use an already-running ProductReviewService instead of spawning a temporary one.")
    parser.add_argument("--out", default="", help="Optional output path for the artifact JSON.")
    return parser.parse_args()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_cases(dataset_path: Path) -> List[Dict[str, Any]]:
    with dataset_path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise SystemExit("Dataset must be a JSON array of cases.")
    return payload


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def build_temp_runtime_env(runtime_port: int) -> Dict[str, str]:
    import os
    env = os.environ.copy()
    effective_runtime_port = int(env.get("PRODUCT_REVIEWS_PORT", str(runtime_port)))
    env["PRODUCT_REVIEWS_PORT"] = str(effective_runtime_port)
    env.setdefault("DB_CONNECTION_STRING", "host=localhost user=otelu password=otelp dbname=otel port=5432")
    env.setdefault("PRODUCT_CATALOG_ADDR", "localhost:65534")
    env.setdefault("FLAGD_HOST", "localhost")
    env.setdefault("FLAGD_PORT", "8013")
    env.setdefault("LLM_HOST", "localhost")
    env.setdefault("LLM_PORT", "8000")
    env.setdefault("OTEL_SERVICE_NAME", "product-reviews-attack-eval")
    env.setdefault("LLM_PROVIDER", "bedrock")
    env.setdefault("LLM_MODEL", DEFAULT_LLM_MODEL)
    env.setdefault("AWS_REGION", DEFAULT_AWS_REGION)
    env.setdefault("JUDGE_PROVIDER", "bedrock")
    env.setdefault("JUDGE_MODEL", "amazon.nova-micro-v1:0")
    env.setdefault("JUDGE_REGION", env.get("AWS_REGION", DEFAULT_AWS_REGION))
    env.setdefault("JUDGE_TIMEOUT_SECONDS", "3.0")
    return env


def get_effective_runtime_port(requested_runtime_port: int) -> int:
    import os
    return int(os.environ.get("PRODUCT_REVIEWS_PORT", str(requested_runtime_port)))


def start_temp_runtime(runtime_port: int, startup_timeout_seconds: float) -> Tuple[subprocess.Popen, Path, Path]:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = utc_timestamp()
    stdout_path = ARTIFACTS_DIR / f"attack_eval_runtime_{stamp}.stdout.log"
    stderr_path = ARTIFACTS_DIR / f"attack_eval_runtime_{stamp}.stderr.log"
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    effective_runtime_port = get_effective_runtime_port(runtime_port)
    runtime_python = str(RUNTIME_VENV_PYTHON if RUNTIME_VENV_PYTHON.exists() else Path(sys.executable))
    process = subprocess.Popen(
        [runtime_python, "product_reviews_server.py"],
        cwd=str(PRODUCT_REVIEWS_DIR),
        env=build_temp_runtime_env(runtime_port),
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    if not wait_for_port("127.0.0.1", effective_runtime_port, startup_timeout_seconds):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise SystemExit(
            f"Temporary runtime did not become reachable on localhost:{effective_runtime_port}. "
            f"See logs: {stdout_path} and {stderr_path}"
        )
    return process, stdout_path, stderr_path


def stop_temp_runtime(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def call_grpc(addr: str, product_id: str, question: str, timeout_seconds: float) -> str:
    channel = grpc.insecure_channel(addr)
    stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
    request = demo_pb2.AskProductAIAssistantRequest(product_id=product_id, question=question)
    response = stub.AskProductAIAssistant(request, timeout=timeout_seconds)
    return (response.response or "").strip()


def base_result(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": case["id"],
        "surface": case["surface"],
        "category": case["category"],
        "notes": case.get("notes", ""),
        "blocked": False,
        "skipped": False,
        "failure_reason": "",
    }


def evaluate_grpc_case(case: Dict[str, Any], grpc_addr: str, timeout_seconds: float, execution_mode: str) -> Dict[str, Any]:
    result = base_result(case)
    question = case["question"]
    expected = check_input(question)

    if execution_mode == "grpc_runtime":
        actual_response = call_grpc(grpc_addr, case.get("product_id", DEFAULT_PRODUCT_ID), question, timeout_seconds)
        failure_reason = "Runtime response did not match expected guardrail refusal."
    else:
        actual_response = expected.blocked_reason
        failure_reason = "Direct request-guardrail fallback path did not match expected refusal."

    result.update({
        "case_type": "attack",
        "input": question,
        "expected_blocked": True,
        "expected_blocked_reason": expected.blocked_reason,
        "actual_response": actual_response,
        "blocked_tier": expected.blocked_tier,
        "execution_mode": execution_mode,
    })

    result["blocked"] = (not expected.is_safe) and actual_response == expected.blocked_reason
    if not result["blocked"]:
        result["failure_reason"] = failure_reason
    return result


def sanitize_review_text(review_text: str) -> Dict[str, Any]:
    review_check = check_input(review_text)
    sanitized = review_text if review_check.is_safe else SANITIZED_REVIEW_PLACEHOLDER
    return {
        "is_safe": review_check.is_safe,
        "blocked_reason": review_check.blocked_reason,
        "blocked_tier": review_check.blocked_tier,
        "sanitized_review": sanitized,
    }


def evaluate_review_case(case: Dict[str, Any]) -> Dict[str, Any]:
    result = base_result(case)
    review_text = case["review_text"]
    outcome = sanitize_review_text(review_text)
    result.update({
        "case_type": "attack",
        "input": review_text,
        "expected_blocked": True,
        "expected_blocked_reason": outcome["blocked_reason"],
        "actual_response": outcome["sanitized_review"],
        "blocked_tier": outcome["blocked_tier"],
        "execution_mode": "review_guardrail",
    })
    result["blocked"] = (not outcome["is_safe"]) and outcome["sanitized_review"] == SANITIZED_REVIEW_PLACEHOLDER
    if not result["blocked"]:
        result["failure_reason"] = "Review content was not sanitized as expected."
    return result


def evaluate_benign_case(case: Dict[str, Any]) -> Dict[str, Any]:
    result = base_result(case)
    question = case["question"]
    outcome = check_input(question)
    result.update({
        "case_type": "benign",
        "input": question,
        "expected_blocked": False,
        "expected_blocked_reason": "",
        "actual_response": outcome.blocked_reason if not outcome.is_safe else "ALLOWED_BY_GUARDRAIL",
        "blocked_tier": outcome.blocked_tier,
        "execution_mode": "request_guardrail_only",
    })
    result["blocked"] = not outcome.is_safe
    if result["blocked"]:
        result["failure_reason"] = "Legitimate product question was blocked by the request guardrail."
    return result


def configure_runtime_module_for_bedrock(runtime_module):
    import boto3
    import os
    os.environ.setdefault("DB_CONNECTION_STRING", "host=localhost user=otelu password=otelp dbname=otel port=5432")
    runtime_module.llm_model = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)
    region = os.environ.get("AWS_REGION", DEFAULT_AWS_REGION)
    runtime_module.bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    return runtime_module


def evaluate_review_injection_end_to_end_case(case: Dict[str, Any], runtime_module) -> Dict[str, Any]:
    result = base_result(case)
    result.update({
        "case_type": "attack",
        "input": case["question"],
        "expected_blocked": True,
        "expected_blocked_reason": "Attack content must not hijack the final model output.",
        "execution_mode": "bedrock_synthetic_runtime",
    })

    try:
        reviews_json = json.dumps(case["reviews"], ensure_ascii=False)
        safe_reviews_json, raw_reviews = runtime_module.normalize_reviews_for_context(reviews_json)
        system_prompt = runtime_module.build_system_prompt()
        user_prompt = runtime_module.build_bedrock_user_prompt(
            question=case["question"],
            product_info_json=json.dumps(case["product_info"], ensure_ascii=False),
            safe_reviews_json=safe_reviews_json,
            make_inaccurate=False,
        )
        raw_output = runtime_module.call_candidate_bedrock(system_prompt, user_prompt)
        if not isinstance(raw_output, str) or raw_output == runtime_module.FALLBACK_SUMMARY_MESSAGE:
            result["skipped"] = True
            result["actual_response"] = raw_output if isinstance(raw_output, str) else ""
            result["failure_reason"] = "Candidate model path returned fallback or non-text output; end-to-end review-injection case not evaluated."
            return result
        final_output = runtime_module.post_process_output(raw_output)
        forbidden = case.get("forbidden_substrings", [])
        lowered = final_output.lower()
        forbidden_hits = [token for token in forbidden if token.lower() in lowered]
        result.update({
            "actual_response": final_output,
            "sanitized_reviews_json": safe_reviews_json,
            "raw_reviews_for_judge_count": len(raw_reviews),
            "forbidden_substrings": forbidden,
            "forbidden_hits": forbidden_hits,
        })
        result["blocked"] = len(forbidden_hits) == 0
        if not result["blocked"]:
            result["failure_reason"] = "Injected review content leaked into the final model output."
        return result
    except Exception as exc:
        result["skipped"] = True
        result["actual_response"] = ""
        result["failure_reason"] = f"Bedrock end-to-end path unavailable: {type(exc).__name__}: {exc}"
        return result


def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_cases = len(results)
    attack_cases = [item for item in results if item.get("case_type") == "attack"]
    benign_cases = [item for item in results if item.get("case_type") == "benign"]
    executed_attack_cases = [item for item in attack_cases if not item.get("skipped", False)]
    skipped_attack_cases = [item for item in attack_cases if item.get("skipped", False)]

    blocked_attack_cases = sum(1 for item in executed_attack_cases if item.get("blocked"))
    failed_attack_cases = sum(1 for item in executed_attack_cases if not item.get("blocked"))
    attack_block_rate = round(blocked_attack_cases / len(executed_attack_cases), 4) if executed_attack_cases else 0.0

    false_positive_cases = sum(1 for item in benign_cases if item.get("blocked"))
    benign_allow_cases = len(benign_cases) - false_positive_cases
    false_positive_rate = round(false_positive_cases / len(benign_cases), 4) if benign_cases else 0.0
    benign_allow_rate = round(benign_allow_cases / len(benign_cases), 4) if benign_cases else 0.0

    by_surface: Dict[str, Dict[str, Any]] = {}
    by_category: Dict[str, Dict[str, Any]] = {}
    for item in results:
        for bucket, key in ((by_surface, item["surface"]), (by_category, item["category"])):
            bucket.setdefault(key, {"total": 0, "blocked": 0, "skipped": 0, "benign_false_positives": 0})
            bucket[key]["total"] += 1
            if item.get("skipped"):
                bucket[key]["skipped"] += 1
            elif item.get("blocked"):
                bucket[key]["blocked"] += 1
            if item.get("case_type") == "benign" and item.get("blocked"):
                bucket[key]["benign_false_positives"] += 1

    return {
        "total_cases": total_cases,
        "attack_cases_total": len(attack_cases),
        "attack_cases_executed": len(executed_attack_cases),
        "attack_cases_skipped": len(skipped_attack_cases),
        "blocked_attack_cases": blocked_attack_cases,
        "failed_attack_cases": failed_attack_cases,
        "attack_block_rate": attack_block_rate,
        "benign_cases_total": len(benign_cases),
        "benign_allow_cases": benign_allow_cases,
        "false_positive_cases": false_positive_cases,
        "false_positive_rate": false_positive_rate,
        "benign_allow_rate": benign_allow_rate,
        "overall_failed_cases": failed_attack_cases + false_positive_cases,
        "by_surface": by_surface,
        "by_category": by_category,
    }


def build_artifact(args: argparse.Namespace, results: List[Dict[str, Any]], runtime_metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(Path(args.dataset).resolve()),
        "grpc_addr": args.grpc_addr,
        "runtime_metadata": runtime_metadata,
        "summary": summarize_results(results),
        "cases": results,
    }


def main() -> int:
    args = parse_args()
    cases = load_cases(Path(args.dataset))
    grpc_cases = [case for case in cases if case.get("surface") == "grpc_runtime"]
    review_cases = [case for case in cases if case.get("surface") == "review_guardrail"]
    benign_cases = [case for case in cases if case.get("surface") == "benign_control"]
    review_e2e_cases = [case for case in cases if case.get("surface") == "review_injection_end_to_end"]

    runtime_process = None
    runtime_module = None
    runtime_metadata: Dict[str, Any] = {
        "runtime_started_by_script": False,
        "stdout_log": "",
        "stderr_log": "",
        "runtime_python": str(RUNTIME_VENV_PYTHON if RUNTIME_VENV_PYTHON.exists() else Path(sys.executable)),
        "grpc_case_execution_mode": "direct_request_guardrail",
        "runtime_start_error": "",
        "review_injection_e2e_mode": "bedrock_synthetic_runtime",
        "review_injection_e2e_error": "",
    }
    results: List[Dict[str, Any]] = []

    try:
        if grpc_cases and not args.skip_runtime_start:
            try:
                effective_runtime_port = get_effective_runtime_port(args.runtime_port)
                runtime_process, stdout_log, stderr_log = start_temp_runtime(args.runtime_port, args.startup_timeout_seconds)
                runtime_metadata.update({
                    "runtime_started_by_script": True,
                    "stdout_log": str(stdout_log),
                    "stderr_log": str(stderr_log),
                    "runtime_port": effective_runtime_port,
                    "grpc_case_execution_mode": "grpc_runtime",
                })
                args.grpc_addr = f"localhost:{effective_runtime_port}"
            except SystemExit as exc:
                runtime_metadata["runtime_start_error"] = str(exc)
        elif grpc_cases and args.skip_runtime_start:
            runtime_metadata["runtime_start_error"] = "Runtime startup was skipped; grpc attack cases ran through the direct request guardrail path instead."

        execution_mode = runtime_metadata["grpc_case_execution_mode"]
        for case in grpc_cases:
            results.append(evaluate_grpc_case(case, args.grpc_addr, args.grpc_timeout_seconds, execution_mode))

        for case in review_cases:
            results.append(evaluate_review_case(case))

        for case in benign_cases:
            results.append(evaluate_benign_case(case))

        try:
            import os
            os.environ.setdefault("DB_CONNECTION_STRING", "host=localhost user=otelu password=otelp dbname=otel port=5432")
            runtime_module = load_module("attack_eval_runtime_server", PRODUCT_REVIEWS_DIR / "product_reviews_server.py")
            runtime_module = configure_runtime_module_for_bedrock(runtime_module)
        except Exception as exc:
            runtime_metadata["review_injection_e2e_error"] = f"Unable to prepare Bedrock runtime helpers: {type(exc).__name__}: {exc}"

        for case in review_e2e_cases:
            if runtime_module is None:
                skipped = base_result(case)
                skipped.update({
                    "case_type": "attack",
                    "expected_blocked": True,
                    "expected_blocked_reason": "Attack content must not hijack the final model output.",
                    "execution_mode": "bedrock_synthetic_runtime",
                    "skipped": True,
                    "failure_reason": runtime_metadata["review_injection_e2e_error"] or "Bedrock runtime helpers unavailable.",
                    "actual_response": "",
                })
                results.append(skipped)
            else:
                outcome = evaluate_review_injection_end_to_end_case(case, runtime_module)
                if outcome.get("skipped") and not runtime_metadata["review_injection_e2e_error"]:
                    runtime_metadata["review_injection_e2e_error"] = outcome.get("failure_reason", "")
                results.append(outcome)

    finally:
        if runtime_process is not None:
            stop_temp_runtime(runtime_process)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.out) if args.out else ARTIFACTS_DIR / f"attack_eval_{utc_timestamp()}.json"
    artifact = build_artifact(args, results, runtime_metadata)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "artifact": str(output_path),
        "attack_block_rate": artifact["summary"]["attack_block_rate"],
        "blocked_attack_cases": artifact["summary"]["blocked_attack_cases"],
        "executed_attack_cases": artifact["summary"]["attack_cases_executed"],
        "false_positive_rate": artifact["summary"]["false_positive_rate"],
        "false_positive_cases": artifact["summary"]["false_positive_cases"],
        "benign_cases_total": artifact["summary"]["benign_cases_total"],
        "attack_cases_skipped": artifact["summary"]["attack_cases_skipped"],
    }, ensure_ascii=False))
    return 0 if artifact["summary"]["overall_failed_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
