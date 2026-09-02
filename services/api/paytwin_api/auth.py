"""AuthN/AuthZ: hashed API keys, principal resolution, RBAC helpers (ADR-010)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from paytwin_api.models import ApiKey

ROLES = ("org_admin", "ops_oncall", "finance_viewer", "risk_admin")
WRITE_ROLES = ("org_admin", "ops_oncall", "risk_admin")
ADMIN_ROLES = ("org_admin", "risk_admin")
WORKSPACE_SESSION_COOKIE = "paytwin_workspace"
_WORKSPACE_SESSION_PURPOSE = "paytwin-workspace-session:v1"


class AuthError(Exception):
    def __init__(self, code: str, status: int = 401):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Principal:
    organization_id: str
    role: str
    key_prefix: str
    user_id: str | None = None
    key_id: str | None = None

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def new_api_key(organization_id: str, role: str, user_id: str | None = None) -> tuple[str, ApiKey]:
    """Returns (raw_key_once, ApiKey row). Only the hash is persisted."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role}")
    raw = "ptw_" + secrets.token_urlsafe(24)
    row = ApiKey(
        organization_id=organization_id,
        user_id=user_id,
        key_prefix=raw[:8],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        role=role,
        scopes=["read"] + (["write"] if role in WRITE_ROLES else []),
    )
    return raw, row


def resolve_principal(db: Session, authorization: str | None) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("missing_bearer")
    raw = authorization.removeprefix("Bearer ").strip()
    if len(raw) < 12:
        raise AuthError("malformed_key")
    h = hashlib.sha256(raw.encode()).hexdigest()
    row = db.query(ApiKey).filter(ApiKey.key_hash == h).one_or_none()
    if row is None or not row.active:
        raise AuthError("invalid_key")
    return Principal(
        organization_id=row.organization_id,
        role=row.role,
        key_prefix=row.key_prefix,
        user_id=row.user_id,
        key_id=row.id,
    )


def issue_workspace_session(principal: Principal, secret: str,
                            issued_at: int | None = None) -> str:
    """Create a signed, short-lived session without serializing the raw API key.

    The cookie holds an API-key row identifier and issuance time only.  It is
    HMAC-signed by the server; an inactive/revoked key is still rejected when
    the cookie is consumed.
    """
    if not principal.key_id:
        raise ValueError("principal lacks API key identity")
    issued = int(time.time()) if issued_at is None else int(issued_at)
    payload = f"{principal.key_id}.{issued}"
    mac = hmac.new(secret.encode(),
                   f"{_WORKSPACE_SESSION_PURPOSE}:{payload}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def resolve_workspace_session(db: Session, token: str | None, secret: str,
                              ttl_seconds: int, now: int | None = None) -> Principal:
    """Resolve an HttpOnly workspace session, failing closed on every anomaly."""
    if not token:
        raise AuthError("missing_bearer")
    try:
        key_id, issued_text, supplied_mac = token.split(".", 2)
        issued = int(issued_text)
    except (AttributeError, ValueError):
        raise AuthError("invalid_session") from None
    payload = f"{key_id}.{issued}"
    expected_mac = hmac.new(secret.encode(),
                            f"{_WORKSPACE_SESSION_PURPOSE}:{payload}".encode(),
                            hashlib.sha256).hexdigest()
    current = int(time.time()) if now is None else int(now)
    if (not hmac.compare_digest(supplied_mac, expected_mac)
            or issued > current + 60
            or current - issued > max(1, int(ttl_seconds))):
        raise AuthError("invalid_session")
    row = db.query(ApiKey).filter(ApiKey.id == key_id).one_or_none()
    if row is None or not row.active:
        raise AuthError("invalid_session")
    return Principal(
        organization_id=row.organization_id,
        role=row.role,
        key_prefix=row.key_prefix,
        user_id=row.user_id,
        key_id=row.id,
    )
