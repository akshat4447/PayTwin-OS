"""PIPE-001/002: webhook ingestion idempotency, DLQ, late/out-of-order, state machine."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from paytwin_api.models import CanonicalEventRow, DeadLetter, EventInbox, Payment
from paytwin_api.services.ingest import ingest_webhook

SECRET = "sim-secret-dev"
ORG, MER = "org1", "mer1"


def _seed(db):
    from paytwin_api.models import Merchant, Organization

    db.add(Organization(id=ORG, name="Nova Commerce"))
    db.add(Merchant(id=MER, organization_id=ORG, name="Nova Grocery", short_code="NG"))
    db.commit()


def _payload(ext: str, etype: str, ref: str, epoch: int, **extra) -> bytes:
    p = {"event": etype, "id": ext, "created_at": epoch,
         "data": {"payment_id": ref, "amount": 129900, "method": "upi_intent",
                  "issuer": "HDFC", "psp": "cashfree", "group_id": f"grp_{ref}",
                  **extra}}
    return json.dumps(p).encode()


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _send(db, body: bytes, sig: str | None = None, provider="simulator", merchant=MER):
    return ingest_webhook(db, provider, merchant, body, sig if sig is not None else _sig(body))


def _epoch(h, m=0):
    return int(datetime(2026, 8, 25, h, m, tzinfo=timezone.utc).timestamp())


class TestHappyPath:
    def test_created_then_failed(self, db):
        _seed(db)
        r1 = _send(db, _payload("evt_a1", "created", "pay_1", _epoch(10)))
        r2 = _send(db, _payload("evt_a2", "failed", "pay_1", _epoch(10, 1),
                                error_reason="issuer_decline"))
        assert (r1.status, r2.status) == (200, 200)
        p = db.query(Payment).one()
        assert p.status == "failed" and p.failure_class == "issuer_decline"
        assert db.query(CanonicalEventRow).count() == 2
        assert db.query(EventInbox).filter_by(status="processed").count() == 2

    def test_timeout_then_late_success_recovers_group(self, db):
        _seed(db)
        _send(db, _payload("evt_b1", "created", "pay_7", _epoch(9)))
        _send(db, _payload("evt_b2", "timeout", "pay_7", _epoch(9, 1)))
        r = _send(db, _payload("evt_b3", "success", "pay_7", _epoch(9, 4)))
        assert r.body["payment_status"] == "success"
        p = db.query(Payment).one()
        assert p.status == "success" and p.recovered is True and p.final_status_at is not None


class TestIdempotencyAndReplay:
    def test_duplicate_webhook_is_noop(self, db):
        _seed(db)
        body = _payload("evt_dup", "created", "pay_2", _epoch(10))
        r1 = _send(db, body)
        r2 = _send(db, body)  # exact same delivery twice (provider retry)
        assert r1.status == 200 and r2.status == 200 and r2.body["duplicate"] is True
        assert db.query(CanonicalEventRow).count() == 1

    def test_replay_after_processed_is_duplicate(self, db):
        _seed(db)
        _send(db, _payload("evt_rp", "created", "pay_3", _epoch(10)))
        r = _send(db, _payload("evt_rp", "created", "pay_3", _epoch(10)))
        assert r.body["duplicate"] is True
        inbox = db.query(EventInbox).filter_by(external_event_id="evt_rp").one()
        assert inbox.status == "duplicate"


class TestRejections:
    def test_bad_signature_401_and_dead_letter(self, db):
        _seed(db)
        r = _send(db, _payload("evt_s1", "created", "pay_4", _epoch(10)), sig="sha256=deadbeef")
        assert r.status == 401
        assert db.query(DeadLetter).filter_by(reason="bad_signature").count() == 1
        assert db.query(CanonicalEventRow).count() == 0

    def test_malformed_422_and_dead_letter(self, db):
        _seed(db)
        body = json.dumps({"event": "failed"}).encode()  # missing id/data
        r = _send(db, body)
        assert r.status == 422
        assert db.query(DeadLetter).filter_by(reason="malformed").count() == 1

    def test_unknown_merchant_404(self, db):
        _seed(db)
        r = _send(db, _payload("evt_u1", "created", "pay_5", _epoch(10)), merchant="mer_nope")
        assert r.status == 404


class TestOrdering:
    def test_late_failure_never_regresses_success(self, db):
        _seed(db)
        _send(db, _payload("evt_o1", "created", "pay_6", _epoch(10)))
        _send(db, _payload("evt_o2", "success", "pay_6", _epoch(10, 5)))
        r = _send(db, _payload("evt_o3", "failed", "pay_6", _epoch(10, 2),
                               error_reason="timeout"))
        assert r.body["late"] is True
        p = db.query(Payment).one()
        assert p.status == "success"  # forward-only by occurred_at
        assert db.query(CanonicalEventRow).filter_by(late=True).count() == 1

    def test_on_time_failure_after_created_applies(self, db):
        _seed(db)
        _send(db, _payload("evt_p1", "created", "pay_8", _epoch(11)))
        r = _send(db, _payload("evt_p2", "failed", "pay_8", _epoch(11, 2)))
        assert r.body["late"] is False
        assert db.query(Payment).one().status == "failed"
