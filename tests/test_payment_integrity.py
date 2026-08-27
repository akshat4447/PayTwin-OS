"""Regression coverage for merchant payment correctness (Phase 1)."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from paytwin_contracts import CanonicalEvent

from paytwin_api.connectors import get_connector
from paytwin_api.models import (CheckoutVerification, Fulfilment, Integration,
                                Merchant, Order, Organization, Payment, Refund)
from paytwin_api.services.checkout_verification import verify_razorpay_checkout
from paytwin_api.services.ingest import ingest_webhook
from paytwin_api.services.state_machine import apply_event, record_fulfilment

ORG, MER = "org_integrity", "mer_integrity"
T0 = datetime(2026, 8, 27, 10, tzinfo=timezone.utc)


def _seed(db):
    db.add(Organization(id=ORG, name="Integrity Org"))
    db.add(Merchant(id=MER, organization_id=ORG, name="Integrity Merchant", short_code="IM"))
    db.commit()


def _event(event_type: str, event_id: str, *, payment_ref: str = "pay_1",
           amount: int = 10_000, minute: int = 0, provider: str = "razorpay",
           order_ref: str = "order_1", payload: dict | None = None) -> CanonicalEvent:
    return CanonicalEvent(
        type=event_type, organization_id=ORG, merchant_id=MER, provider=provider,
        external_event_id=event_id, occurred_at=T0 + timedelta(minutes=minute),
        payment_ref=payment_ref, amount_paise=amount,
        payload={"order_ref": order_ref, **(payload or {})},
    )


def test_razorpay_refund_uses_refund_entity_amount_not_payment_amount():
    connector = get_connector("razorpay")
    payload = {
        "event": "refund.processed",
        "payload": {
            "payment": {"entity": {"id": "pay_R1", "amount": 10_000,
                                     "order_id": "order_R1", "created_at": 1_756_500_000}},
            "refund": {"entity": {"id": "rfnd_R1", "payment_id": "pay_R1",
                                    "amount": 2_500, "status": "processed",
                                    "created_at": 1_756_500_100}},
        },
    }
    event = connector.normalize(payload, ORG, MER, headers={"x-razorpay-event-id": "evt_ref_1"})
    assert event.type == "refund.created"
    assert event.payment_ref == "pay_R1"
    assert event.amount_paise == 2_500
    assert event.payload["payment_amount_paise"] == 10_000
    assert event.payload["refund_ref"] == "rfnd_R1"


def test_partial_full_duplicate_and_over_refund_are_financially_safe(db):
    _seed(db)
    payment = apply_event(db, _event("payment.success", "evt_capture"))
    partial = _event("refund.created", "evt_refund_partial", amount=2_500, minute=1,
                     payload={"refund_ref": "rfnd_partial", "refund_amount_paise": 2_500,
                              "refund_status": "processed", "payment_amount_paise": 10_000})
    payment = apply_event(db, partial)
    assert (payment.status, payment.refunded_amount_paise) == ("success", 2_500)
    # State processing is idempotent even if a caller replays an already-normalized event.
    payment = apply_event(db, partial)
    assert payment.refunded_amount_paise == 2_500

    over = _event("refund.created", "evt_refund_over", amount=8_000, minute=2,
                  payload={"refund_ref": "rfnd_over", "refund_amount_paise": 8_000,
                           "refund_status": "processed", "payment_amount_paise": 10_000})
    payment = apply_event(db, over)
    assert payment.refunded_amount_paise == 2_500
    assert db.query(Refund).filter_by(refund_ref="rfnd_over").one().status == "rejected"

    final = _event("refund.created", "evt_refund_final", amount=7_500, minute=3,
                   payload={"refund_ref": "rfnd_final", "refund_amount_paise": 7_500,
                            "refund_status": "processed", "payment_amount_paise": 10_000})
    payment = apply_event(db, final)
    assert (payment.status, payment.refunded_amount_paise) == ("refunded", 10_000)


def test_refund_before_capture_is_held_then_settled(db):
    _seed(db)
    refund = _event("refund.created", "evt_early_refund", amount=10_000,
                    payload={"refund_ref": "rfnd_early", "refund_amount_paise": 10_000,
                             "refund_status": "processed", "payment_amount_paise": 10_000})
    payment = apply_event(db, refund)
    assert payment.status == "created"
    assert db.query(Refund).one().status == "pending_reconciliation"

    payment = apply_event(db, _event("payment.success", "evt_late_capture", minute=1))
    assert (payment.status, payment.refunded_amount_paise) == ("refunded", 10_000)
    assert db.query(Refund).one().status == "processed"


def test_only_one_fulfilment_for_multiple_payment_attempts_on_one_order(db):
    _seed(db)
    p1 = apply_event(db, _event("payment.success", "evt_attempt_1", payment_ref="pay_a"))
    p2 = apply_event(db, _event("payment.success", "evt_attempt_2", payment_ref="pay_b", minute=1))
    first = record_fulfilment(db, p1, source="checkout", idempotency_key="fulfil-order-1")
    repeat = record_fulfilment(db, p2, source="checkout", idempotency_key="other-key")
    assert repeat.id == first.id
    assert db.query(Fulfilment).count() == 1
    assert db.query(Order).one().status == "paid"


def test_checkout_requires_valid_signature_captured_payment_and_exact_order(db, monkeypatch):
    _seed(db)
    secret_name, secret = "PTW_RAZORPAY_CHECKOUT_TEST_SECRET", "checkout-secret"
    monkeypatch.setenv(secret_name, secret)
    db.add(Integration(organization_id=ORG, merchant_id=MER, provider="razorpay",
                       api_secret_ref=secret_name, status="test_mode"))
    payment = apply_event(db, _event("payment.success", "evt_checkout_capture",
                                     payment_ref="pay_checkout", amount=4_200,
                                     order_ref="order_checkout"))
    assert payment.status == "success"
    signature = hmac.new(secret.encode(), b"order_checkout|pay_checkout", hashlib.sha256).hexdigest()

    bad = verify_razorpay_checkout(
        db, organization_id=ORG, merchant_id=MER, order_ref="order_checkout",
        payment_ref="pay_checkout", signature="not-a-real-signature")
    assert bad.ok is False and bad.code == "invalid_signature"
    good = verify_razorpay_checkout(
        db, organization_id=ORG, merchant_id=MER, order_ref="order_checkout",
        payment_ref="pay_checkout", signature=signature)
    assert good.ok is True
    evidence = db.query(CheckoutVerification).one()
    assert evidence.signature_valid is True and evidence.status == "verified"

    mismatch = verify_razorpay_checkout(
        db, organization_id=ORG, merchant_id=MER, order_ref="order_checkout",
        payment_ref="pay_other", signature=hmac.new(
            secret.encode(), b"order_checkout|pay_other", hashlib.sha256).hexdigest())
    assert mismatch.ok is False and mismatch.code == "payment_order_mismatch"


def test_webhook_secret_rotation_accepts_only_explicit_grace_window(db, monkeypatch):
    _seed(db)
    old_ref, new_ref = "PTW_RZP_OLD", "PTW_RZP_NEW"
    old_secret, new_secret = "old-webhook-secret", "new-webhook-secret"
    monkeypatch.setenv(old_ref, old_secret)
    monkeypatch.setenv(new_ref, new_secret)
    integration = Integration(organization_id=ORG, merchant_id=MER, provider="razorpay",
                              secret_ref=new_ref, previous_secret_ref=old_ref,
                              previous_secret_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(integration)
    db.commit()

    def body(event_id: str, payment_ref: str) -> bytes:
        return json.dumps({"event": "payment.authorized", "payload": {"payment": {"entity": {
            "id": payment_ref, "amount": 100, "created_at": 1_756_500_000,
        }}}}).encode()

    old_body = body("evt_rotation_old", "pay_rotation_old")
    old_sig = hmac.new(old_secret.encode(), old_body, hashlib.sha256).hexdigest()
    assert ingest_webhook(db, "razorpay", MER, old_body, old_sig,
                          headers={"x-razorpay-event-id": "evt_rotation_old"}).status == 200
    new_body = body("evt_rotation_new", "pay_rotation_new")
    new_sig = hmac.new(new_secret.encode(), new_body, hashlib.sha256).hexdigest()
    assert ingest_webhook(db, "razorpay", MER, new_body, new_sig,
                          headers={"x-razorpay-event-id": "evt_rotation_new"}).status == 200

    integration.previous_secret_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    expired_body = body("evt_rotation_expired", "pay_rotation_expired")
    expired_sig = hmac.new(old_secret.encode(), expired_body, hashlib.sha256).hexdigest()
    assert ingest_webhook(db, "razorpay", MER, expired_body, expired_sig,
                          headers={"x-razorpay-event-id": "evt_rotation_expired"}).status == 401
