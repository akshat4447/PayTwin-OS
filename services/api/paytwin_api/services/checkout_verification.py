"""Server-side Razorpay Standard Checkout signature verification.

The browser callback is *not* proof of payment.  This service validates the
``razorpay_order_id|razorpay_payment_id`` HMAC using a server-only environment
reference, then requires the local payment materialization to be captured for
that exact merchant order.  It records concise verification evidence without
persisting the signature secret.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from paytwin_api.models import CheckoutVerification, Integration, Order, Payment
from paytwin_api.config import get_settings


@dataclass(frozen=True)
class CheckoutResult:
    ok: bool
    code: str
    message: str
    verification_id: str | None = None


def _checkout_secret(db: Session, merchant_id: str) -> str:
    integration = (db.query(Integration)
                   .filter(Integration.merchant_id == merchant_id,
                           Integration.provider == "razorpay")
                   .one_or_none())
    ref = integration.api_secret_ref if integration is not None else None
    # This fallback is intentionally distinct from the webhook secret.  It
    # supports a local Test Mode demo without letting webhook configuration
    # accidentally become a Checkout signing key.
    configured = os.environ.get(ref or "PAYTWIN_RAZORPAY_KEY_SECRET", "")
    # A credential-free local Test Mode includes a development-only Checkout
    # key so the full browser-proof path can be exercised. Production startup
    # rejects this default and never reaches this fallback.
    return configured or (get_settings().razorpay_key_secret
                          if not get_settings().is_prod else "")


def _record(db: Session, *, order: Order, payment: Payment | None,
            payment_ref: str, valid: bool, code: str) -> CheckoutVerification:
    row = (db.query(CheckoutVerification)
           .filter(CheckoutVerification.merchant_id == order.merchant_id,
                   CheckoutVerification.provider == "razorpay",
                   CheckoutVerification.payment_ref == payment_ref)
           .one_or_none())
    now = datetime.now(timezone.utc)
    if row is None:
        row = CheckoutVerification(
            organization_id=order.organization_id, merchant_id=order.merchant_id,
            order_id=order.id, payment_id=payment.id if payment else None,
            provider="razorpay", payment_ref=payment_ref,
            signature_valid=valid, status="verified" if valid else "rejected",
            reason=None if valid else code, verified_at=now,
        )
        db.add(row)
        db.flush()
        return row

    # A valid proof is immutable.  A later malicious/accidental bad callback
    # must never downgrade an already verified transaction.
    if valid and not row.signature_valid:
        row.payment_id = payment.id if payment else row.payment_id
        row.signature_valid = True
        row.status = "verified"
        row.reason = None
        row.verified_at = now
    return row


def verify_razorpay_checkout(db: Session, *, organization_id: str,
                             merchant_id: str, order_ref: str,
                             payment_ref: str, signature: str) -> CheckoutResult:
    """Verify one Checkout callback against tenant-local order/payment state."""
    order = (db.query(Order)
             .filter(Order.organization_id == organization_id,
                     Order.merchant_id == merchant_id,
                     Order.provider == "razorpay", Order.order_ref == order_ref)
             .one_or_none())
    if order is None:
        return CheckoutResult(False, "unknown_order", "order is not known for this merchant")

    secret = _checkout_secret(db, merchant_id)
    if not secret:
        return CheckoutResult(False, "checkout_secret_not_configured",
                              "Razorpay Checkout API-secret reference is not configured")
    expected = hmac.new(secret.encode(), f"{order_ref}|{payment_ref}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        row = _record(db, order=order, payment=None, payment_ref=payment_ref,
                      valid=False, code="invalid_signature")
        return CheckoutResult(False, "invalid_signature", "Checkout signature is invalid", row.id)

    payment = (db.query(Payment)
               .filter(Payment.organization_id == organization_id,
                       Payment.merchant_id == merchant_id,
                       Payment.provider == "razorpay", Payment.payment_ref == payment_ref)
               .one_or_none())
    if payment is None or payment.order_ref != order_ref:
        row = _record(db, order=order, payment=payment, payment_ref=payment_ref,
                      valid=False, code="payment_order_mismatch")
        return CheckoutResult(False, "payment_order_mismatch",
                              "payment does not belong to the supplied order", row.id)
    if payment.status != "success" or order.status != "paid":
        row = _record(db, order=order, payment=payment, payment_ref=payment_ref,
                      valid=False, code="payment_not_captured")
        return CheckoutResult(False, "payment_not_captured",
                              "payment is not captured and payable", row.id)
    if order.amount_paise and payment.amount_paise != order.amount_paise:
        row = _record(db, order=order, payment=payment, payment_ref=payment_ref,
                      valid=False, code="payment_amount_mismatch")
        return CheckoutResult(False, "payment_amount_mismatch",
                              "captured payment amount does not match the order", row.id)

    row = _record(db, order=order, payment=payment, payment_ref=payment_ref,
                  valid=True, code="verified")
    return CheckoutResult(True, "verified", "signature and captured payment verified", row.id)
