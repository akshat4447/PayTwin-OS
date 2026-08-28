"""Sandbox integration registry used by the Razorpay hackathon demo.

Credentials are never accepted or returned here.  ``secret_ref`` is only the name
of an environment variable that contains a webhook secret.  Real payment actions
remain disabled by the executor; this API makes a Test Mode webhook connection
explicit, tenant-scoped, and auditable.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.connectors import SUPPORTED_PROVIDERS, get_connector
from paytwin_api.deps import current_principal, err, get_db, require_admin
from paytwin_api.models import Integration, Merchant
from paytwin_api.services import audit as audit_svc

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,119}$")


class ConnectBody(BaseModel):
    merchant_id: str
    provider: str
    # The demo is deliberately sandbox-only.  Keeping this in the request makes
    # the safety boundary visible in both API responses and the UI.
    test_mode: bool = True
    environment: str = Field(default="local_test", pattern="^(local_test|razorpay_test)$")
    secret_ref: str | None = Field(default=None, max_length=120)
    api_secret_ref: str | None = Field(default=None, max_length=120)


def _serialize(row: Integration) -> dict:
    return {
        "id": row.id,
        "merchant_id": row.merchant_id,
        "provider": row.provider,
        "status": row.status,
        "test_mode": row.status == "test_mode",
        "environment": row.environment,
        "capabilities": row.capabilities or {},
        # Expose only the environment-variable *name*, never its value.
        "secret_ref": row.secret_ref,
        "api_secret_ref": row.api_secret_ref,
        # This opaque route identifier is not a credential. It prevents a
        # public webhook URL from exposing or trusting a merchant identifier.
        "webhook_path": (f"/webhooks/{row.provider}/{row.webhook_route_token}"
                         if row.webhook_route_token else None),
        "previous_secret_expires_at": (row.previous_secret_expires_at.isoformat()
                                        if row.previous_secret_expires_at else None),
        "last_webhook_at": row.last_webhook_at.isoformat() if row.last_webhook_at else None,
        "created_at": row.created_at.isoformat(),
    }


@router.get("")
def list_integrations(p: Principal = Depends(current_principal),
                      db: Session = Depends(get_db),
                      scope: str | None = None):
    q = db.query(Integration).filter(Integration.organization_id == p.organization_id)
    if scope and scope != "org":
        q = q.filter(Integration.merchant_id == scope)
    return {"integrations": [_serialize(row) for row in q.order_by(Integration.created_at).all()],
            "supported_providers": list(SUPPORTED_PROVIDERS),
            "execution_boundary": "sandbox-only local and provider Test Mode; live PSP execution is disabled"}


@router.post("")
def connect(body: ConnectBody, p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)):
    """Create or refresh a tenant-scoped Test Mode integration reference."""
    require_admin(p)
    provider = body.provider.lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        return err(422, "unsupported_provider", f"choose one of {SUPPORTED_PROVIDERS}")
    if not body.test_mode:
        return err(422, "test_mode_required",
                   "hackathon integrations are Test Mode only; real execution is disabled")
    for field, value in (("secret_ref", body.secret_ref),
                         ("api_secret_ref", body.api_secret_ref)):
        if value and not _ENV_NAME.fullmatch(value):
            return err(422, "invalid_secret_ref",
                       f"{field} must be an environment variable name")

    merchant = (db.query(Merchant)
                .filter(Merchant.organization_id == p.organization_id,
                        Merchant.id == body.merchant_id).one_or_none())
    if merchant is None:
        return err(404, "not_found", f"merchant {body.merchant_id}")

    default_ref = ("PAYTWIN_WEBHOOK_SECRET_RAZORPAY"
                   if provider == "razorpay" else None)
    default_api_ref = ("PAYTWIN_RAZORPAY_KEY_SECRET"
                       if provider == "razorpay" else None)
    row = (db.query(Integration)
           .filter(Integration.merchant_id == merchant.id,
                   Integration.provider == provider).one_or_none())
    if row is None:
        row = Integration(organization_id=p.organization_id, merchant_id=merchant.id,
                          provider=provider)
        db.add(row)
    row.status = "test_mode"
    row.environment = body.environment
    row.webhook_route_token = row.webhook_route_token or secrets.token_urlsafe(32)
    row.secret_ref = body.secret_ref or row.secret_ref or default_ref
    row.api_secret_ref = body.api_secret_ref or row.api_secret_ref or default_api_ref
    row.capabilities = get_connector(provider).capabilities().as_dict()
    db.flush()
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="integration.connected",
        object_type="integration", object_id=row.id,
        summary=f"{provider} {body.environment} connected for {merchant.name}",
        details={"merchant_id": merchant.id, "provider": provider,
                 "test_mode": True, "environment": row.environment,
                 "capabilities": row.capabilities,
                 "secret_ref_configured": bool(row.secret_ref),
                 "api_secret_ref_configured": bool(row.api_secret_ref)},
    )
    db.commit()
    return _serialize(row)


class RotateWebhookSecretBody(BaseModel):
    merchant_id: str
    secret_ref: str = Field(min_length=1, max_length=120)
    # Razorpay can retry failed webhooks for up to 24h. Keep an overlap at
    # least that long so a rotation does not turn a valid retry into a loss.
    grace_minutes: int = Field(default=24 * 60, ge=24 * 60, le=16 * 24 * 60)


@router.post("/webhook-secret/rotate")
def rotate_webhook_secret(body: RotateWebhookSecretBody,
                          p: Principal = Depends(current_principal),
                          db: Session = Depends(get_db)):
    """Rotate an env-reference with an explicit, bounded dual-secret window."""
    require_admin(p)
    if not _ENV_NAME.fullmatch(body.secret_ref):
        return err(422, "invalid_secret_ref", "secret_ref must be an environment variable name")
    row = (db.query(Integration)
           .filter(Integration.organization_id == p.organization_id,
                   Integration.merchant_id == body.merchant_id,
                   Integration.provider == "razorpay").one_or_none())
    if row is None:
        return err(404, "not_found", "Razorpay Test Mode integration")
    if row.secret_ref == body.secret_ref:
        return err(422, "unchanged_secret_ref", "new secret_ref must differ from the current reference")

    previous = row.secret_ref
    row.secret_ref = body.secret_ref
    row.previous_secret_ref = previous
    row.previous_secret_expires_at = datetime.now(timezone.utc) + timedelta(minutes=body.grace_minutes)
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="integration.webhook_secret_rotated",
        object_type="integration", object_id=row.id,
        summary="Razorpay webhook secret reference rotated",
        details={"merchant_id": row.merchant_id, "provider": "razorpay",
                 "grace_minutes": body.grace_minutes,
                 "previous_reference_present": bool(previous)},
    )
    db.commit()
    return _serialize(row)
