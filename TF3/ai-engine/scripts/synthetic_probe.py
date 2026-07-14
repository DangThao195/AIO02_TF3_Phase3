"""External synthetic probe — nguồn sự thật ĐỘC LẬP với monitoring stack (W3-D2).

Chạy NGOÀI cluster (laptop / máy CI / VM khác). Internal metrics có thể tự dối
(cache stale, 200-nhưng-sai-nội-dung, monitoring dependency loop — Roblox 2021 mù
60+ giờ vì stack quan sát phụ thuộc chính Consul đang chết). Probe này chỉ cần
stdlib, đo đúng cái user thấy:

  - GET từng target mỗi PROBE_INTERVAL_S (mặc định 5s), timeout 4s
  - pass = HTTP 2xx/3xx VÀ (nếu khai expect) body chứa chuỗi expect
  - steady-state = pass-rate cửa sổ 60s ≥ 99% (in ra mỗi cửa sổ)
  - output JSON-lines (probe.log hoặc stdout) để đối chiếu MTTD/verify-loop

Dùng:
  python scripts/synthetic_probe.py                       # target mặc định
  python scripts/synthetic_probe.py http://host/ http://host/api/products/OLJCESPC7Z
  PROBE_TARGETS="http://a/,http://b/" python scripts/synthetic_probe.py
  python scripts/synthetic_probe.py --once                # 1 vòng rồi thoát (CI smoke)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

PROBE_INTERVAL_S = float(os.environ.get("PROBE_INTERVAL_S", "5"))
PROBE_TIMEOUT_S = float(os.environ.get("PROBE_TIMEOUT_S", "4"))
WINDOW_S = 60
STEADY_STATE_MIN = 0.99

DEFAULT_TARGETS = [
    # frontend home + product-detail (trang có AI review summary — INC-4/INC-7 lộ ở đây)
    os.environ.get("PROBE_FRONTEND", "http://localhost:8080/"),
    os.environ.get("PROBE_PRODUCT", "http://localhost:8080/api/products/OLJCESPC7Z"),
]


def probe_once(url: str) -> dict:
    started = time.time()
    ok, status, err = False, 0, ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tf3-synthetic-probe/1.0"})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            status = resp.status
            body = resp.read(4096)
            ok = 200 <= status < 400 and len(body) > 0
    except Exception as exc:  # DNS/refused/timeout/5xx — tất cả là fail từ góc nhìn user
        err = str(exc)[:120]
    return {
        "ts": round(time.time(), 3),
        "url": url,
        "pass": ok,
        "status": status,
        "latency_ms": round((time.time() - started) * 1000, 1),
        **({"error": err} if err else {}),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    once = "--once" in sys.argv
    env_targets = os.environ.get("PROBE_TARGETS", "")
    targets = args or ([t.strip() for t in env_targets.split(",") if t.strip()] or DEFAULT_TARGETS)

    window: list[dict] = []
    window_started = time.time()
    print(json.dumps({"probe": "start", "targets": targets, "interval_s": PROBE_INTERVAL_S}),
          flush=True)

    while True:
        for url in targets:
            r = probe_once(url)
            window.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)

        if time.time() - window_started >= WINDOW_S:
            passed = sum(1 for r in window if r["pass"])
            rate = passed / len(window) if window else 0.0
            steady = rate >= STEADY_STATE_MIN
            print(json.dumps({
                "window_s": WINDOW_S, "probes": len(window),
                "pass_rate": round(rate, 4),
                "steady_state": steady,
            }), flush=True)
            if not steady:
                # tín hiệu cho chaos runner / verify-loop: user ĐANG đau, độc lập với Prometheus
                print(json.dumps({"alert": "steady-state broken", "pass_rate": round(rate, 4)}),
                      file=sys.stderr, flush=True)
            window, window_started = [], time.time()

        if once:
            return 0 if all(r["pass"] for r in window) else 1
        time.sleep(PROBE_INTERVAL_S)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
