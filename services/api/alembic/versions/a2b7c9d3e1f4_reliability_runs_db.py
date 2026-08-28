"""persist Reliability Lab evidence in the primary database

Revision ID: a2b7c9d3e1f4
Revises: f1a8b3c4d9e0
Create Date: 2026-08-28 11:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2b7c9d3e1f4"
down_revision = "f1a8b3c4d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reliability_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False, server_default="SANDBOX_FIXTURE"),
        sa.Column("gate_verdict", sa.String(length=20), nullable=False, server_default="UNKNOWN"),
        sa.Column("gate_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"],
                                name="fk_reliability_runs_organization_id_organizations"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_reliability_run_id"),
    )
    op.create_index("ix_reliability_runs_run_id", "reliability_runs", ["run_id"])
    op.create_index("ix_reliability_runs_organization_id", "reliability_runs", ["organization_id"])
    op.create_index("ix_reliability_runs_org_at", "reliability_runs",
                    ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_reliability_runs_org_at", table_name="reliability_runs")
    op.drop_index("ix_reliability_runs_organization_id", table_name="reliability_runs")
    op.drop_index("ix_reliability_runs_run_id", table_name="reliability_runs")
    op.drop_table("reliability_runs")
