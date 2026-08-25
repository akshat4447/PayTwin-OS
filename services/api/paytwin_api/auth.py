"""AuthN/AuthZ: hashed API keys, principal resolution, RBAC helpers (ADR-010)."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from paytwin_api.models import ApiKey

ROLES = ("org_admin", "ops_oncall", "finance_viewer", "risk_admin")
WRITE_ROLES = ("org_admin", "ops_oncall", "risk_admin")
ADMIN_ROLES = ("org_admin", "risk_admin")


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
    )
