"""
rebuild_topology_from_jaeger.py
================================
Tự động xây dựng lại file services.json (topology đồ thị phụ thuộc microservices)
bằng cách khai thác dữ liệu Jaeger traces thực tế từ cụm EKS.

Thuật toán:
  1. Lấy danh sách tất cả services đang active từ Jaeger API
  2. Với mỗi service, lấy N traces gần nhất
  3. Với mỗi trace, duyệt các spans:
     - Nếu span A là CHILD_OF span B → service(A) được gọi bởi service(B)
     → Thêm edge: service(B) → service(A)  (B là caller, A là callee/dependency)
  4. Gom tất cả edges → loại bỏ self-loop và service infra noise
  5. Merge với services.json hiện tại (giữ nguyên cạnh tĩnh không có trong trace)
  6. Ghi ra services.json

Chạy:
  cd aiops-engine
  python scripts/rebuild_topology_from_jaeger.py

  # Dry run (không ghi file, chỉ in kết quả):
  python scripts/rebuild_topology_from_jaeger.py --dry-run

  # Chỉ dùng traces của 1 service:
  python scripts/rebuild_topology_from_jaeger.py --service checkout

  # Tăng số traces lấy (mặc định 50):
  python scripts/rebuild_topology_from_jaeger.py --limit 200
"""

import os
import sys
import json
import argparse
import logging
import requests
from collections import defaultdict
from datetime import datetime

# Thêm thư mục gốc vào path để import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import JAEGER_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("TopologyBuilder")

# Service infra/sidecar không cần xuất hiện trong topology application
EXCLUDE_SERVICES = {
    "jaeger", "jaeger-query", "jaeger-collector",
    "prometheus", "grafana", "otel-collector",
    "envoy", "istio-proxy", "linkerd-proxy",
    "unknown", ""
}

# Đường dẫn mặc định của services.json
SERVICES_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services.json"
)


