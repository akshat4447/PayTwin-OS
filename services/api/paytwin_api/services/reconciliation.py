"""Read-only-safe financial repair and operational status helpers.

The worker's reconciliation pass deliberately has a narrow authority: settle a
previously recorded pending refund only after the local payment is captured, and
retire an expired webhook-secret grace reference.  It never fetches a provider,
creates fulfilment, or initiates money movement.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from paytwin_api.models import (CheckoutVerification, DeadLetter, Fulfilment,
                                Integration, Order, Outbox, Payment, Refund)
from paytwin_api.services.state_machine import reconcile_pending_refunds


def reconcile_financial_state(db: Session, organization_id: str | None = None) -> dict:
    """Perform the safe local repair sweep and return only aggregate counts."""
    now = datetime.now(timezone.utc)
    payments = db.query(Payment).filter(Payment.status.in_(("success", "refunded")))
    integrations = db.query(Integration)
    if organization_id:
        payments = payments.filter(Payment.organization_id == organization_id)
        integrations = integrations.filter(Integration.organization_id == organization_id)

    held_refunds = 0
    for payment in payments.order_by(Payment.updated_at.asc()).limit(1_000).all():
        held_refunds += reconcile_pending_refunds(db, payment, now)

    expired_refs = 0
    for integration in integrations.all():
        expires_at = integration.previous_secret_expires_at
        if expires_at is not None:
            expires_at = (expires_at.replace(tzinfo=timezone.utc)
                          if expires_at.tzinfo is None else expires_at)
            if expires_at < now:
                integration.previous_secret_ref = None
                integration.previous_secret_expires_at = None
                expired_refs += 1
        integration.last_healthcheck_at = now
    db.flush()
    return {"pending_refunds_examined": held_refunds,
            "expired_secret_references_retired": expired_refs,
            "mode": "local_reconciliation_only"}


def operational_status(db: Session, organization_id: str) -> dict:
    """Tenant-scoped operational summary with no customer/payment references."""
    pending_refunds = (db.query(Refund)
                       .filter(Refund.organization_id == organization_id,
                               Refund.status == "pending_reconciliation").count())
    undispatched = (db.query(Outbox)
                     .filter(Outbox.organization_id == organization_id,
                             Outbox.dispatched_at.is_(None)).count())
    dead_letters = (db.query(DeadLetter)
                    .filter(DeadLetter.organization_id == organization_id).count())
    razorpay_orders = (db.query(Order)
                       .filter(Order.organization_id == organization_id,
                               Order.provider == "razorpay", Order.status == "paid").all())
    unverified_orders = 0
    verified_unfulfilled = 0
    for order in razorpay_orders:
        verified = (db.query(CheckoutVerification)
                    .filter(CheckoutVerification.order_id == order.id,
                            CheckoutVerification.signature_valid.is_(True)).one_or_none())
        if verified is None:
            unverified_orders += 1
        elif (db.query(Fulfilment).filter(Fulfilment.order_id == order.id).one_or_none()
              is None):
            verified_unfulfilled += 1
    integrations = (db.query(Integration)
                    .filter(Integration.organization_id == organization_id).all())
    return {
        "mode": "sandbox-only",
        "outbox_undispatched": undispatched,
        "dead_letters": dead_letters,
        "pending_refunds": pending_refunds,
        "razorpay_paid_orders_unverified": unverified_orders,
        "verified_orders_unfulfilled": verified_unfulfilled,
        "integrations": [{"provider": row.provider, "merchant_id": row.merchant_id,
                          "test_mode": row.status == "test_mode",
                          "last_webhook_at": (row.last_webhook_at.isoformat()
                                              if row.last_webhook_at else None),
                          "last_healthcheck_at": (row.last_healthcheck_at.isoformat()
                                                  if row.last_healthcheck_at else None)}
                         for row in integrations],
    }
