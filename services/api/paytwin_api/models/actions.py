"""Governance & execution: policies, policy decisions, action executions."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from paytwin_api.db import Base
from paytwin_api.models.tenancy import _id, _now


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("merchant_id", "human_id", "version", name="uq_policy_merchant_ver"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("pol"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    human_id: Mapped[str] = mapped_column(String(12))  # RP-007
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(12), default="live")  # draft|live|archived
    rules: Mapped[dict] = mapped_column(JSON, default=dict)  # typed predicate params
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (Index("ix_pdec_execution", "action_execution_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("pdc"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    action_execution_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("action_executions.id"), index=True)
    policy_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(120), default="")
    decision: Mapped[str] = mapped_column(String(20))  # allow|require_approval|block
    failed_rules: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionExecution(Base):
    __tablename__ = "action_executions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_exec_idem"),
        Index("ix_exec_incident", "incident_id"),
        Index("ix_exec_state", "state"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("act"))
    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("merchants.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("incidents.id"), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("action_candidates.id"), nullable=True)
    human_id: Mapped[str] = mapped_column(String(20), default="")  # ACT-####
    kind: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(24), default="CREATED")
    approved_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    connector: Mapped[str] = mapped_column(String(30), default="simulator")
    connector_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
