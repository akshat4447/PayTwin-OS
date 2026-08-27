"""payment integrity entities: orders, refunds, fulfilment and Checkout proof

Revision ID: d8e4c2a9b517
Revises: c7d2e8a41b90
Create Date: 2026-08-27 14:30:00

Separates an order's business lifecycle from individual payment attempts and
records provider refunds/Checkout verification as immutable financial evidence.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8e4c2a9b517"
down_revision = "c7d2e8a41b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as b:
        b.add_column(sa.Column("refunded_amount_paise", sa.BigInteger(), nullable=False,
                               server_default="0"))

    with op.batch_alter_table("integrations") as b:
        b.add_column(sa.Column("api_secret_ref", sa.String(length=120), nullable=True))
        b.add_column(sa.Column("previous_secret_ref", sa.String(length=120), nullable=True))
        b.add_column(sa.Column("previous_secret_expires_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("last_healthcheck_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("merchant_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("order_ref", sa.String(length=200), nullable=False),
        sa.Column("receipt", sa.String(length=80), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("amount_paid_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_order_org"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name="fk_order_merchant"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "provider", "order_ref",
                            name="uq_order_merchant_provider_ref"),
        sa.UniqueConstraint("merchant_id", "receipt", name="uq_order_merchant_receipt"),
    )
    op.create_index("ix_order_merchant_status", "orders", ["merchant_id", "status"])

    op.create_table(
        "refunds",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("merchant_id", sa.String(length=40), nullable=False),
        sa.Column("payment_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("refund_ref", sa.String(length=200), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("idempotency_key", sa.String(length=80), nullable=True),
        sa.Column("receipt", sa.String(length=80), nullable=True),
        sa.Column("speed_requested", sa.String(length=20), nullable=True),
        sa.Column("speed_processed", sa.String(length=20), nullable=True),
        sa.Column("failure_reason", sa.String(length=300), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_refund_org"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name="fk_refund_merchant"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_refund_payment"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "provider", "refund_ref",
                            name="uq_refund_merchant_provider_ref"),
        sa.UniqueConstraint("merchant_id", "idempotency_key",
                            name="uq_refund_merchant_idempotency"),
    )
    op.create_index("ix_refund_payment_status", "refunds", ["payment_id", "status"])

    op.create_table(
        "fulfilments",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("merchant_id", sa.String(length=40), nullable=False),
        sa.Column("order_id", sa.String(length=40), nullable=False),
        sa.Column("payment_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="fulfilled"),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False, server_default="system"),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_fulfilment_org"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name="fk_fulfilment_merchant"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_fulfilment_order"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_fulfilment_payment"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_fulfilment_order"),
        sa.UniqueConstraint("idempotency_key", name="uq_fulfilment_idempotency"),
    )

    op.create_table(
        "checkout_verifications",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("merchant_id", sa.String(length=40), nullable=False),
        sa.Column("order_id", sa.String(length=40), nullable=False),
        sa.Column("payment_id", sa.String(length=40), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("payment_ref", sa.String(length=200), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="rejected"),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_checkout_verify_org"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name="fk_checkout_verify_merchant"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_checkout_verify_order"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_checkout_verify_payment"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "provider", "payment_ref",
                            name="uq_checkout_verify_merchant_provider_payment"),
    )
    op.create_index("ix_checkout_verify_order", "checkout_verifications", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_checkout_verify_order", table_name="checkout_verifications")
    op.drop_table("checkout_verifications")
    op.drop_table("fulfilments")
    op.drop_index("ix_refund_payment_status", table_name="refunds")
    op.drop_table("refunds")
    op.drop_index("ix_order_merchant_status", table_name="orders")
    op.drop_table("orders")
    with op.batch_alter_table("integrations") as b:
        b.drop_column("last_healthcheck_at")
        b.drop_column("last_webhook_at")
        b.drop_column("previous_secret_expires_at")
        b.drop_column("previous_secret_ref")
        b.drop_column("api_secret_ref")
    with op.batch_alter_table("payments") as b:
        b.drop_column("refunded_amount_paise")
