"""Worker entrypoint: detection cycle -> policy-gated autopilot -> outbox dispatch.

Run: python -m paytwin_api.worker   (honours PAYTWIN_DATABASE_URL; loops every
PAYTWIN_WORKER_INTERVAL seconds, default 30; Ctrl-C exits cleanly).

Safety: the worker only auto-executes when the merchant's autonomy ladder and the
deterministic policy engine ALLOW it — the same executor path the API uses.
"""
from __future__ import annotations

import os
import time

INTERVAL = int(os.environ.get("PAYTWIN_WORKER_INTERVAL", "30"))


def _db():
    from paytwin_api.db import make_engine, make_session_factory

    engine = make_engine()
    return make_session_factory(engine)()


def dispatch_outbox(db) -> int:
    """Mark pending outbox rows dispatched (fan-out already happened on publish)."""
    from datetime import datetime, timezone

    from paytwin_api.models import Outbox

    rows = (db.query(Outbox)
            .filter(Outbox.dispatched_at.is_(None))
            .order_by(Outbox.created_at.asc()).limit(200).all())
    now = datetime.now(timezone.utc)
    for r in rows:
        r.dispatched_at = now
    if rows:
        db.commit()
    return len(rows)


def detection_pass(db, org_id: str = "org1") -> dict:
    """One sweep per merchant; auto-execute best candidate when policy allows."""
    from paytwin_api.models import ActionCandidate, Merchant
    from paytwin_api.services import executor, incident_service

    opened = incident_service.run_detection_cycle(db, org_id)
    executed = []
    for inc in opened:
        merchant = db.query(Merchant).filter_by(id=inc.merchant_id).one()
        cand = (db.query(ActionCandidate).filter_by(incident_id=inc.id)
                .order_by(ActionCandidate.rank).first())
        if cand is None:
            continue
        ex, res = executor.request_execution(
            db, None, merchant, cand, actor="worker-autopilot")
        executed.append({"incident": inc.human_id, "kind": cand.kind,
                         "decision": res.decision if res else "duplicate",
                         "state": ex.state})
    db.commit()
    return {"opened": len(opened), "executed": executed}


def run_once(db) -> dict:
    result = detection_pass(db)
    result["outbox_dispatched"] = dispatch_outbox(db)
    return result


def main() -> None:
    print(f"[worker] starting · interval {INTERVAL}s · org1")
    while True:
        try:
            db = _db()
            result = run_once(db)
            db.close()
            print(f"[worker] {result}")
        except KeyboardInterrupt:
            print("[worker] shutting down")
            break
        except Exception as e:  # keep the loop alive; log and retry next tick
            print(f"[worker] tick failed: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()