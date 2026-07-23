"""CLI eval AI — MANDATE #14/#06. Nhận bộ ca JSON từ NGOÀI, chấm, in report ra số.

Dùng:
  python scripts/eval_ai.py                    # bộ ca mẫu (evalsets/)
  python scripts/eval_ai.py hidden-cases.json  # bộ ẩn của mentor

Exit 0 = qua bar cứng + bộ ẩn (unanswerable/injection), 1 = trượt. Ghi evals/report.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_engine.aie.eval_harness import evaluate, load_cases, render_report  # noqa: E402

_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "evalsets"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        cases = load_cases(args[0])
    else:
        cases = []
        for f in sorted(_DEFAULT_DIR.glob("*.json")):
            cases.extend(load_cases(f))
        if not cases:
            print("Không có ca eval. Truyền file JSON hoặc tạo evalsets/*.json")
            return 1

    rep = evaluate(cases)
    report = render_report(rep)
    print(report)

    out = Path(__file__).resolve().parents[1] / "evals" / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\nreport -> {out}")

    unans = all(r.passed for r in rep.results if r.kind == "unanswerable")
    inj = all(r.passed for r in rep.results if r.kind in ("injection-review", "injection-multiturn"))
    return 0 if (rep.hard_bar_ok and unans and inj) else 1


if __name__ == "__main__":
    raise SystemExit(main())
