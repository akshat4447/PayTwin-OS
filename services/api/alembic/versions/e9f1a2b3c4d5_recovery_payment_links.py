"""add local-test payment-link recovery lifecycle

Revision ID: e9f1a2b3c4d5
Revises: a2b7c9d3e1f4
Create Date: 2026-08-31 12:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9f1a2b3c4d5"
down_revision = "a2b7c9d3e1f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_links",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("merchant_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="razorpay"),
        sa.Column("link_ref", sa.String(length=120), nullable=False),
        sa.Column("reference_id", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.String(length=40), nullable=False),
        sa.Column("action_execution_id", sa.String(length=40), nullable=True),
        sa.Column("payment_group_id", sa.String(length=40), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("amount_paid_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="issued"),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="whatsapp"),
        sa.Column("reminder_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"],
                                name="fk_payment_links_organization"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"],
                                name="fk_payment_links_merchant"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"],
                                name="fk_payment_links_order"),
        sa.ForeignKeyConstraint(["action_execution_id"], ["action_executions.id"],
                                name="fk_payment_links_execution"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "provider", "link_ref",
                            name="uq_payment_link_merchant_provider_ref"),
        sa.UniqueConstraint("merchant_id", "reference_id",
                            name="uq_payment_link_merchant_reference"),
    )
    op.create_index("ix_payment_link_execution", "payment_links", ["action_execution_id"])
    op.create_index("ix_payment_link_status", "payment_links", ["merchant_id", "status"])
    op.create_index("ix_payment_links_organization_id", "payment_links", ["organization_id"])
    op.create_index("ix_payment_links_merchant_id", "payment_links", ["merchant_id"])
    op.create_index("ix_payment_links_order_id", "payment_links", ["order_id"])
    op.create_index("ix_payment_links_payment_group_id", "payment_links", ["payment_group_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_links_payment_group_id", table_name="payment_links")
    op.drop_index("ix_payment_links_order_id", table_name="payment_links")
    op.drop_index("ix_payment_links_merchant_id", table_name="payment_links")
    op.drop_index("ix_payment_links_organization_id", table_name="payment_links")
    op.drop_index("ix_payment_link_status", table_name="payment_links")
    op.drop_index("ix_payment_link_execution", table_name="payment_links")
    op.drop_table("payment_links")
