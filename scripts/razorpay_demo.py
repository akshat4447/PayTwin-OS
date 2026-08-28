#!/usr/bin/env python3
"""Build the repeatable, sandbox-only Razorpay hackathon demo.

The script first builds the existing PayTwin flagship story (detection, RCA,
RaR, Twin, policy, action simulation, measurement and audit).  It then runs
six Razorpay-shaped, HMAC-signed webhook scenarios through the production
ingestion service.  It never calls Razorpay, never stores a secret, and never
enables real provider execution.
"""
from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]


def _markdown(report: dict) -> str:
    verdict = "READY" if report["passed"] else "BLOCKED"
    lines = [
        "# PayTwin × Razorpay — Test Mode Demo",
        "",
        "> **SANDBOX ONLY.** Synthetic Razorpay-shaped, HMAC-signed events run through "
        "PayTwin's real ingestion and payment-state paths. No network call or money movement occurs.",
        "",
        f"## Razorpay Test Mode verification: {verdict}",
        "",
    ]
    for check in report["checks"]:
        marker = "PASS" if check["passed"] else "BLOCK"
        lines.append(f"- **{marker}** — {check['title']}")
    lines.extend([
        "",
        "## Capability tour",
        "",
        "1. **Observe and detect:** seeded payment traffic includes a controlled issuer/UPI outage.",
        "2. **Diagnose and quantify:** PayTwin opens an incident, ranks the cohort root cause, "
        "and reports Revenue at Risk with an interval.",
        "3. **Simulate and govern:** the Digital Twin ranks safe responses; the versioned policy "
        "engine blocks or requires approval before the simulator executor acts.",
        "4. **Measure and explain:** control/treatment outcomes, hash-chained audit, and the "
        "evidence-grounded Commander remain available in the UI.",
        "5. **Assure Razorpay Test Mode:** duplicate, forged-signature, out-of-order, "
        "late-authorization, partial-refund, and failed-refund scenarios exercise the actual "
        "webhook pipeline.",
        "",
        "Open the UI after starting the API with the development risk-admin key printed by the demo.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    # Do not allow the demo command to accidentally turn on external actions.
    os.environ["PAYTWIN_ALLOW_REAL_EXECUTION"] = "false"
    os.environ.setdefault("PAYTWIN_ENV", "development")
    # 90 minutes gives the detector its two observation windows while keeping
    # the judge-facing demo comfortably fast.  The ordinary `make demo` keeps
    # its full three-hour historical default.
    os.environ.setdefault("PAYTWIN_DEMO_HOURS", "1.5")

    from paytwin_sim import demo

    print("1/2 Building the PayTwin intelligence demo…")
    demo.main()
    print("2/2 Running Razorpay Test Mode runtime verification…")
    db = demo.make_db()
    try:
        from paytwin_api.reliability.runtime import run_razorpay_runtime_checks

        report = run_razorpay_runtime_checks(db, "mgro")
        db.commit()
    finally:
        db.close()

    output = REPO / "RAZORPAY_TEST_MODE_DEMO.md"
    output.write_text(_markdown(report))
    print(output.read_text())
    print("UI: start `make razorpay-api`, then open http://localhost:8000/#key=<risk_admin key>")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
