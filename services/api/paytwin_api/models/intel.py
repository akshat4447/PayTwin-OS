"""Intelligence tables: predictions, incidents + evidence + RCA, simulations, candidates."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from paytwin_api.db import Base
from paytwin_api.models.tenancy import _id, _now


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (Index("ix_pred_payment", "payment_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("prd"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    merchant_id: Mapped[str] = mapped_column(String(40), index=True)
    payment_id: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(60))
    feature_version: Mapped[str] = mapped_column(String(30))
    p_success: Mapped[float] = mapped_column(Float)
    failure_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    uncertainty: Mapped[float] = mapped_column(Float, default=0.0)
    features_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("organization_id", "human_id", name="uq_incident_org_human"),
        Index("ix_incident_merchant_state", "merchant_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("inc"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    merchant_id: Mapped[str] = mapped_column(String(40), index=True)
    human_id: Mapped[str] = mapped_column(String(20))  # INC-2481
    sev: Mapped[str] = mapped_column(String(4), default="P2")
    title: Mapped[str] = mapped_column(String(200))
    cohort_issuer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cohort_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cohort_psp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cohort_gateway: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="DETECTED", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_sr_bp: Mapped[int] = mapped_column(Integer, default=0)
    current_sr_bp: Mapped[int] = mapped_column(Integer, default=0)
    rar_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    rar_lo_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    rar_hi_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    affected_payments: Mapped[int] = mapped_column(Integer, default=0)
    affected_customers: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    scenario_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)

    def cohort(self) -> dict:
        return {"issuer": self.cohort_issuer, "method": self.cohort_method,
                "psp": self.cohort_psp, "gateway": self.cohort_gateway}


# __PART2__


class IncidentEvidence(Base):
    __tablename__ = "incident_evidence"
    __table_args__ = (Index("ix_evid_incident", "incident_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("evd"))
    incident_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(30))  # detector|rca|simulation|metric|policy|action|experiment
    ref: Mapped[str] = mapped_column(String(120))  # evidence id used by commander chips
    summary: Mapped[str] = mapped_column(String(500))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RootCauseCandidate(Base):
    __tablename__ = "root_cause_candidates"
    __table_args__ = (Index("ix_rcc_incident", "incident_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("rcc"))
    incident_id: Mapped[str] = mapped_column(String(40))
    edge_issuer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    edge_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    edge_psp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    counterfactual_share: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Simulation(Base):
    __tablename__ = "simulations"
    __table_args__ = (
        UniqueConstraint("incident_id", "scenario", "seed", "params_hash", name="uq_sim_reproducible"),
        Index("ix_sim_merchant", "merchant_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("sim"))
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    merchant_id: Mapped[str] = mapped_column(String(40), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    scenario: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    trials: Mapped[int] = mapped_column(Integer, default=400)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    params_hash: Mapped[str] = mapped_column(String(32), default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)  # p50/lo/hi/lift/traj/cost
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionCandidate(Base):
    __tablename__ = "action_candidates"
    __table_args__ = (Index("ix_cand_incident", "incident_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _id("cnd"))
    incident_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(30))  # ActionKind
    label: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(String(400), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    p_succ_delta: Mapped[float] = mapped_column(Float, default=0.0)
    value_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    risk_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    ev_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    simulation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
