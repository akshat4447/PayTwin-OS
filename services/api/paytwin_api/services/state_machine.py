"""Payment state machine (PIPE-002). Applies canonical events to payments rows.

Rules:
- Forward-only by occurred_at per payment_ref (out-of-order protection).
- Late events still recorded in canonical_events (with late=True) but do not regress state.
- Retry groups: group_id links attempts; group recovered when any attempt succeeds.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from paytwin_contracts import CanonicalEvent

from paytwin_api.models import Payment

_FINAL = {"success", "failed", "refunded"}

# Forward-only ladder: a payment may never move DOWN a rank, regardless of when
# the event claims to have occurred (a late `created` cannot undo `authorized`).
_RANK = {"created": 0, "authorized": 1, "timeout": 1, "failed": 2,
         "success": 2, "refunded": 3}


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
            amount_paise=e.amount_paise,
            occurred_at=e.occurred_at,
            status="created",
        )
        db.add(row)
        db.flush()
    return row


def apply_event(db: Session, e: CanonicalEvent) -> Payment:
    p = _ensure_payment(db, e)
    stale = e.occurred_at < _aware(p.occurred_at)
    if stale and p.status in _FINAL:
        return p  # late/out-of-order: never regress a final state

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
        # Forward-only by state rank too: a late/out-of-order event (e.g. a
        # replayed `payment.created`) may never move the payment DOWN the ladder.
        if _RANK.get(target, 0) < _RANK.get(p.status, 0):
            return p
        if target != p.status:
            _apply_status(db, p, t, target, e)

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
    "refund.created": "refunded",
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


def _mark_group_recovered(db: Session, p: Payment, e: CanonicalEvent) -> None:
    """Any success in a retry group marks the group recovered (eventual-success label)."""
    db.query(Payment).filter(
        Payment.organization_id == p.organization_id,
        Payment.group_id == p.group_id,
        Payment.recovered.is_(False),
    ).update({"recovered": True}, synchronize_session=False)
