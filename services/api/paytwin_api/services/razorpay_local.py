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
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.models import Integration, Merchant, Order, Payment, PaymentLink
from paytwin_api.services.ingest import _secrets_for, ingest_webhook

PROVENANCE = "LOCAL_RAZORPAY_TEST"


class LocalProviderError(ValueError):
    """A safe 4xx error from the local provider boundary."""


@dataclass(frozen=True)
class LocalOrderResult:
    order: Order
    provider_order: dict


@dataclass(frozen=True)
class LocalPaymentLinkResult:
    link: PaymentLink
    order: Order
    provider_link: dict


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


def _link_payload(link: PaymentLink, order: Order) -> dict:
    """Return the useful Razorpay-shaped subset without retaining PII."""
    notify = {"email": link.channel == "email", "sms": link.channel == "sms",
              "whatsapp": link.channel == "whatsapp"}
    return {
        "id": link.link_ref,
        "entity": "payment_link",
        "amount": link.amount_paise,
        "amount_paid": link.amount_paid_paise,
        "currency": link.currency,
        "reference_id": link.reference_id,
        "notes": {"paytwin_group_id": link.payment_group_id} if link.payment_group_id else {},
        "status": link.status,
        "short_url": f"https://rzp.local/{link.link_ref}",
        "order_id": order.order_ref,
        "notify": notify,
        "reminder_enable": link.reminder_enabled,
        "expire_by": int(link.expires_at.timestamp()) if link.expires_at else 0,
        "created_at": int(link.created_at.timestamp()),
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


def create_payment_link(
    db: Session, *, organization_id: str, merchant_id: str, amount_paise: int,
    reference_id: str | None, payment_group_id: str | None = None,
    action_execution_id: str | None = None, channel: str = "whatsapp",
    reminder_enabled: bool = False, expires_after_min: int = 30,
) -> LocalPaymentLinkResult:
    """Issue a bounded local Payment Link and retain a recovery attribution key."""
    if channel not in {"whatsapp", "sms", "email"}:
        raise LocalProviderError("channel must be whatsapp, sms, or email")
    if not 5 <= int(expires_after_min) <= 1_440:
        raise LocalProviderError("expires_after_min must be between 5 and 1440")
    reference = (reference_id or f"recovery-{secrets.token_hex(8)}").strip()
    if not reference or len(reference) > 80:
        raise LocalProviderError("reference_id must contain 1 to 80 characters")
    existing = (db.query(PaymentLink)
                .filter(PaymentLink.organization_id == organization_id,
                        PaymentLink.merchant_id == merchant_id,
                        PaymentLink.reference_id == reference).one_or_none())
    if existing is not None:
        order = db.query(Order).filter(Order.id == existing.order_id).one()
        if existing.amount_paise != amount_paise:
            raise LocalProviderError("reference_id is already used with a different amount")
        return LocalPaymentLinkResult(existing, order, _link_payload(existing, order))
    receipt = f"plink-{reference}"[:80]
    order_result = create_order(
        db, organization_id=organization_id, merchant_id=merchant_id,
        amount_paise=amount_paise, receipt=receipt,
    )
    link = PaymentLink(
        organization_id=organization_id, merchant_id=merchant_id, provider="razorpay",
        link_ref=_id("plink"), reference_id=reference, order_id=order_result.order.id,
        action_execution_id=action_execution_id, payment_group_id=payment_group_id,
        amount_paise=amount_paise, currency=order_result.order.currency,
        channel=channel, reminder_enabled=bool(reminder_enabled),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=int(expires_after_min)),
        status="issued",
    )
    db.add(link)
    db.flush()
    return LocalPaymentLinkResult(link, order_result.order, _link_payload(link, order_result.order))


def _payment_payload(*, order: Order, payment_ref: str, outcome: str,
                     method: str, bank: str | None, vpa: str | None,
                     failure_reason: str | None,
                     payment_group_id: str | None = None) -> tuple[dict, dict]:
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
    if payment_group_id:
        payment["notes"] = {"paytwin_group_id": payment_group_id}
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
                     failure_reason: str | None = None,
                     payment_group_id: str | None = None) -> dict:
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
        payment_group_id=payment_group_id,
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


