"""Webhook ingestion (PIPE-001): verify → inbox idempotency → canonicalize → outbox → state.

The merchant scope arrives as ?merchant=<merchant_id> (the integration this webhook is
configured for); org is derived from the merchant row. Bad signature ⇒ 401 + dead-letter.
Duplicate external_event_id ⇒ 200 {"duplicate": true} (idempotent at-least-once delivery).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.connectors import get_connector
from paytwin_api.connectors.base import WebhookRejected
from paytwin_api.models import (CanonicalEventRow, DeadLetter, EventInbox,
                                Integration, Merchant)
from paytwin_api.services.bus import publish_outbox
from paytwin_api.services.state_machine import apply_event


class IngestResult:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body


def _provider_secret(provider: str) -> str:
    s = get_settings()
    return {
        "simulator": s.webhook_secret_simulator,
        "mockprovider": s.webhook_secret_mockprovider,
        "razorpay": s.webhook_secret_razorpay,
    }.get(provider, "")


def _secrets_for(db: Session, provider: str, merchant: Merchant) -> tuple[str, ...]:
    """Resolve active inbound webhook secrets for one merchant integration.

    ``Integration.secret_ref`` is an environment-variable name, never a raw
    secret.  It lets each Razorpay Test Mode integration use its own webhook
    secret while retaining the historical per-provider setting as a sandbox/demo
    fallback when an integration is not yet configured. During an explicit
    rotation grace window, the immediately previous reference is accepted too;
    that keeps provider retries from becoming false signature failures.
    """
    integration = (
        db.query(Integration)
        .filter(Integration.merchant_id == merchant.id,
                Integration.provider == provider)
        .one_or_none()
    )
    secrets: list[str] = []
    if integration is not None and integration.secret_ref:
        configured = os.environ.get(integration.secret_ref, "")
        if configured:
            secrets.append(configured)
    if integration is not None and integration.previous_secret_ref:
        expires_at = integration.previous_secret_expires_at
        if expires_at is not None:
            expires_at = (expires_at.replace(tzinfo=timezone.utc)
                          if expires_at.tzinfo is None else expires_at)
            if expires_at >= datetime.now(timezone.utc):
                previous = os.environ.get(integration.previous_secret_ref, "")
                if previous:
                    secrets.append(previous)
    # Once a tenant-specific secret has resolved, do not also accept a shared
    # provider fallback.  That would silently weaken the tenant boundary.
    if not secrets:
        fallback = _provider_secret(provider)
        if fallback:
            secrets.append(fallback)
    # Avoid doing HMAC work twice when the fallback and configured value match.
    return tuple(dict.fromkeys(secrets))


def ingest_webhook(db: Session, provider: str, merchant_id: str, body: bytes,
                   signature: str, headers: dict | None = None,
                   *, commit: bool = True) -> IngestResult:
    """Verify, normalize, persist, and materialize a provider webhook.

    Request handlers use the default transactional commit.  Deterministic demo
    seeding may set ``commit=False`` and commit bounded batches without bypassing
    any of the real connector, inbox, canonical-event, or state-machine logic.
    """
    m = db.query(Merchant).filter(Merchant.id == merchant_id).one_or_none()
    if m is None:
        return IngestResult(404, {"error": {"code": "unknown_merchant", "message": merchant_id}})

    try:
        connector = get_connector(provider)
    except WebhookRejected:
        # Provider is part of the public webhook URL.  Return a typed response
        # instead of leaking an adapter exception as a FastAPI 500.
        db.add(DeadLetter(organization_id=m.organization_id, reason="unknown_provider",
                          detail=f"unsupported provider {provider}"[:500],
                          payload={"body_sha": hashlib.sha256(body).hexdigest()}))
        if commit:
            db.commit()
        return IngestResult(404, {"error": {"code": "unknown_provider",
                                            "message": provider}})

    if not any(connector.verify_webhook(body, signature or "", secret)
               for secret in _secrets_for(db, provider, m)):
        db.add(DeadLetter(organization_id=m.organization_id, reason="bad_signature",
                          detail=f"{provider} webhook for {merchant_id}",
                          payload={"body_sha": hashlib.sha256(body).hexdigest()}))
        if commit:
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
        if commit:
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
        if commit:
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
                       status="received", payload=_inbox_payload(raw_payload))
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

    integration = (db.query(Integration)
                   .filter(Integration.merchant_id == m.id,
                           Integration.provider == provider).one_or_none())
    if integration is not None:
        integration.last_webhook_at = datetime.now(timezone.utc)

    inbox.status = "processed"
    inbox.processed_at = datetime.now(timezone.utc)
    publish_outbox(db, m.organization_id, "payment.updated", {
        "event": event.type, "payment_ref": event.payment_ref,
        "merchant_id": m.id, "status": payment.status,
        "amount_paise": event.amount_paise, "late": late,
        "cohort": event.cohort,
    })
    if commit:
        db.commit()
    return IngestResult(200, {"ok": True, "event": event.type, "payment_status": payment.status,
                              "late": late, "canonical_id": row.id})


_PII_KEYS = {"customer_ref", "customer_id", "vpa", "email", "phone", "contact",
             "contact_id", "name", "notes", "description", "pan", "cvv",
             "card_number", "cardholder_name", "expiry", "exp_month", "exp_year"}
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
    return _capped_redacted_payload(redacted, body)


def _inbox_payload(raw_payload: dict) -> dict:
    """Store only a redacted, size-capped trace of a successful delivery."""
    return _capped_redacted_payload(_redact(raw_payload),
                                    json.dumps(raw_payload, default=str).encode())


def _capped_redacted_payload(redacted, raw_body: bytes) -> dict:
    if len(json.dumps(redacted, default=str)) > _DLQ_MAX_BYTES:
        return {"truncated": True, "body_sha256": hashlib.sha256(raw_body).hexdigest(),
                "keys": list(redacted)[:20] if isinstance(redacted, dict) else None}
    return redacted
