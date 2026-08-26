"""Webhook ingestion (PIPE-001): verify → inbox idempotency → canonicalize → outbox → state.

The merchant scope arrives as ?merchant=<merchant_id> (the integration this webhook is
configured for); org is derived from the merchant row. Bad signature ⇒ 401 + dead-letter.
Duplicate external_event_id ⇒ 200 {"duplicate": true} (idempotent at-least-once delivery).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.connectors import get_connector
from paytwin_api.connectors.base import WebhookRejected
from paytwin_api.models import CanonicalEventRow, DeadLetter, EventInbox, Merchant
from paytwin_api.services.bus import publish_outbox
from paytwin_api.services.state_machine import apply_event


class IngestResult:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body


def _secret_for(provider: str) -> str:
    s = get_settings()
    return {
        "simulator": s.webhook_secret_simulator,
        "mockprovider": s.webhook_secret_mockprovider,
        "razorpay": s.webhook_secret_razorpay,
    }.get(provider, "")


def ingest_webhook(db: Session, provider: str, merchant_id: str, body: bytes,
                   signature: str, headers: dict | None = None) -> IngestResult:
    m = db.query(Merchant).filter(Merchant.id == merchant_id).one_or_none()
    if m is None:
        return IngestResult(404, {"error": {"code": "unknown_merchant", "message": merchant_id}})

    connector = get_connector(provider)
    if not connector.verify_webhook(body, signature or "", _secret_for(provider)):
        db.add(DeadLetter(organization_id=m.organization_id, reason="bad_signature",
                          detail=f"{provider} webhook for {merchant_id}",
                          payload={"body_sha": hashlib.sha256(body).hexdigest()}))
        db.commit()
        return IngestResult(401, {"error": {"code": "bad_signature", "message": "rejected"}})

    try:
        raw_payload = json.loads(body.decode("utf-8"))
        if not isinstance(raw_payload, dict):
            raise ValueError("payload must be an object")
        event = connector.normalize(raw_payload, m.organization_id, m.id, headers=headers)
    except (WebhookRejected, ValueError) as e:
        db.add(DeadLetter(organization_id=m.organization_id, reason="malformed",
                          detail=str(e)[:480], payload=_dlq_payload(body)))
        db.commit()
        return IngestResult(422, {"error": {"code": "malformed_payload", "message": str(e)[:200]}})

    # Idempotency at the inbox — tenant-scoped, race-safe: the UNIQUE
    # (provider, organization, external_event_id) constraint is the arbiter.
    existing = (
        db.query(EventInbox)
        .filter(EventInbox.provider == provider,
                EventInbox.organization_id == m.organization_id,
                EventInbox.external_event_id == event.external_event_id)
        .one_or_none()
    )
    if existing is not None:
        existing.status = "duplicate"
        db.commit()
        return IngestResult(200, {"duplicate": True, "id": existing.id})

    # Late-event detection vs last seen occurrence for this merchant
    last = (
        db.query(CanonicalEventRow.occurred_at)
        .filter(CanonicalEventRow.merchant_id == m.id)
        .order_by(CanonicalEventRow.occurred_at.desc())
        .first()
    )
    late = bool(last and event.occurred_at < last[0].replace(tzinfo=timezone.utc) - timedelta(seconds=60))

    inbox = EventInbox(organization_id=m.organization_id, provider=provider,
                       external_event_id=event.external_event_id, signature_ok=True,
                       status="received", payload=raw_payload)
    db.add(inbox)
    try:
        with db.begin_nested():  # concurrent retry loses the race, not the request
            db.flush()
    except IntegrityError:
        db.rollback()
        winner = (
            db.query(EventInbox)
            .filter(EventInbox.provider == provider,
                    EventInbox.organization_id == m.organization_id,
                    EventInbox.external_event_id == event.external_event_id)
            .one_or_none()
        )
        if winner is not None:
            return IngestResult(200, {"duplicate": True, "id": winner.id})
        raise

    row = CanonicalEventRow(
        organization_id=event.organization_id, merchant_id=event.merchant_id,
        type=event.type, provider=event.provider, external_event_id=event.external_event_id,
        occurred_at=event.occurred_at, payment_ref=event.payment_ref,
        amount_paise=event.amount_paise, currency=event.currency,
        issuer=event.cohort.get("issuer"), method=event.cohort.get("method"),
        psp=event.cohort.get("psp"), gateway=event.cohort.get("gateway"),
        payload=event.payload, late=late,
    )
    db.add(row)
    db.flush()

    payment = apply_event(db, event)

    inbox.status = "processed"
    inbox.processed_at = datetime.now(timezone.utc)
    publish_outbox(db, m.organization_id, "payment.updated", {
        "event": event.type, "payment_ref": event.payment_ref,
        "merchant_id": m.id, "status": payment.status,
        "amount_paise": event.amount_paise, "late": late,
        "cohort": event.cohort,
    })
    db.commit()
    return IngestResult(200, {"ok": True, "event": event.type, "payment_status": payment.status,
                              "late": late, "canonical_id": row.id})


_PII_KEYS = {"customer_ref", "customer_id", "vpa", "email", "phone", "contact",
             "contact_id", "name", "notes", "description"}
_DLQ_MAX_BYTES = 8192


def _redact(obj, depth: int = 0):
    """Recursive PII redaction + string capping for dead-letter payloads."""
    if depth > 6:
        return "…"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in _PII_KEYS:
                out[k] = "[redacted]"
            else:
                out[k] = _redact(v, depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(x, depth + 1) for x in list(obj)[:20]]
    if isinstance(obj, str):
        return obj[:200]
    return obj


def _dlq_payload(body: bytes) -> dict:
    """Size-capped, PII-redacted raw payload for the dead-letter queue."""
    try:
        parsed = json.loads(body.decode("utf-8"))
        redacted = _redact(parsed if isinstance(parsed, dict)
                           else {"raw": str(parsed)[:400]})
    except Exception:
        return {"raw_b64_prefix": body[:120].hex()}
    if len(json.dumps(redacted, default=str)) > _DLQ_MAX_BYTES:
        return {"truncated": True, "body_sha256": hashlib.sha256(body).hexdigest(),
                "keys": list(redacted)[:20] if isinstance(redacted, dict) else None}
    return redacted
