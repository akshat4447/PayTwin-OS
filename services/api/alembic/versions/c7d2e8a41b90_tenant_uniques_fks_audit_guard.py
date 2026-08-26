"""tenant-scoped uniques, FKs, audit fork guard + checkpoint

Revision ID: c7d2e8a41b90
Revises: b47531c6f9e6
Create Date: 2026-08-26 13:30:00

Functional changes:
- Payments unique per (merchant, provider, payment_ref) — blocks cross-tenant
  payment corruption via reused provider references.
- Inbox/canonical idempotency scoped per (provider, organization, external id).
- Audit fork guard UNIQUE(organization_id, prev_hash) + audit_heads checkpoint.
- policy_decisions.policy_version widened (carries contributing policy versions).
- Foreign keys across the core relations (defense in depth; see infra/rls.sql
  for the PostgreSQL RLS companion policies).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7d2e8a41b90"
down_revision = "b47531c6f9e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_heads",
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("last_seq", sa.Integer(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"],
                                name="fk_audit_head_org"),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_audit_heads")),
    )

    with op.batch_alter_table("event_inbox") as b:
        b.drop_constraint("uq_event_inbox_provider_ext", type_="unique")
        b.create_unique_constraint("uq_event_inbox_provider_org_ext",
                                   ["provider", "organization_id", "external_event_id"])
        b.create_foreign_key("fk_inbox_org", "organizations",
                             ["organization_id"], ["id"])

    with op.batch_alter_table("canonical_events") as b:
        b.drop_constraint("uq_canon_provider_ext", type_="unique")
        b.create_unique_constraint("uq_canon_org_provider_ext",
                                   ["organization_id", "provider", "external_event_id"])
        b.create_foreign_key("fk_canon_org", "organizations",
                             ["organization_id"], ["id"])
        b.create_foreign_key("fk_canon_merchant", "merchants",
                             ["merchant_id"], ["id"])

    with op.batch_alter_table("payments") as b:
        b.drop_constraint("uq_pay_provider_ref", type_="unique")
        b.create_unique_constraint("uq_pay_merchant_provider_ref",
                                   ["merchant_id", "provider", "payment_ref"])
        b.create_foreign_key("fk_pay_org", "organizations",
                             ["organization_id"], ["id"])
        b.create_foreign_key("fk_pay_merchant", "merchants",
                             ["merchant_id"], ["id"])

    with op.batch_alter_table("audit_records") as b:
        b.create_unique_constraint("uq_audit_org_prev_hash",
                                   ["organization_id", "prev_hash"])
        b.create_foreign_key("fk_audit_org", "organizations",
                             ["organization_id"], ["id"])

    with op.batch_alter_table("policy_decisions") as b:
        b.alter_column("policy_version", existing_type=sa.String(length=30),
                       type_=sa.String(length=120), existing_nullable=True)
        b.create_foreign_key("fk_pdec_org", "organizations",
                             ["organization_id"], ["id"])
        b.create_foreign_key("fk_pdec_merchant", "merchants",
                             ["merchant_id"], ["id"])
        b.create_foreign_key("fk_pdec_exec", "action_executions",
                             ["action_execution_id"], ["id"])

    _add_simple_fks()


def _add_simple_fks() -> None:
    """Remaining FK coverage (batch mode recreates tables on sqlite)."""
    with op.batch_alter_table("merchants") as b:
        b.create_foreign_key("fk_merchant_org", "organizations",
                             ["organization_id"], ["id"])
    with op.batch_alter_table("users") as b:
        b.create_foreign_key("fk_user_org", "organizations",
                             ["organization_id"], ["id"])
    with op.batch_alter_table("api_keys") as b:
        b.create_foreign_key("fk_apikey_org", "organizations",
                             ["organization_id"], ["id"])
    with op.batch_alter_table("outbox") as b:
        b.create_foreign_key("fk_outbox_org", "organizations",
                             ["organization_id"], ["id"])
    with op.batch_alter_table("dead_letters") as b:
        b.create_foreign_key("fk_dlq_org", "organizations",
                             ["organization_id"], ["id"])
    with op.batch_alter_table("predictions") as b:
        b.create_foreign_key("fk_pred_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_pred_merchant", "merchants", ["merchant_id"], ["id"])
        b.create_foreign_key("fk_pred_payment", "payments", ["payment_id"], ["id"])
    with op.batch_alter_table("incidents") as b:
        b.create_foreign_key("fk_inc_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_inc_merchant", "merchants", ["merchant_id"], ["id"])
    with op.batch_alter_table("incident_evidence") as b:
        b.create_foreign_key("fk_evid_incident", "incidents", ["incident_id"], ["id"])
    with op.batch_alter_table("root_cause_candidates") as b:
        b.create_foreign_key("fk_rcc_incident", "incidents", ["incident_id"], ["id"])
    with op.batch_alter_table("simulations") as b:
        b.create_foreign_key("fk_sim_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_sim_merchant", "merchants", ["merchant_id"], ["id"])
        b.create_foreign_key("fk_sim_incident", "incidents", ["incident_id"], ["id"])
    with op.batch_alter_table("action_candidates") as b:
        b.create_foreign_key("fk_cand_incident", "incidents", ["incident_id"], ["id"])
        b.create_foreign_key("fk_cand_sim", "simulations", ["simulation_id"], ["id"])
    with op.batch_alter_table("policies") as b:
        b.create_foreign_key("fk_pol_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_pol_merchant", "merchants", ["merchant_id"], ["id"])
    with op.batch_alter_table("action_executions") as b:
        b.create_foreign_key("fk_exec_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_exec_merchant", "merchants", ["merchant_id"], ["id"])
        b.create_foreign_key("fk_exec_incident", "incidents", ["incident_id"], ["id"])
        b.create_foreign_key("fk_exec_candidate", "action_candidates",
                             ["candidate_id"], ["id"])
    with op.batch_alter_table("integrations") as b:
        b.create_foreign_key("fk_int_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_int_merchant", "merchants", ["merchant_id"], ["id"])
    with op.batch_alter_table("experiments") as b:
        b.create_foreign_key("fk_exp_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_exp_merchant", "merchants", ["merchant_id"], ["id"])
        b.create_foreign_key("fk_exp_incident", "incidents", ["incident_id"], ["id"])
    with op.batch_alter_table("experiment_assignments") as b:
        b.create_foreign_key("fk_asgn_exp", "experiments", ["experiment_id"], ["id"])
        b.create_foreign_key("fk_asgn_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_asgn_exec", "action_executions",
                             ["action_execution_id"], ["id"])
    with op.batch_alter_table("outcomes") as b:
        b.create_foreign_key("fk_out_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_out_exp", "experiments", ["experiment_id"], ["id"])
        b.create_foreign_key("fk_out_asgn", "experiment_assignments",
                             ["assignment_id"], ["id"])
    with op.batch_alter_table("sim_scenarios") as b:
        b.create_foreign_key("fk_scn_org", "organizations", ["organization_id"], ["id"])
        b.create_foreign_key("fk_scn_merchant", "merchants", ["merchant_id"], ["id"])


def downgrade() -> None:
    op.drop_table("audit_heads")
    with op.batch_alter_table("payments") as b:
        b.drop_constraint("uq_pay_merchant_provider_ref", type_="unique")
        b.create_unique_constraint("uq_pay_provider_ref", ["provider", "payment_ref"])
    with op.batch_alter_table("event_inbox") as b:
        b.drop_constraint("uq_event_inbox_provider_org_ext", type_="unique")
        b.create_unique_constraint("uq_event_inbox_provider_ext",
                                   ["provider", "external_event_id"])
    with op.batch_alter_table("canonical_events") as b:
        b.drop_constraint("uq_canon_org_provider_ext", type_="unique")
        b.create_unique_constraint("uq_canon_provider_ext",
                                   ["provider", "external_event_id"])
    with op.batch_alter_table("policy_decisions") as b:
        b.alter_column("policy_version", existing_type=sa.String(length=120),
                       type_=sa.String(length=30), existing_nullable=True)
    # FK rollback is intentionally not enumerated: dropping FKs is a no-op for
    # correctness and batch-dropping every constraint is high-risk churn.
