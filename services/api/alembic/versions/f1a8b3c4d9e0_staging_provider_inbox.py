"""staging provider routing and durable inbox envelope

Revision ID: f1a8b3c4d9e0
Revises: d8e4c2a9b517
Create Date: 2026-08-28 10:00:00

Adds opaque integration webhook routes and the normalized envelope needed to
acknowledge provider callbacks before a worker materializes side effects.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a8b3c4d9e0"
down_revision = "d8e4c2a9b517"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("integrations") as b:
        b.add_column(sa.Column("environment", sa.String(length=30), nullable=False,
                               server_default="local_test"))
        b.add_column(sa.Column("webhook_route_token", sa.String(length=80), nullable=True))
        b.create_unique_constraint("uq_integrations_webhook_route_token",
                                   ["webhook_route_token"])
        b.create_index("ix_integrations_webhook_route_token", ["webhook_route_token"])
    with op.batch_alter_table("event_inbox") as b:
        b.add_column(sa.Column("merchant_id", sa.String(length=40), nullable=True))
        b.add_column(sa.Column("canonical_payload", sa.JSON(), nullable=False,
                               server_default=sa.text("'{}'")))
        b.create_foreign_key("fk_event_inbox_merchant", "merchants", ["merchant_id"], ["id"])
        b.create_index("ix_event_inbox_merchant_id", ["merchant_id"])


def downgrade() -> None:
    with op.batch_alter_table("event_inbox") as b:
        b.drop_index("ix_event_inbox_merchant_id")
        b.drop_constraint("fk_event_inbox_merchant", type_="foreignkey")
        b.drop_column("canonical_payload")
        b.drop_column("merchant_id")
    with op.batch_alter_table("integrations") as b:
        b.drop_index("ix_integrations_webhook_route_token")
        b.drop_constraint("uq_integrations_webhook_route_token", type_="unique")
        b.drop_column("webhook_route_token")
        b.drop_column("environment")
