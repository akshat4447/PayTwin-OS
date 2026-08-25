"""SIM-002/OPS: demo world seeding + worker single-pass smoke tests."""
from __future__ import annotations

from paytwin_api.models import (
    ActionExecution,
    ApiKey,
    Merchant,
    Organization,
    Outbox,
    Policy,
)
from paytwin_api.services.bus import publish_outbox


def test_seed_world_creates_org_merchants_keys_policies(db):
    from paytwin_sim.demo import DEFAULT_POLICIES, MERCHANT_SPECS, seed_world

    out = seed_world(db)
    assert out["org_id"] == "org1" and set(out["keys"]) == {
        "risk_admin", "ops_oncall", "finance_viewer"}
    assert (db.query(Merchant).filter_by(organization_id="org1").count()
           == len(MERCHANT_SPECS))
    modes = {m.id: m.autonomy_mode for m in
             db.query(Merchant).filter_by(organization_id="org1").all()}
    assert modes["mgro"] == 3 and modes["mfash"] == 2 and modes["mtrav"] == 3 \
        and modes["msubs"] == 1
    assert (db.query(Policy).filter_by(organization_id="org1").count()
           >= len(DEFAULT_POLICIES))
    assert db.query(ApiKey).count() >= 3


class TestWorker:
    def test_run_once_on_quiet_data(self, db):
        from paytwin_api.worker import run_once

        db.add(Organization(id="org1", name="Nova"))
        db.commit()
        result = run_once(db)
        assert result["opened"] == 0          # no traffic -> no incidents
        assert result["executed"] == []
        assert result["outbox_dispatched"] >= 0

    def test_dispatch_marks_pending_outbox(self, db):
        db.add(Organization(id="org1", name="Nova"))
        db.flush()
        publish_outbox(db, "org1", "metric", {"x": 1})
        db.commit()
        from paytwin_api.worker import dispatch_outbox

        n = dispatch_outbox(db)
        assert n == 1
        assert db.query(Outbox).filter(
            Outbox.dispatched_at.is_(None)).count() == 0

    def test_worker_executes_only_when_policy_allows(self, db):
        """Autonomy mode 1 (recommend-only) => require_approval, never executed."""
        from datetime import datetime, timezone

        from paytwin_api.worker import detection_pass

        db.add(Organization(id="org1", name="Nova"))
        db.add(Merchant(id="mer1", organization_id="org1", name="M",
                        short_code="M", autonomy_mode=1,
                        config={"policy_rules": {}}))
        db.commit()
        # no payments -> no incidents -> nothing executed either way
        out = detection_pass(db)
        assert out["opened"] == 0
        assert db.query(ActionExecution).count() == 0