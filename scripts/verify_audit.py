#!/usr/bin/env python3
"""Verify the per-org audit hash chain (make verify).

Usage: PAYTWIN_DATABASE_URL=sqlite:///./data/demo.db python scripts/verify_audit.py
Exits non-zero when the chain is broken or the tail checkpoint disagrees.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    from paytwin_api.db import make_engine, make_session_factory
    from paytwin_api.services.audit import verify_chain

    engine = make_engine()
    db = make_session_factory(engine)()
    try:
        orgs = [row[0] for row in db.execute(
            __import__("sqlalchemy").text(
                "SELECT DISTINCT organization_id FROM audit_records"))]
        if not orgs:
            print("no audit records found")
            return 0
        failures = 0
        for org in sorted(orgs):
            ok, bad = verify_chain(db, org)
            print(f"{org}: chain {'OK' if ok else 'BROKEN'}"
                  + ("" if ok else f" first_bad_seq={bad}"))
            failures += 0 if ok else 1
        return 1 if failures else 0
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())