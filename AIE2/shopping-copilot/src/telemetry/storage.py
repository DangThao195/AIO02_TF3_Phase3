import json
import pathlib
import datetime
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("telemetry.storage")


class JsonlTraceStore:
    def __init__(self, logs_dir: str = "logs/traces"):
        self._logs_dir = pathlib.Path(logs_dir)
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def _today_path(self) -> pathlib.Path:
        return self._logs_dir / f"{datetime.date.today().isoformat()}.jsonl"

    def save(self, trace: dict) -> None:
        line = json.dumps(trace, ensure_ascii=False)
        try:
            with open(self._today_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.warning("[TRACE STORE] Cannot write trace: %s", e)

    def get_by_request_id(self, request_id: str) -> list[dict]:
        traces = []
        for p in sorted(self._logs_dir.glob("*.jsonl")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        t = json.loads(line)
                        if t.get("request_id") == request_id:
                            traces.append(t)
            except OSError:
                continue
        return sorted(traces, key=lambda x: x.get("timestamp", ""))

    def get_by_trace_id(self, trace_id: str) -> Optional[dict]:
        for p in sorted(self._logs_dir.glob("*.jsonl")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        t = json.loads(line)
                        if t.get("trace_id") == trace_id:
                            return t
            except OSError:
                continue
        return None

    def aggregate(self, period_hours: int = 24) -> dict:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=period_hours)
        agg = defaultdict(lambda: {"calls": 0, "total_latency": 0, "total_cost": 0.0, "total_tokens": 0, "errors": 0, "fallbacks": 0})
        for p in sorted(self._logs_dir.glob("*.jsonl")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        t = json.loads(line)
                        ts_str = t.get("timestamp", "")
                        try:
                            ts = datetime.datetime.fromisoformat(ts_str)
                        except (ValueError, TypeError):
                            continue
                        if ts < cutoff:
                            continue
                        key = (t.get("model", "unknown"), t.get("surface", "unknown"), t.get("layer", "unknown"))
                        agg[key]["calls"] += 1
                        agg[key]["total_latency"] += t.get("latency_ms", 0)
                        agg[key]["total_cost"] += t.get("estimated_cost_usd", 0.0)
                        agg[key]["total_tokens"] += t.get("total_tokens", 0)
                        if t.get("outcome") == "error":
                            agg[key]["errors"] += 1
                        if t.get("outcome") == "fallback":
                            agg[key]["fallbacks"] += 1
            except OSError:
                continue
        result = {}
        for (model, surface, layer), stats in agg.items():
            result[f"{model}|{surface}|{layer}"] = {
                "model": model,
                "surface": surface,
                "layer": layer,
                "calls": stats["calls"],
                "avg_latency_ms": round(stats["total_latency"] / max(stats["calls"], 1), 2),
                "total_cost_usd": round(stats["total_cost"], 6),
                "total_tokens": stats["total_tokens"],
                "errors": stats["errors"],
                "fallbacks": stats["fallbacks"],
                "error_rate": round(stats["errors"] / max(stats["calls"], 1), 4),
            }
        return result
