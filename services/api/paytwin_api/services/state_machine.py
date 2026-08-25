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


def _aware(dt):
    """SQLite returns naive UTC datetimes; canonical events are tz-aware. Compare safely."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ensure_payment(db: Session, e: CanonicalEvent) -> Payment:
    row = (
        db.query(Payment)
        .filter(Payment.provider == e.provider, Payment.payment_ref == e.payment_ref)
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
    if t == "payment.created":
        p.status = "created"
    elif t == "payment.authorized":
        p.status = "authorized"
    elif t == "payment.timeout":
        p.status = "timeout"
    elif t == "payment.failed":
        p.status = "failed"
        p.failure_class = e.payload.get("failure_class") or "issuer_decline"
        p.final_status_at = e.occurred_at
    elif t == "payment.success":
        p.status = "success"
        p.final_status_at = e.occurred_at
        _mark_group_recovered(db, p, e)
    elif t == "refund.created":
        p.status = "refunded"

    p.occurred_at = max(_aware(p.occurred_at), e.occurred_at)
    p.updated_at = datetime.now(timezone.utc)
    db.flush()
    return p


def _mark_group_recovered(db: Session, p: Payment, e: CanonicalEvent) -> None:
    """Any success in a retry group marks the group recovered (eventual-success label)."""
    db.query(Payment).filter(
        Payment.organization_id == p.organization_id,
        Payment.group_id == p.group_id,
        Payment.recovered.is_(False),
    ).update({"recovered": True}, synchronize_session=False)
