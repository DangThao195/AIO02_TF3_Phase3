"""CLI cửa replay — MANDATE #15. Nhận scenario JSON từ NGOÀI, chấm, in report.

Dùng:
  python scripts/replay.py                        # chạy bộ scenario mẫu (scenarios/)
  python scripts/replay.py path/to/hidden.json    # chạy bộ ẩn của mentor
  python scripts/replay.py hidden.json --baseline-mttd 900   # so MTTD với mốc thủ công

Exit 0 = đạt tiêu chí ẩn (#15), 1 = trượt. Ghi report ra replay/report.md.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_engine.aiops.replay_harness import (  # noqa: E402
    load_scenarios,
    render_report,
    replay,
)

_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "scenarios"


async def main() -> int:
    baseline = None
    raw = sys.argv[1:]
    args = []
    i = 0
    while i < len(raw):
        if raw[i] == "--baseline-mttd":
            baseline = int(raw[i + 1]); i += 2; continue
        if raw[i].startswith("--"):
            i += 1; continue
        args.append(raw[i]); i += 1

    if args:
        scenarios = load_scenarios(args[0])
    else:
        # bộ mẫu: gộp mọi file .json trong scenarios/
        scenarios = []
        for f in sorted(_DEFAULT_DIR.glob("*.json")):
            scenarios.extend(load_scenarios(f))
        if not scenarios:
            print("Không có scenario. Truyền file JSON hoặc tạo scenarios/*.json")
            return 1

    results = [await replay(s) for s in scenarios]
    report = render_report(results, baseline_mttd_s=baseline)
    print(report)

    out = Path(__file__).resolve().parents[1] / "replay" / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\nreport -> {out}")

    passed = all(
        (r.masking_ok is not False) and (r.busy_ok is not False)
        and (r.recall >= 0.99 if r.detection else True)
        for r in results
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