def _emit_payment_link_webhook(db: Session, link: PaymentLink, order: Order,
                               outcome: str, payment: dict | None = None) -> dict:
    """Send a real signed Razorpay-shaped Payment Link delivery through ingress."""
    now = int(time.time())
    if payment is None:
        payment = {
            "id": f"pay_link_{link.link_ref[-18:]}", "entity": "payment",
            "amount": 0, "currency": link.currency, "status": "failed",
            "order_id": order.order_ref, "method": "upi", "created_at": now,
            "error_reason": outcome,
        }
    event = {
        "paid": "payment_link.paid",
        "partially_paid": "payment_link.partially_paid",
        "expired": "payment_link.expired",
        "cancelled": "payment_link.cancelled",
    }[outcome]
    payload = {
        "event": event,
        "payload": {
            "payment_link": {"entity": _link_payload(link, order)},
            "order": {"entity": _order_payload(order)},
            "payment": {"entity": payment},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(_webhook_secret(db, link.merchant_id).encode(), raw,
                         hashlib.sha256).hexdigest()
    event_id = _id("evt")
    result = ingest_webhook(db, "razorpay", link.merchant_id, raw, signature,
                            headers={"x-razorpay-event-id": event_id})
    if result.status != 200:
        raise RuntimeError(f"local payment-link webhook was rejected: {result.body}")
    return {"event_id": event_id, "event": event, "result": result.body}


def simulate_payment_link_outcome(
    db: Session, *, merchant_id: str, link_ref: str, outcome: str,
    amount_paid_paise: int | None = None,
) -> dict:
    """Advance a local Payment Link and emit the matching signed webhook.

    A ``paid`` result creates a captured payment through the normal checkout
    lifecycle first. Partial/cancelled/expired outcomes are still delivered as
    provider-shaped webhooks but do not claim recovered revenue.
    """
    if outcome not in {"paid", "partially_paid", "expired", "cancelled"}:
        raise LocalProviderError("outcome must be paid, partially_paid, expired, or cancelled")
    link = (db.query(PaymentLink)
            .filter(PaymentLink.merchant_id == merchant_id,
                    PaymentLink.provider == "razorpay", PaymentLink.link_ref == link_ref)
            .one_or_none())
    if link is None:
        raise LocalProviderError("payment link not found")
    order = db.query(Order).filter(Order.id == link.order_id).one()
    if link.status in {"paid", "cancelled", "expired"}:
        raise LocalProviderError(f"payment link is already {link.status}")
    now = datetime.now(timezone.utc)
    if link.expires_at is not None and link.expires_at.replace(tzinfo=timezone.utc) < now \
            and outcome not in {"expired", "cancelled"}:
        raise LocalProviderError("payment link has expired")

    payment = None
    if outcome == "paid":
        captured = simulate_payment(db, merchant_id=merchant_id, order_ref=order.order_ref,
                                    outcome="captured", method="upi", bank="HDFC",
                                    vpa="recovery@upi", payment_group_id=link.payment_group_id)
        payment = captured["payment"]
        link.amount_paid_paise = link.amount_paise
        link.status = "paid"
        link.terminal_reason = "captured_payment"
    elif outcome == "partially_paid":
        amount = int(amount_paid_paise or 0)
        if not 1 <= amount < link.amount_paise:
            raise LocalProviderError("partial payment must be between 1 and the link amount - 1")
        link.amount_paid_paise = max(link.amount_paid_paise, amount)
        link.status = "partially_paid"
        payment = {
            "id": f"pay_link_{link.link_ref[-18:]}", "entity": "payment",
            "amount": amount, "currency": link.currency, "status": "authorized",
            "order_id": order.order_ref, "method": "upi", "bank": "HDFC",
            "created_at": int(time.time()),
        }
    else:
        link.status = outcome
        link.terminal_reason = outcome

    db.flush()
    webhook = _emit_payment_link_webhook(db, link, order, outcome, payment)
    return {"provenance": PROVENANCE, "payment_link": _link_payload(link, order),
            "webhook": webhook, "payment": payment}


def cancel_open_payment_links(db: Session, *, action_execution_id: str,
                              reason: str) -> int:
    """Cancel outstanding local links when a recovery action is halted/rolled back."""
    links = (db.query(PaymentLink)
             .filter(PaymentLink.action_execution_id == action_execution_id,
                     PaymentLink.status.in_(("issued", "partially_paid"))).all())
    for link in links:
        order = db.query(Order).filter(Order.id == link.order_id).one()
        link.status = "cancelled"
        link.terminal_reason = reason[:160]
        db.flush()
        _emit_payment_link_webhook(db, link, order, "cancelled")
    return len(links)


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
