import json
import time
from typing import Any, Dict, List


def _now_ms() -> int:
    return int(time.time() * 1000)


class SearchTracer:
    def __init__(self):
        self._steps: List[Dict[str, Any]] = []

    @property
    def steps(self) -> List[Dict[str, Any]]:
        return self._steps

    def time(self, action: str) -> tuple:
        return _now_ms(), action

    def end(self, start: tuple, status: str, detail: str):
        started_ms, action = start
        self._steps.append({
            "action": action,
            "status": status,
            "detail": detail,
            "duration_ms": _now_ms() - started_ms,
        })

    def add(self, action: str, status: str, detail: str, duration_ms: int = 0):
        self._steps.append({
            "action": action,
            "status": status,
            "detail": detail,
            "duration_ms": duration_ms,
        })

    def to_json(self) -> str:
        return json.dumps(self._steps, ensure_ascii=False)
