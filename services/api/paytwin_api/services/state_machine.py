"""Payment state machine (PIPE-002). Applies canonical events to payments rows.

Rules:
- Explicit provider lifecycle transitions, rather than a numeric status rank.
- Late events still recorded in canonical_events (with late=True) but do not regress
  an immutable success/refund state.
- Retry groups: group_id links attempts; group recovered when any attempt succeeds.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from paytwin_contracts import CanonicalEvent

from paytwin_api.models import CheckoutVerification, Fulfilment, Order, Payment, Refund

# A payment failure or timeout is not necessarily terminal: some providers send a
# late authorization, and a later capture/success is valid.  In contrast, a
# captured payment must never be overwritten by an unrelated failure/timeout, and
# a refunded payment is immutable.  A refund is the one valid forward transition
# from a successful payment.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "created": {"created", "authorized", "timeout", "failed", "success", "refunded"},
    "authorized": {"authorized", "timeout", "failed", "success", "refunded"},
    "timeout": {"timeout", "authorized", "failed", "success", "refunded"},
    "failed": {"failed", "authorized", "success", "refunded"},
    "success": {"success", "refunded"},
    "refunded": {"refunded"},
}


def _aware(dt):
    """SQLite returns naive UTC datetimes; canonical events are tz-aware. Compare safely."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ensure_payment(db: Session, e: CanonicalEvent) -> Payment:
    # Tenant-scoped lookup: (merchant, provider, payment_ref). A reference reused
    # under another merchant/org is a DIFFERENT payment — never a cross-tenant write.
    row = (
        db.query(Payment)
        .filter(Payment.merchant_id == e.merchant_id,
                Payment.organization_id == e.organization_id,
                Payment.provider == e.provider,
                Payment.payment_ref == e.payment_ref)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        row = Payment(
            organization_id=e.organization_id,
            merchant_id=e.merchant_id,
            group_id=str(e.payload.get("group_id") or e.payment_ref),
            attempt_no=int(e.payload.get("attempt_no", 1)),
            provider=e.provider,
            payment_ref=e.payment_ref,
            order_ref=e.payload.get("order_ref"),
            customer_ref=e.payload.get("customer_ref"),
            # Refund events contain the refund amount in ``amount_paise``.  A
            # late refund must not turn that amount into the payment principal.
            amount_paise=int(e.payload.get("payment_amount_paise") or e.amount_paise),
            occurred_at=e.occurred_at,
            status="created",
        )
        db.add(row)
        db.flush()
    elif e.payload.get("order_ref") and not row.order_ref:
        # Some providers first send a sparse authorization and only attach the
        # order on capture/refund.  Preserve the first complete relationship.
        row.order_ref = str(e.payload["order_ref"])
    if e.payload.get("payment_link_ref") and e.payload.get("group_id"):
        # The original captured event is keyed by the new recovery order. The
        # immediately following Payment Link webhook carries the eligible
        # recovery group; preserve that stronger attribution key for outcomes.
        row.group_id = str(e.payload["group_id"])
    return row


def _ensure_order(db: Session, p: Payment, e: CanonicalEvent) -> Order | None:
    """Create/update a separate merchant order for payment-linked events."""
    order_ref = e.payload.get("order_ref") or p.order_ref
    if not order_ref:
        return None
    row = (db.query(Order)
           .filter(Order.organization_id == e.organization_id,
                   Order.merchant_id == e.merchant_id,
                   Order.provider == e.provider,
                   Order.order_ref == str(order_ref))
           .with_for_update().one_or_none())
    if row is None:
        row = Order(
            organization_id=e.organization_id, merchant_id=e.merchant_id,
            provider=e.provider, order_ref=str(order_ref),
            amount_paise=int(e.payload.get("order_amount_paise") or p.amount_paise),
            currency=e.currency,
        )
        db.add(row)
        db.flush()
    elif not row.amount_paise and p.amount_paise:
        row.amount_paise = p.amount_paise
    return row


def _mark_order_paid(order: Order | None, p: Payment, e: CanonicalEvent) -> None:
    if order is None or p.status not in {"success", "refunded"}:
        return
    order.status = "paid"
    order.amount_paid_paise = max(order.amount_paid_paise, p.amount_paise)
    if order.paid_at is None:
        order.paid_at = e.occurred_at


def _refund_status(e: CanonicalEvent) -> str:
    if e.type == "refund.failed":
        return "failed"
    if e.type == "refund.updated":
        return "updated"
    # Older generic connectors emit refund.created only when the refund has
    # completed. Razorpay is different: its ``refund.created`` callback can
    # genuinely still be pending, and carries the provider status explicitly.
    if e.type == "refund.created" and not e.payload.get("refund_status"):
        return "created" if e.provider == "razorpay" else "processed"
    return str(e.payload.get("refund_status") or "created")


def _apply_refund(db: Session, p: Payment, e: CanonicalEvent) -> None:
    """Apply one provider refund exactly once and never over-refund a payment."""
    # A production provider supplies a refund id.  The deterministic fallback
    # retains compatibility with generic simulator events while remaining
    # idempotent on their canonical external event id.
    refund_ref = str(e.payload.get("refund_ref") or f"event:{e.external_event_id}")
    amount = int(e.payload.get("refund_amount_paise") or e.amount_paise)
    row = (db.query(Refund)
           .filter(Refund.organization_id == e.organization_id,
                   Refund.merchant_id == e.merchant_id,
                   Refund.provider == e.provider,
                   Refund.refund_ref == refund_ref)
           .with_for_update().one_or_none())
    if row is None:
        row = Refund(
            organization_id=e.organization_id, merchant_id=e.merchant_id,
            payment_id=p.id, provider=e.provider, refund_ref=refund_ref,
            amount_paise=amount, currency=e.currency,
            receipt=e.payload.get("refund_receipt"),
            idempotency_key=e.payload.get("refund_idempotency_key"),
            speed_requested=e.payload.get("refund_speed_requested"),
            speed_processed=e.payload.get("refund_speed_processed"),
        )
        db.add(row)
        db.flush()
    else:
        # A provider update may add a speed/status field, but may never alter
        # the financial amount attached to a known refund reference.
        if row.amount_paise != amount:
            row.status = "rejected"
            row.failure_reason = "provider refund amount changed for same refund reference"
            return
        row.speed_requested = e.payload.get("refund_speed_requested") or row.speed_requested
        row.speed_processed = e.payload.get("refund_speed_processed") or row.speed_processed

    status = _refund_status(e)
    if status == "failed":
        row.status = "failed"
        row.failure_reason = str(e.payload.get("failure_class") or "provider_refund_failed")
        return
    if status not in {"processed", "created", "pending", "updated"}:
        row.status = status
        return
    if status != "processed":
        # A created/pending refund changes no financial aggregate.
        if row.status != "processed":
            row.status = status
        return
    if row.status == "processed":
        return  # duplicate delivery or later speed update: no second credit
    if p.status not in {"success", "refunded"}:
        row.status = "pending_reconciliation"
        return
    _settle_refund(p, row, e.occurred_at)


def _settle_refund(p: Payment, row: Refund, occurred_at: datetime) -> None:
    if p.refunded_amount_paise + row.amount_paise > p.amount_paise:
        row.status = "rejected"
        row.failure_reason = "refund total exceeds captured payment amount"
        return
    p.refunded_amount_paise += row.amount_paise
    row.status = "processed"
    row.processed_at = occurred_at
    if p.refunded_amount_paise == p.amount_paise:
        p.status = "refunded"
        p.final_status_at = occurred_at


def _settle_pending_refunds(db: Session, p: Payment, occurred_at: datetime) -> None:
    rows = (db.query(Refund)
            .filter(Refund.payment_id == p.id,
                    Refund.status == "pending_reconciliation")
            .order_by(Refund.created_at.asc()).with_for_update().all())
    for row in rows:
        _settle_refund(p, row, occurred_at)


def reconcile_pending_refunds(db: Session, payment: Payment,
                              occurred_at: datetime | None = None) -> int:
    """Settle held provider refunds once their payment has become captured.

    Webhooks normally trigger this inline.  The worker invokes this same safe
    path as a repair sweep for deliveries that arrived out of order or during a
    transient process failure.  It never calls a provider and never creates a
    fulfilment side effect.
    """
    if payment.status not in {"success", "refunded"}:
        return 0
    pending = (db.query(Refund)
               .filter(Refund.payment_id == payment.id,
                       Refund.status == "pending_reconciliation")
               .count())
    if not pending:
        return 0
    event_time = occurred_at or datetime.now(timezone.utc)
    _settle_pending_refunds(db, payment, event_time)
    db.flush()
    return pending


def _can_transition(p: Payment, target: str, occurred_at: datetime) -> bool:
    """Return whether a canonical event may change this payment's state.

    We intentionally permit ``failed -> authorized -> success`` and
    ``timeout -> success`` because those are legitimate late-provider lifecycle
    paths.  Success is otherwise immutable; only a non-stale refund may advance
    it.  Refunded remains immutable under every event.
    """
    current = p.status
    if target == current:
        return True
    if current == "refunded":
        return False
    if current == "success":
        return target == "refunded" and occurred_at >= _aware(p.occurred_at)
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def apply_event(db: Session, e: CanonicalEvent) -> Payment:
    p = _ensure_payment(db, e)

    # enrich cohort dims on first sight
    for dim in ("issuer", "method", "psp", "gateway"):
        v = e.cohort.get(dim)
        if v and not getattr(p, dim):
            setattr(p, dim, v)
    if e.payload.get("latency_ms") is not None:
        p.latency_ms = int(e.payload["latency_ms"])

    t = e.type
    target = _TARGET_STATUS.get(t)
    if target is not None:
        if not _can_transition(p, target, e.occurred_at):
            # Keep the canonical event for investigation, but never allow it to
            # corrupt the materialized payment state.
            return p
        if target != p.status:
            _apply_status(db, p, t, target, e)

    order = _ensure_order(db, p, e)
    if t in {"refund.created", "refund.failed", "refund.updated"}:
        _apply_refund(db, p, e)
    if t in {"payment.success", "order.paid"}:
        _settle_pending_refunds(db, p, e.occurred_at)
        _mark_order_paid(order, p, e)

    p.occurred_at = max(_aware(p.occurred_at), e.occurred_at)
    p.updated_at = datetime.now(timezone.utc)
    db.flush()
    return p


_TARGET_STATUS = {
    "payment.created": "created",
    "payment.authorized": "authorized",
    "payment.timeout": "timeout",
    "payment.failed": "failed",
    "payment.success": "success",
    "order.paid": "success",
}


def _apply_status(db: Session, p: Payment, event_type: str, target: str,
                  e: CanonicalEvent) -> None:
    p.status = target
    if event_type == "payment.failed":
        p.failure_class = e.payload.get("failure_class") or "issuer_decline"
        p.final_status_at = e.occurred_at
    elif event_type == "payment.success":
        p.final_status_at = e.occurred_at
        _mark_group_recovered(db, p, e)
    elif target == "authorized":
        # A late authorization re-opens a previously failed attempt; the later
        # capture/success event will set its definitive final timestamp again.
        p.final_status_at = None


def record_fulfilment(db: Session, payment: Payment, *, source: str,
                      idempotency_key: str) -> Fulfilment:
    """Record the one allowed fulfilment for a paid order.

    The unique order/idempotency constraints are the final guard under
    concurrent requests; PostgreSQL callers additionally benefit from row locks
    acquired by the payment state transition.
    """
    if payment.status not in {"success", "refunded"}:
        raise ValueError("cannot fulfil an uncaptured payment")
    if not payment.order_ref:
        raise ValueError("cannot fulfil a payment without an order reference")
    order = (db.query(Order)
             .filter(Order.organization_id == payment.organization_id,
                     Order.merchant_id == payment.merchant_id,
                     Order.provider == payment.provider,
                     Order.order_ref == payment.order_ref)
             .with_for_update().one_or_none())
    if order is None or order.status != "paid":
        raise ValueError("cannot fulfil an unpaid order")
    fulfilment_payment = payment
    if payment.provider == "razorpay" and source == "razorpay_checkout":
        # A captured webhook is not a browser Checkout proof. Require the
        # server-side HMAC verification for this merchant order before the
        # single irreversible business effect is recorded.
        proof = (db.query(CheckoutVerification)
                 .filter(CheckoutVerification.organization_id == payment.organization_id,
                         CheckoutVerification.merchant_id == payment.merchant_id,
                         CheckoutVerification.order_id == order.id,
                         CheckoutVerification.provider == "razorpay",
                         CheckoutVerification.signature_valid.is_(True),
                         CheckoutVerification.status == "verified")
                 .order_by(CheckoutVerification.verified_at.desc()).first())
        if proof is None:
            raise ValueError("cannot fulfil Razorpay order without verified Checkout proof")
        if proof.payment_id:
            verified_payment = db.query(Payment).filter(Payment.id == proof.payment_id).one_or_none()
            if verified_payment is None or verified_payment.order_ref != order.order_ref:
                raise ValueError("verified Checkout proof is not linked to this order payment")
            fulfilment_payment = verified_payment
    existing = db.query(Fulfilment).filter(Fulfilment.order_id == order.id).one_or_none()
    if existing is not None:
        return existing
    row = Fulfilment(
        organization_id=payment.organization_id, merchant_id=payment.merchant_id,
        order_id=order.id, payment_id=fulfilment_payment.id, source=source,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    return row


def _mark_group_recovered(db: Session, p: Payment, e: CanonicalEvent) -> None:
    """Any success in a retry group marks the group recovered (eventual-success label)."""
    db.query(Payment).filter(
        Payment.organization_id == p.organization_id,
        Payment.group_id == p.group_id,
        Payment.recovered.is_(False),
    ).update({"recovered": True}, synchronize_session=False)
