"""Bedrock Knowledge Base retrieval cho RCA — RAG grounding từ INCIDENT_HISTORY.md.

Hạ tầng KB provision bằng TF3/terraform (S3 → Titan v2 → OpenSearch Serverless). Module
này là phía đọc: lấy top-K đoạn playbook lịch sử giống sự cố hiện tại để đưa vào Evidence
Pack + prompt LLM diagnostician. Chấm điểm liên quan theo heuristic W2-D2:

  +0.4 nếu service root-cause của sự cố lịch sử nằm trong cluster hiện tại
  +0.2 mỗi service trùng (tối đa +0.4)
  +0.2 nếu trùng severity
  chỉ giữ đoạn có điểm ≥ 0.2

Fail-graceful (C3): KB chậm/chết → TelemetryError, caller đánh dấu evidence incomplete,
pack vẫn ship — local_matcher vẫn là fallback offline cuối cùng.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

from ..common.telemetry import TelemetryError
from .correlator import DEPENDENCY_MAP

log = logging.getLogger("ai_engine.kb_retriever")

INCLUDE_THRESHOLD = 0.2

# Mọi service TF3 biết đến (node + leaf của dependency map) — dùng để nhận diện
# service được nhắc trong một đoạn playbook.
_KNOWN_SERVICES: frozenset[str] = frozenset(
    set(DEPENDENCY_MAP) | {s for deps in DEPENDENCY_MAP.values() for s in deps}
)

# Root-cause của đoạn lịch sử = target của lệnh khắc phục (deploy/<svc>, deployment/<svc>).
_ROOT_RE = re.compile(r"deploy(?:ment)?/([a-z][a-z0-9-]*)")

_SEVERITY_WORDS = {
    "critical": ("vỡ slo", "mất tính năng", "lỗi thanh toán", "mất giỏ", "treo trang"),
    "warning": ("chậm", "latency", "lag", "memory pressure", "cold start"),
}


def score_kb_chunk(text: str, *, cluster_services: set[str], severity: str) -> float:
    """Heuristic W2-D2 trên một đoạn playbook thô (markdown INC-x). Deterministic,
    không LLM — chấm xong mới quyết đưa vào prompt hay không."""
    low = text.lower()
    score = 0.0

    m = _ROOT_RE.search(low)
    root = m.group(1) if m else ""
    if root and root in cluster_services:
        score += 0.4

    mentioned = {s for s in _KNOWN_SERVICES if s in low}
    overlap = len(mentioned & cluster_services)
    score += min(0.2 * overlap, 0.4)

    sev_markers = _SEVERITY_WORDS.get(severity.lower(), ())
    if any(w in low for w in sev_markers):
        score += 0.2

    return round(score, 2)


class BedrockKBRetriever:
    """Đọc bedrock-agent-runtime `retrieve`. KNOWLEDGE_BASE_ID lấy từ env (output của
    `terraform output -raw knowledge_base_id`). boto3 import lười + chạy trong thread
    để không chặn event loop; mọi lỗi → TelemetryError (caller fail-graceful)."""

    def __init__(self, kb_id: str | None = None, region: str | None = None, timeout_s: float = 10.0):
        self._kb_id = kb_id or os.environ.get("KNOWLEDGE_BASE_ID", "")
        self._region = region or os.environ.get("AWS_BEDROCK_REGION", "us-east-1")
        self._timeout_s = timeout_s
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self._kb_id)

    def _get_client(self):
        if self._client is None:
            import boto3  # lười: engine chạy được không cần boto3 khi KB tắt

            self._client = boto3.client("bedrock-agent-runtime", region_name=self._region)
        return self._client

    async def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        """Trả về [{'text': ..., 'score': <kb similarity>}, ...]. Không bao giờ trả None."""
        if not self.configured:
            return []
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: self._get_client().retrieve(
                        knowledgeBaseId=self._kb_id,
                        retrievalQuery={"text": query[:1000]},
                        retrievalConfiguration={
                            "vectorSearchConfiguration": {"numberOfResults": top_k}
                        },
                    )
                ),
                timeout=self._timeout_s,
            )
        except Exception as exc:  # boto/network/timeout — một đường fail duy nhất
            raise TelemetryError(f"bedrock kb retrieve failed: {exc}") from exc

        out = []
        for r in resp.get("retrievalResults", []):
            out.append({
                "text": r.get("content", {}).get("text", ""),
                "score": r.get("score", 0.0),
            })
        return out


async def retrieve_scored(
    retriever,
    *,
    query: str,
    cluster_services: set[str],
    severity: str,
    top_k: int = 3,
) -> list[tuple[float, str]]:
    """Retrieve + chấm heuristic + lọc ngưỡng. Trả [(score, text), ...] giảm dần.
    `retriever` chỉ cần có async .retrieve(query, top_k) — test được bằng fake."""
    chunks = await retriever.retrieve(query, top_k=top_k)
    scored = [
        (score_kb_chunk(c["text"], cluster_services=cluster_services, severity=severity), c["text"])
        for c in chunks
        if c.get("text")
    ]
    kept = sorted((s for s in scored if s[0] >= INCLUDE_THRESHOLD), key=lambda x: -x[0])
    if len(kept) < len(scored):
        log.info("kb: dropped %d/%d chunks below %.1f threshold",
                 len(scored) - len(kept), len(scored), INCLUDE_THRESHOLD)
    return kept
