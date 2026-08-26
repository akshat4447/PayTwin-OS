"""Measurement & system tables: integrations, experiments, outcomes, models, audit, ground truth."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Index,
                        Integer, String, JSON, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from paytwin_api.db import Base
from paytwin_api.models.tenancy import _id, _now


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("merchant_id", "provider", name="uq_int_merchant_provider"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("int"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="connected")
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)  # env ref, never the secret
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("exp"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("incidents.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|stopped
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"
    __table_args__ = (UniqueConstraint("experiment_id", "payment_group_id", name="uq_asgn_exp_group"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("asg"))
    experiment_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("experiments.id"), index=True)
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    payment_group_id: Mapped[str] = mapped_column(String(40), index=True)
    arm: Mapped[str] = mapped_column(String(12))  # control|treatment
    propensity: Mapped[float] = mapped_column(Float, default=0.5)
    action_execution_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("action_executions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# __PART2__


class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("assignment_id", name="uq_outcome_asgn"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("out"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("experiments.id"), index=True)
    assignment_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("experiment_assignments.id"))
    payment_group_id: Mapped[str] = mapped_column(String(40))
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    reward_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_ver"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("mdl"))
    name: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(30))
    stage: Mapped[str] = mapped_column(String(12), default="TRAINED", index=True)
    kind: Mapped[str] = mapped_column(String(60), default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    feature_version: Mapped[str] = mapped_column(String(30), default="fv1")
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_org_seq", "organization_id", "seq"),
        # Fork guard: two concurrent writers can never both claim the same
        # chain position (same prev_hash) for one organization.
        UniqueConstraint("organization_id", "prev_hash",
                         name="uq_audit_org_prev_hash"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(40), default=lambda: _id("aud"), unique=True)
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    actor: Mapped[str] = mapped_column(String(60))  # user/system/policy-engine
    actor_role: Mapped[str] = mapped_column(String(30), default="system")
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(60))
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(300), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SimScenario(Base):
    """Simulator ground truth — the evaluation anchor for detectors/RCA/RaR."""

    __tablename__ = "sim_scenarios"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("scn"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cohort_issuer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cohort_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cohort_psp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    true_excess_failures: Mapped[int] = mapped_column(Integer, default=0)
    true_rar_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    true_top_cause: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditHead(Base):
    """Per-org chain checkpoint: last seq/hash + record count.

    verify_chain() requires the live table to agree with this head, so deleting
    the newest record (or any tail record) breaks verification even though the
    remaining prefix still hashes correctly.
    """
    __tablename__ = "audit_heads"

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), default="")
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 onupdate=_now)
