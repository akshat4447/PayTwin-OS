"""Tenancy & identity: organizations, merchants, users, api keys."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from paytwin_api.db import Base


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("org"))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    plan: Mapped[str] = mapped_column(String(30), default="growth")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("mer"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120))
    short_code: Mapped[str] = mapped_column(String(4))
    color: Mapped[str] = mapped_column(String(16), default="#6d7dff")
    industry: Mapped[str] = mapped_column(String(40), default="ecommerce")
    autonomy_mode: Mapped[int] = mapped_column(Integer, default=1)  # AutonomyMode
    stage: Mapped[int] = mapped_column(Integer, default=3)  # onboarding 1..5
    sr_base_bp: Mapped[int] = mapped_column(Integer, default=9500)  # basis points
    gmv_mtd_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    protected_mtd_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("usr"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30), default="ops_oncall")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("key"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)  # shown in UI
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)   # sha256 hex
    role: Mapped[str] = mapped_column(String(30), default="ops_oncall")
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def active(self) -> bool:
        return self.revoked_at is None


def hash_key(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()
