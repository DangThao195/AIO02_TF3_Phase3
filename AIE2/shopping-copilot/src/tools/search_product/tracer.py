import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class StepTrace:
    step_name: str
    duration_ms: float
    status: str
    details: str = ""


class SearchTracer:
    def __init__(self):
        self.traces: List[StepTrace] = []
        self._start_time = time.time()

    def time(self, step_name: str):
        return (step_name, time.time())

    def end(self, timer_tuple, status: str = "ok", details: str = ""):
        step_name, start = timer_tuple
        duration_ms = (time.time() - start) * 1000.0
        self.traces.append(StepTrace(
            step_name=step_name,
            duration_ms=round(duration_ms, 2),
            status=status,
            details=details,
        ))

    def summary(self) -> str:
        total_ms = (time.time() - self._start_time) * 1000.0
        lines = [f"[SEARCH TRACE] Total: {total_ms:.2f}ms"]
        for t in self.traces:
            lines.append(f"  - {t.step_name}: {t.duration_ms:.2f}ms [{t.status}] {t.details}")
        return "\n".join(lines)
