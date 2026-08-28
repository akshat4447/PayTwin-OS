"""Credential-free, Razorpay-shaped local Test Mode environment.

This module is deliberately a *local provider emulator*, not a claim that a
Razorpay account is connected.  It creates Razorpay-shaped orders, payments and
webhooks, signs them with the development webhook secret, and sends them through
the same verification/inbox/state-machine path as an external delivery.  The
public router labels every response with ``LOCAL_RAZORPAY_TEST`` so sample data
can never be mistaken for observed provider data.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.models import Integration, Merchant, Order, Payment
from paytwin_api.services.ingest import _secrets_for, ingest_webhook

PROVENANCE = "LOCAL_RAZORPAY_TEST"


class LocalProviderError(ValueError):
    """A safe 4xx error from the local provider boundary."""


@dataclass(frozen=True)
class LocalOrderResult:
    order: Order
    provider_order: dict


def _id(prefix: str) -> str:
    return f"{prefix}_test_{secrets.token_hex(12)}"


def _webhook_secret(db: Session, merchant_id: str) -> str:
    """Use the configured development reference when present, else local default."""
    integration = (db.query(Integration)
                   .filter(Integration.merchant_id == merchant_id,
                           Integration.provider == "razorpay")
                   .one_or_none())
    # ``_secrets_for`` owns the active/previous-secret policy. Local dispatch
    # must obey exactly the same rule as an inbound provider webhook.
    if integration is not None:
        merchant = db.query(Merchant).filter(Merchant.id == merchant_id).one()
        resolved = _secrets_for(db, "razorpay", merchant)
        if resolved:
            return resolved[0]
    return get_settings().webhook_secret_razorpay


def _order_payload(order: Order) -> dict:
    return {
        "id": order.order_ref,
        "entity": "order",
        "amount": order.amount_paise,
        "amount_paid": order.amount_paid_paise,
        "amount_due": max(0, order.amount_paise - order.amount_paid_paise),
        "currency": order.currency,
        "receipt": order.receipt,
        "status": order.status,
        "created_at": int(order.created_at.timestamp()),
        "environment": PROVENANCE,
    }


def create_order(db: Session, *, organization_id: str, merchant_id: str,
                 amount_paise: int, receipt: str | None,
                 currency: str = "INR") -> LocalOrderResult:
    """Create a local Razorpay-compatible order without credentials or network IO."""
    if amount_paise < 100:
        raise LocalProviderError("amount must be at least 100 paise")
    if currency != "INR":
        raise LocalProviderError("the local Razorpay environment currently supports INR only")
    clean_receipt = (receipt or f"ptw-{secrets.token_hex(8)}").strip()
    if len(clean_receipt) > 80:
        raise LocalProviderError("receipt must be 80 characters or fewer")
    existing = (db.query(Order)
                .filter(Order.organization_id == organization_id,
                        Order.merchant_id == merchant_id,
                        Order.provider == "razorpay", Order.receipt == clean_receipt)
                .one_or_none())
    if existing is not None:
        if existing.amount_paise != amount_paise:
            raise LocalProviderError("receipt is already used with a different amount")
        return LocalOrderResult(existing, _order_payload(existing))
    order = Order(
        organization_id=organization_id, merchant_id=merchant_id,
        provider="razorpay", order_ref=_id("order"), receipt=clean_receipt,
        amount_paise=amount_paise, currency=currency, status="created",
    )
    db.add(order)
    db.flush()
    return LocalOrderResult(order, _order_payload(order))


def _payment_payload(*, order: Order, payment_ref: str, outcome: str,
                     method: str, bank: str | None, vpa: str | None,
                     failure_reason: str | None) -> tuple[dict, dict]:
    now = int(time.time())
    payment = {
        "id": payment_ref,
        "entity": "payment",
        "amount": order.amount_paise,
        "currency": order.currency,
        "status": "captured" if outcome == "captured" else outcome,
        "order_id": order.order_ref,
        "method": method,
        "bank": bank,
        "vpa": vpa,
        "created_at": now,
    }
    if outcome == "failed":
        payment.update({
            "error_source": "bank",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": failure_reason or "issuer_declined",
            "error_description": failure_reason or "issuer declined the payment",
        })
    event = {"captured": "payment.captured", "failed": "payment.failed",
             "authorized": "payment.authorized"}[outcome]
    return {"event": event, "payload": {"payment": {"entity": payment}}}, payment


def simulate_payment(db: Session, *, merchant_id: str, order_ref: str,
                     outcome: str, method: str = "upi", bank: str | None = "HDFC",
                     vpa: str | None = "local@upi",
                     failure_reason: str | None = None) -> dict:
    """Emit a signed local Razorpay payment webhook through normal ingestion."""
    if outcome not in {"captured", "failed", "authorized"}:
        raise LocalProviderError("outcome must be captured, failed, or authorized")
    order = (db.query(Order)
             .filter(Order.merchant_id == merchant_id, Order.provider == "razorpay",
                     Order.order_ref == order_ref).one_or_none())
    if order is None:
        raise LocalProviderError("order not found")
    if order.status == "paid":
        raise LocalProviderError("order is already paid; create a new order for another attempt")
    payment_ref = _id("pay")
    payload, payment = _payment_payload(
        order=order, payment_ref=payment_ref, outcome=outcome, method=method,
        bank=bank, vpa=vpa if method == "upi" else None, failure_reason=failure_reason,
    )
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(_webhook_secret(db, merchant_id).encode(), raw,
                         hashlib.sha256).hexdigest()
    event_id = _id("evt")
    result = ingest_webhook(db, "razorpay", merchant_id, raw, signature,
                            headers={"x-razorpay-event-id": event_id})
    if result.status != 200:
        raise RuntimeError(f"local provider webhook was rejected: {result.body}")
    checkout_signature = hmac.new(
        get_settings().razorpay_key_secret.encode(),
        f"{order.order_ref}|{payment_ref}".encode(), hashlib.sha256,
    ).hexdigest()
    return {
        "provenance": PROVENANCE,
        "webhook": {"event_id": event_id, "accepted": True,
                    "result": result.body},
        "payment": payment,
        "checkout_callback": ({
            "razorpay_order_id": order.order_ref,
            "razorpay_payment_id": payment_ref,
            "razorpay_signature": checkout_signature,
        } if outcome == "captured" else None),
    }


def simulate_refund(db: Session, *, merchant_id: str, payment_ref: str,
                    amount_paise: int, receipt: str | None = None) -> dict:
    """Emit a processed Razorpay-shaped refund callback for a captured payment."""
    payment = (db.query(Payment)
               .filter(Payment.merchant_id == merchant_id, Payment.provider == "razorpay",
                       Payment.payment_ref == payment_ref).one_or_none())
    if payment is None:
        raise LocalProviderError("payment not found")
    if payment.status not in {"success", "refunded"}:
        raise LocalProviderError("only captured local payments can be refunded")
    remaining = payment.amount_paise - payment.refunded_amount_paise
    if amount_paise < 1 or amount_paise > remaining:
        raise LocalProviderError("refund amount must be between 1 and the unrefunded amount")
    refund_ref = _id("rfnd")
    now = int(time.time())
    payload = {
        "event": "refund.processed",
        "payload": {
            "payment": {"entity": {"id": payment.payment_ref,
                                       "amount": payment.amount_paise,
                                       "order_id": payment.order_ref,
                                       "created_at": now}},
            "refund": {"entity": {"id": refund_ref, "payment_id": payment.payment_ref,
                                      "amount": amount_paise, "status": "processed",
                                      "receipt": receipt, "created_at": now}},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(_webhook_secret(db, merchant_id).encode(), raw,
                         hashlib.sha256).hexdigest()
    result = ingest_webhook(db, "razorpay", merchant_id, raw, signature,
                            headers={"x-razorpay-event-id": _id("evt")})
    if result.status != 200:
        raise RuntimeError(f"local provider refund webhook was rejected: {result.body}")
    return {"provenance": PROVENANCE, "refund_id": refund_ref,
            "result": result.body}


def local_downtime(db: Session, *, organization_id: str, merchant_id: str | None) -> dict:
    """Derive a transparent local health view from recorded local test attempts."""
    q = db.query(Payment).filter(Payment.organization_id == organization_id,
                                 Payment.provider == "razorpay")
    if merchant_id:
        q = q.filter(Payment.merchant_id == merchant_id)
    rows = q.order_by(Payment.occurred_at.desc()).limit(200).all()
    total = len(rows)
    failed = sum(row.status == "failed" for row in rows)
    rate = failed / total if total else 0.0
    return {
        "provenance": PROVENANCE,
        "source": "locally recorded Razorpay-shaped payment events",
        "observed_attempts": total,
        "failed_attempts": failed,
        "failure_rate": round(rate, 4),
        "status": "degraded" if total >= 5 and rate >= 0.25 else "healthy",
        "not_provider_downtime_feed": True,
    }
