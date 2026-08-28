"""Credential-free Razorpay-compatible Test Mode lifecycle regression tests."""
from __future__ import annotations

from paytwin_api.auth import Principal
from paytwin_api.models import Merchant, Organization
from paytwin_api.routers.checkout import FulfilBody, RazorpayVerifyBody, fulfil_razorpay, verify_razorpay
from paytwin_api.routers.razorpay import (
    CreateOrderBody, RefundBody, SimulatePaymentBody, create_local_order,
    simulate_local_payment, simulate_local_refund,
)
from paytwin_api.services.ingest import accept_webhook, process_pending_inbox
from paytwin_api.services.razorpay_local import PROVENANCE


def _seed(db):
    db.add(Organization(id="org_local", name="Local Test"))
    db.add(Merchant(id="mer_local", organization_id="org_local", name="Local Merchant",
                    short_code="LT"))
    db.commit()


def _principal():
    return Principal(organization_id="org_local", role="risk_admin", key_prefix="ptw_local",
                     user_id="local-operator")


def test_local_razorpay_order_payment_checkout_fulfilment_and_refund(db):
    _seed(db)
    p = _principal()
    created = create_local_order(CreateOrderBody(merchant_id="mer_local", amount_paise=12_500,
                                                 receipt="local-order-1"), p, db)
    assert created["provenance"] == PROVENANCE
    order_id = created["order"]["id"]

    payment = simulate_local_payment(SimulatePaymentBody(merchant_id="mer_local",
                                                           order_id=order_id), p, db)
    assert payment["webhook"]["result"]["payment_status"] == "success"
    callback = payment["checkout_callback"]
    verified = verify_razorpay(RazorpayVerifyBody(merchant_id="mer_local",
                                                   **callback), p, db)
    assert verified["ok"] is True
    fulfilled = fulfil_razorpay(FulfilBody(merchant_id="mer_local",
                                           razorpay_payment_id=callback["razorpay_payment_id"],
                                           idempotency_key="local-fulfilment-1"), p, db)
    assert fulfilled["ok"] is True
    refunded = simulate_local_refund(RefundBody(
        merchant_id="mer_local", payment_id=callback["razorpay_payment_id"],
        amount_paise=2_500, receipt="local-refund-1"), p, db)
    assert refunded["provenance"] == PROVENANCE


def test_accepted_webhook_is_durable_then_worker_materializes(db):
    _seed(db)
    # The simulator signing details are exercised extensively elsewhere. This
    # check uses its public service contract to prove the 202 -> worker split.
    import hashlib
    import hmac
    import json
    from paytwin_api.config import get_settings
    from paytwin_api.models import EventInbox, Payment

    payload = {"event": "created", "id": "evt_durable_1", "created_at": 1_756_500_000,
               "data": {"payment_id": "pay_durable_1", "amount": 100,
                        "method": "upi_intent", "issuer": "HDFC", "psp": "cashfree"}}
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(get_settings().webhook_secret_simulator.encode(), raw,
                                      hashlib.sha256).hexdigest()
    accepted = accept_webhook(db, "simulator", "mer_local", raw, signature)
    assert accepted.status == 202
    assert db.query(Payment).count() == 0
    inbox = db.query(EventInbox).one()
    assert inbox.status == "received" and inbox.canonical_payload["payment_ref"] == "pay_durable_1"
    assert process_pending_inbox(db)["processed"] == 1
    assert db.query(Payment).filter_by(payment_ref="pay_durable_1").one().status == "created"
