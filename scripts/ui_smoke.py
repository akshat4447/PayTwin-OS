#!/usr/bin/env python3
"""UI smoke test (headless Chrome): all routes render + release self-test hook.

Run: python scripts/ui_smoke.py
Exit 1 on any failure. Used by the ci ui-smoke job; needs Chrome installed.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "apps" / "web" / "index.html"
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
)
ROUTES = ["overview", "cohort", "warroom", "twinlab", "policies", "commander",
          "experiments", "modelhealth", "audit", "integrations", "merchants",
          "funnel", "bench", "reliability"]


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if pathlib.Path(c).exists():
            return c
    print("Chrome not found"); sys.exit(2)


def load(binary: str, url: str, budget: int = 6000) -> tuple[str, str]:
    p = subprocess.run(
        [binary, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--no-first-run", "--mute-audio",
         "--enable-logging=stderr", "--v=0", f"--virtual-time-budget={budget}",
         "--window-size=1440,960", "--dump-dom", url],
        capture_output=True, text=True, timeout=60)
    return p.stdout, p.stderr


def main() -> int:
    binary = chrome()
    failures: list[str] = []

    # 1) every route renders the shell with zero console errors
    for route in ROUTES:
        dom, err = load(binary, f"file://{SRC}#{route}")
        problems = []
        if 'class="app"' not in dom:
            problems.append("no shell")
        if 'class="page"' not in dom and "<article" not in dom:
            problems.append("no page article")
        for line in err.splitlines():
            if "CONSOLE" in line and re.search(r'"(ERROR|error)|Uncaught', line):
                problems.append(line.strip()[:180])
        print(("OK  " if not problems else "FAIL") + f" #{route}"
              + ("" if not problems else "  -> " + " | ".join(problems[:2])))
        if problems:
            failures.append(route)

    # 2) release self-test hook (regression flows)
    dom, _ = load(binary, f"file://{SRC}?selftest=1#reliability", budget=9000)
    m = re.search(r'<pre id="ptds-selftest-out"[^>]*>(.*?)</pre>', dom, re.S)
    if not m:
        failures.append("selftest: no output block rendered")
        print("FAIL selftest: output block missing")
    else:
        for line in m.group(1).strip().splitlines():
            print("SELFTEST " + line.strip())
            if line.startswith("FAIL"):
                failures.append("selftest:" + line.split()[1])
            elif not line.startswith("PASS"):
                failures.append("selftest-unparsed:" + line[:60])

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'ALL SMOKE CHECKS PASSED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