def get_all_services(jaeger_url: str) -> list[str]:
    """Lấy danh sách tất cả services đang có traces trong Jaeger."""
    try:
        resp = requests.get(f"{jaeger_url}/api/services", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            services = data.get("data", [])
            # Lọc bỏ infra services
            filtered = [s for s in services if s not in EXCLUDE_SERVICES and s.strip()]
            logger.info(f"Found {len(filtered)} application services in Jaeger: {filtered}")
            return filtered
    except Exception as e:
        logger.error(f"Failed to get services from Jaeger: {e}")
    return []


def get_traces_for_service(jaeger_url: str, service: str, limit: int = 50) -> list[dict]:
    """Lấy N traces gần nhất của một service từ Jaeger."""
    try:
        params = {
            "service": service,
            "limit": limit,
            # Lấy traces trong 7 ngày gần nhất để có đủ coverage
            "lookback": "168h"
        }
        resp = requests.get(f"{jaeger_url}/api/traces", params=params, timeout=15)
        if resp.status_code == 200:
            traces = resp.json().get("data", [])
            logger.debug(f"  Fetched {len(traces)} traces for {service}")
            return traces
    except Exception as e:
        logger.warning(f"  Failed to fetch traces for {service}: {e}")
    return []


def extract_edges_from_trace(trace: dict) -> set[tuple[str, str]]:
    """
    Trích xuất các cạnh phụ thuộc từ một Jaeger trace.

    Format Jaeger: span có "references": [{"refType": "CHILD_OF", "spanID": "parent_id"}]
    Nghĩa là: span hiện tại là con của parent_span
    → service(parent_span) → service(current_span)

    Returns:
        Set of (caller_service, callee_service) tuples
    """
    spans = trace.get("spans", [])
    processes = trace.get("processes", {})

    # Map spanID → service name
    span_to_service: dict[str, str] = {}
    for span in spans:
        sid = span.get("spanID", "")
        pid = span.get("processID", "")
        svc = processes.get(pid, {}).get("serviceName", "").strip()
        if sid and svc:
            span_to_service[sid] = svc

    edges: set[tuple[str, str]] = set()

    for span in spans:
        sid = span.get("spanID", "")
        callee_svc = span_to_service.get(sid, "")

        if not callee_svc or callee_svc in EXCLUDE_SERVICES:
            continue

        for ref in span.get("references", []):
            if ref.get("refType") == "CHILD_OF":
                parent_sid = ref.get("spanID", "")
                caller_svc = span_to_service.get(parent_sid, "")

                if not caller_svc or caller_svc in EXCLUDE_SERVICES:
                    continue
                if caller_svc == callee_svc:
                    continue  # bỏ self-loop

                edges.add((caller_svc, callee_svc))

    return edges


def build_topology_from_jaeger(
    jaeger_url: str,
    target_services: list[str] | None = None,
    limit_per_service: int = 50
) -> dict[str, list[str]]:
    """
    Xây dựng topology đầy đủ từ Jaeger.

    Args:
        jaeger_url: URL của Jaeger Query API
        target_services: Chỉ lấy traces của các services này (None = lấy tất cả)
        limit_per_service: Số traces lấy cho mỗi service

    Returns:
        dict {caller_service: [callee_service, ...]}
    """
    # Lấy danh sách services
    all_services = target_services or get_all_services(jaeger_url)
    if not all_services:
        logger.error("No services found. Check Jaeger connection.")
        return {}

    # Tổng hợp edges từ tất cả traces
    all_edges: set[tuple[str, str]] = set()
    edge_count_map: dict[tuple[str, str], int] = defaultdict(int)

    for service in all_services:
        logger.info(f"Processing traces for: {service}")
        traces = get_traces_for_service(jaeger_url, service, limit=limit_per_service)

        for trace in traces:
            edges = extract_edges_from_trace(trace)
            for edge in edges:
                all_edges.add(edge)
                edge_count_map[edge] += 1

    logger.info(f"\nTotal unique edges discovered: {len(all_edges)}")

    # Chuyển set edges → dict topology
    topology: dict[str, set[str]] = defaultdict(set)
    for caller, callee in all_edges:
        topology[caller].add(callee)

    # Convert sets to sorted lists
    result = {svc: sorted(deps) for svc, deps in sorted(topology.items())}

    return result


def merge_with_existing(
    discovered: dict[str, list[str]],
    existing_path: str
) -> dict[str, list[str]]:
    """
    Merge topology mới phát hiện với services.json hiện tại.
    Giữ nguyên các cạnh tĩnh không xuất hiện trong traces (ví dụ: infra connections).
    """
    existing: dict[str, list[str]] = {}
    if os.path.exists(existing_path):
        try:
            with open(existing_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            logger.info(f"Loaded existing topology: {len(existing)} services")
        except Exception as e:
            logger.warning(f"Could not load existing topology: {e}")

    merged: dict[str, set[str]] = defaultdict(set)

    # Thêm tất cả cạnh từ discovered
    for svc, deps in discovered.items():
        for dep in deps:
            merged[svc].add(dep)

    # Thêm cạnh từ existing mà discovered không có
    # (giữ nguyên các khai báo tĩnh đã biết)
    new_from_existing = 0
    for svc, deps in existing.items():
        for dep in deps:
            if dep not in merged.get(svc, set()):
                merged[svc].add(dep)
                new_from_existing += 1

    if new_from_existing > 0:
        logger.info(f"Kept {new_from_existing} edges from existing topology not seen in traces")

    return {svc: sorted(deps) for svc, deps in sorted(merged.items())}


def print_diff(old: dict, new: dict):
    """In ra sự khác biệt giữa topology cũ và mới."""
    old_edges = {(svc, dep) for svc, deps in old.items() for dep in deps}
    new_edges = {(svc, dep) for svc, deps in new.items() for dep in deps}

    added = new_edges - old_edges
    removed = old_edges - new_edges

    if added:
        logger.info(f"\n✅ EDGES ADDED ({len(added)}):")
        for caller, callee in sorted(added):
            logger.info(f"   + {caller} → {callee}")

    if removed:
        logger.info(f"\n⚠️  EDGES REMOVED ({len(removed)}) — kept because merge strategy:")
        for caller, callee in sorted(removed):
            logger.info(f"   - {caller} → {callee}")

    if not added and not removed:
        logger.info("\n✓ No changes detected — topology is up to date")


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild services.json topology from Jaeger traces"
    )
    parser.add_argument(
        "--jaeger-url",
        default=JAEGER_URL,
        help=f"Jaeger Query API URL (default: {JAEGER_URL})"
    )
    parser.add_argument(
        "--service",
        nargs="+",
        help="Only process traces from these services (default: all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of traces to fetch per service (default: 50)"
    )
    parser.add_argument(
        "--output",
        default=SERVICES_JSON_PATH,
        help=f"Output path for services.json (default: {SERVICES_JSON_PATH})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print discovered topology without writing to file"
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Replace existing topology entirely (do not merge)"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("TOPOLOGY BUILDER — Jaeger Trace Analysis")
    logger.info(f"Jaeger URL : {args.jaeger_url}")
    logger.info(f"Services   : {args.service or 'ALL'}")
    logger.info(f"Limit      : {args.limit} traces/service")
    logger.info(f"Output     : {args.output}")
    logger.info(f"Dry run    : {args.dry_run}")
    logger.info("=" * 60)

    # 1. Build từ Jaeger
    discovered = build_topology_from_jaeger(
        jaeger_url=args.jaeger_url,
        target_services=args.service,
        limit_per_service=args.limit
    )

    if not discovered:
        logger.warning("No topology discovered from Jaeger. Keeping existing file unchanged.")
        return

    # 2. Merge hoặc replace
    if args.no_merge:
        final_topology = {svc: sorted(deps) for svc, deps in sorted(discovered.items())}
        logger.info("Using discovered topology only (--no-merge)")
    else:
        final_topology = merge_with_existing(discovered, args.output)

    # 3. In diff
    existing_topology: dict = {}
    if os.path.exists(args.output):
        try:
            with open(args.output) as f:
                existing_topology = json.load(f)
        except Exception:
            pass
    print_diff(existing_topology, final_topology)

    # 4. Print kết quả
    logger.info("\n📊 Final Topology:")
    for svc, deps in final_topology.items():
        logger.info(f"  {svc:25s} → {deps}")

    # 5. Ghi file (nếu không phải dry run)
    if args.dry_run:
        logger.info("\n[DRY RUN] Would write to: %s", args.output)
        logger.info(json.dumps(final_topology, indent=2, ensure_ascii=False))
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        content = json.dumps(final_topology, indent=2, ensure_ascii=False)

        # Ghi local
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"\n✅ Topology written to: {args.output}")

        # Upload lên S3 để tất cả Pod đều dùng cùng version (không bị mất khi Pod restart)
        _upload_to_s3(content, args.output)

        logger.info(
            f"   {sum(len(v) for v in final_topology.values())} edges, "
            f"{len(final_topology)} source services"
        )
        logger.info(f"   Timestamp: {datetime.now().isoformat()}")


def _upload_to_s3(content: str, local_path: str):
    """
    Upload services.json lên S3 bucket (cùng bucket với models).
    Key: topology/services.json

    Khi Pod restart, AlertCorrelator sẽ load từ S3 trước → luôn có topology mới nhất
    dù image cũ vẫn có services.json cũ baked in.
    """
    try:
        import boto3
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import S3_BUCKET_NAME

        if not os.getenv("AWS_ACCESS_KEY_ID"):
            logger.info("No AWS credentials — skipping S3 upload.")
            return

        s3 = boto3.client("s3")
        s3_key = "topology/services.json"

        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
            Metadata={
                "source": "rebuild_topology_from_jaeger",
                "local_path": local_path,
                "rebuilt_at": datetime.now().isoformat()
            }
        )
        logger.info(f"✅ Uploaded topology to s3://{S3_BUCKET_NAME}/{s3_key}")
    except Exception as e:
        logger.warning(f"S3 upload failed (topology still saved locally): {e}")


if __name__ == "__main__":
    main()
