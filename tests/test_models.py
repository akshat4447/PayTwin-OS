"""FOUNDATION-003: schema, constraints, idempotency uniques, migration parity."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from paytwin_api.models import (
    ActionExecution,
    ApiKey,
    CanonicalEventRow,
    EventInbox,
    Incident,
    Merchant,
    Organization,
    Payment,
    Policy,
    Simulation,
)


def _org(db):
    o = Organization(id="org1", name="Nova Commerce")
    db.add(o)
    m = Merchant(id="mer1", organization_id="org1", name="Nova Grocery", short_code="NG")
    db.add(m)
    db.commit()
    return o, m


def _ts(h=10):
    return datetime(2026, 8, 25, h, 0, tzinfo=timezone.utc)


class TestSchema:
    def test_create_all_and_query(self, db):
        _org(db)
        assert db.query(Merchant).filter_by(organization_id="org1").count() == 1

    def test_inbox_idempotency_unique(self, db):
        _org(db)
        db.add(EventInbox(organization_id="org1", provider="simulator",
                          external_event_id="evt_1", payload={}))
        db.commit()
        db.add(EventInbox(organization_id="org1", provider="simulator",
                          external_event_id="evt_1", payload={}))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_canonical_unique_provider_ext(self, db):
        _org(db)
        kw = dict(organization_id="org1", merchant_id="mer1", type="payment.failed",
                  provider="simulator", external_event_id="evt_9", occurred_at=_ts(),
                  payment_ref="pay_1", amount_paise=100)
        db.add(CanonicalEventRow(**kw))
        db.commit()
        db.add(CanonicalEventRow(**kw))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_incident_human_id_unique_per_org(self, db):
        _org(db)
        db.add(Incident(organization_id="org1", merchant_id="mer1", human_id="INC-2481", title="x"))
        db.commit()
        db.add(Incident(organization_id="org1", merchant_id="mer1", human_id="INC-2481", title="y"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_execution_idempotency_key_unique(self, db):
        _org(db)
        db.add(ActionExecution(organization_id="org1", merchant_id="mer1", kind="retry_burst",
                               idempotency_key="abc123"))
        db.commit()
        db.add(ActionExecution(organization_id="org1", merchant_id="mer1", kind="retry_burst",
                               idempotency_key="abc123"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_simulation_reproducible_unique(self, db):
        _org(db)
        kw = dict(organization_id="org1", merchant_id="mer1", incident_id="inc1",
                  scenario="issuer_outage", seed=42, params={}, params_hash="h")
        db.add(Simulation(**kw))
        db.commit()
        db.add(Simulation(**kw))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_policy_version_unique(self, db):
        _org(db)
        db.add(Policy(organization_id="org1", merchant_id="mer1", human_id="RP-007",
                      name="Retry guard", version=1, rules={}))
        db.commit()
        db.add(Policy(organization_id="org1", merchant_id="mer1", human_id="RP-007",
                      name="Retry guard", version=1, rules={}))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_payment_unique_provider_ref(self, db):
        _org(db)
        kw = dict(organization_id="org1", merchant_id="mer1", group_id="g1", provider="simulator",
                  payment_ref="pay_1", amount_paise=100, occurred_at=_ts())
        db.add(Payment(**kw))
        db.commit()
        db.add(Payment(**kw))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_api_key_hash_unique(self, db):
        _org(db)
        db.add(ApiKey(organization_id="org1", key_prefix="ptw_abc", key_hash="h" * 64, role="org_admin"))
        db.commit()
        db.add(ApiKey(organization_id="org1", key_prefix="ptw_xyz", key_hash="h" * 64, role="ops_oncall"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
