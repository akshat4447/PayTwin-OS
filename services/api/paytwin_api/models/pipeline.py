"""Event pipeline tables: inbox (idempotency), canonical events, DLQ, outbox, payments.

Tenancy invariants (enforced at the schema layer):
- Inbox/canonical idempotency is scoped per (provider, organization, external id) —
  one tenant's provider event can never shadow another tenant's delivery.
- Payments are unique per (merchant, provider, payment_ref) — the same provider
  reference under different merchants is a different row, never a cross-tenant write.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from paytwin_api.db import Base
from paytwin_api.models.tenancy import _id, _now


class EventInbox(Base):
    __tablename__ = "event_inbox"
    __table_args__ = (
        UniqueConstraint("provider", "organization_id", "external_event_id",
                         name="uq_event_inbox_provider_org_ext"),
        Index("ix_event_inbox_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("inb"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(30))
    external_event_id: Mapped[str] = mapped_column(String(200))
    signature_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="received")  # received|processed|duplicate|dead
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # A PII-safe canonical envelope lets the worker materialize an accepted
    # provider delivery after the HTTP acknowledgement has been returned.
    canonical_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CanonicalEventRow(Base):
    __tablename__ = "canonical_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "external_event_id",
                         name="uq_canon_org_provider_ext"),
        Index("ix_canon_merchant_time", "merchant_id", "occurred_at"),
        Index("ix_canon_type", "type"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("evt"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
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
    organization_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True, nullable=True)
    reason: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_undispatched", "dispatched_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("obx"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    topic: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_pay_merchant_time", "merchant_id", "occurred_at"),
        Index("ix_pay_group", "group_id"),
        # Tenant-scoped identity: the same provider reference under a different
        # merchant is a DIFFERENT payment (blocks cross-tenant corruption).
        UniqueConstraint("merchant_id", "provider", "payment_ref",
                         name="uq_pay_merchant_provider_ref"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("pay"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
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
    refunded_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Order(Base):
    """Merchant order separate from individual payment attempts.

    A Razorpay Order can receive several payment attempts.  It becomes paid only
    after a captured payment/order.paid signal, and owns the one-business-effect
    fulfilment record.
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("merchant_id", "provider", "order_ref",
                         name="uq_order_merchant_provider_ref"),
        UniqueConstraint("merchant_id", "receipt", name="uq_order_merchant_receipt"),
        Index("ix_order_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("ord"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    order_ref: Mapped[str] = mapped_column(String(200))
    receipt: Mapped[str | None] = mapped_column(String(80), nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    amount_paid_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="created")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                  onupdate=_now)


class PaymentLink(Base):
    """A provider-shaped recovery link, kept separate from its resulting payment.

    A recovery link can be issued, partially paid, paid, cancelled or expired.
    Keeping that lifecycle in the ledger lets a revenue experiment attribute a
    captured payment to the bounded treatment that issued the link, without
    mistaking an ordinary eventual retry for recovered revenue.
    """

    __tablename__ = "payment_links"
    __table_args__ = (
        UniqueConstraint("merchant_id", "provider", "link_ref",
                         name="uq_payment_link_merchant_provider_ref"),
        UniqueConstraint("merchant_id", "reference_id",
                         name="uq_payment_link_merchant_reference"),
        Index("ix_payment_link_execution", "action_execution_id"),
        Index("ix_payment_link_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("plk"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="razorpay")
    link_ref: Mapped[str] = mapped_column(String(120))
    reference_id: Mapped[str] = mapped_column(String(80))
    order_id: Mapped[str] = mapped_column(String(40), ForeignKey("orders.id"), index=True)
    action_execution_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("action_executions.id"), nullable=True)
    payment_group_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    amount_paid_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(24), default="issued")
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                  onupdate=_now)


class Refund(Base):
    """Provider refund lifecycle, kept independent from the aggregate payment state."""

    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("merchant_id", "provider", "refund_ref",
                         name="uq_refund_merchant_provider_ref"),
        UniqueConstraint("merchant_id", "idempotency_key",
                         name="uq_refund_merchant_idempotency"),
        Index("ix_refund_payment_status", "payment_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("rfd"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    payment_id: Mapped[str] = mapped_column(String(40), ForeignKey("payments.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    refund_ref: Mapped[str] = mapped_column(String(200))
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="created")
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    receipt: Mapped[str | None] = mapped_column(String(80), nullable=True)
    speed_requested: Mapped[str | None] = mapped_column(String(20), nullable=True)
    speed_processed: Mapped[str | None] = mapped_column(String(20), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                  onupdate=_now)


class Fulfilment(Base):
    """One idempotent business effect per paid order."""

    __tablename__ = "fulfilments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_fulfilment_order"),
        UniqueConstraint("idempotency_key", name="uq_fulfilment_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("ful"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), ForeignKey("orders.id"), index=True)
    payment_id: Mapped[str] = mapped_column(String(40), ForeignKey("payments.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="fulfilled")
    idempotency_key: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(60), default="system")
    fulfilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CheckoutVerification(Base):
    """Server-side Razorpay Checkout verification evidence; never stores the secret."""

    __tablename__ = "checkout_verifications"
    __table_args__ = (
        UniqueConstraint("merchant_id", "provider", "payment_ref",
                         name="uq_checkout_verify_merchant_provider_payment"),
        Index("ix_checkout_verify_order", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("vfy"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), ForeignKey("orders.id"), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("payments.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(30))
    payment_ref: Mapped[str] = mapped_column(String(200))
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="rejected")
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
