"""Event pipeline tables: inbox (idempotency), canonical events, DLQ, outbox, payments."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from paytwin_api.db import Base
from paytwin_api.models.tenancy import _id, _now


class EventInbox(Base):
    __tablename__ = "event_inbox"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="uq_event_inbox_provider_ext"),
        Index("ix_event_inbox_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("inb"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    external_event_id: Mapped[str] = mapped_column(String(200))
    signature_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="received")  # received|processed|duplicate|dead
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonicalEventRow(Base):
    __tablename__ = "canonical_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="uq_canon_provider_ext"),
        Index("ix_canon_merchant_time", "merchant_id", "occurred_at"),
        Index("ix_canon_type", "type"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("evt"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    merchant_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(30))
    external_event_id: Mapped[str] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    payment_ref: Mapped[str] = mapped_column(String(200), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    issuer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    psp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gateway: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


# __PART2__


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("dlq"))
    organization_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    reason: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_undispatched", "dispatched_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("obx"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    topic: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_pay_merchant_time", "merchant_id", "occurred_at"),
        Index("ix_pay_group", "group_id"),
        UniqueConstraint("provider", "payment_ref", name="uq_pay_provider_ref"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("pay"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    merchant_id: Mapped[str] = mapped_column(String(40), index=True)
    group_id: Mapped[str] = mapped_column(String(40))  # retry group
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(30))
    payment_ref: Mapped[str] = mapped_column(String(200))
    order_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    psp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gateway: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)
    failure_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    final_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
