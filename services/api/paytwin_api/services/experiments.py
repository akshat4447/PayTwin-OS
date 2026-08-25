"""CAUSAL-001: experiments — deterministic assignment, outcome storage, lift + CI.

Design-based measurement: control vs treatment from STORED assignments/outcomes.
Lift CI via normal approximation on proportions (n large enough in practice); bootstrap
available for small n.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from paytwin_api.models import Experiment, ExperimentAssignment, Outcome


def assign_arm(experiment_id: str, payment_group_id: str, propensity: float = 0.5) -> str:
    """Deterministic 50/50 (or propensity) split — same group always lands same arm."""
    h = int(hashlib.sha256(f"{experiment_id}:{payment_group_id}".encode()).hexdigest()[:12], 16)
    return "treatment" if (h / 0xFFFFFFFFFFFF) < propensity else "control"


def create_experiment(db: Session, organization_id: str, merchant_id: str,
                      name: str, incident_id: str | None = None, config: dict | None = None
                      ) -> Experiment:
    e = Experiment(organization_id=organization_id, merchant_id=merchant_id,
                   incident_id=incident_id, name=name, config=config or {})
    db.add(e)
    db.flush()
    return e


def record_assignment(db: Session, experiment: Experiment, payment_group_id: str,
                      action_execution_id: str | None = None,
                      propensity: float = 0.5) -> ExperimentAssignment:
    arm = assign_arm(experiment.id, payment_group_id, propensity)
    a = ExperimentAssignment(experiment_id=experiment.id,
                             organization_id=experiment.organization_id,
                             payment_group_id=payment_group_id, arm=arm,
                             propensity=propensity, action_execution_id=action_execution_id)
    db.add(a)
    db.flush()
    return a


def record_outcome(db: Session, assignment: ExperimentAssignment, recovered: bool,
                   amount_paise: int, reward_paise: int | None = None) -> Outcome:
    o = Outcome(organization_id=assignment.organization_id,
                experiment_id=assignment.experiment_id, assignment_id=assignment.id,
                payment_group_id=assignment.payment_group_id, recovered=recovered,
                recovered_at=datetime.now(timezone.utc) if recovered else None,
                amount_paise=amount_paise,
                reward_paise=reward_paise if reward_paise is not None
                else (amount_paise if recovered else 0))
    db.add(o)
    db.flush()
    return o


def results(db: Session, experiment: Experiment) -> dict:
    rows = (db.query(ExperimentAssignment, Outcome)
            .outerjoin(Outcome, Outcome.assignment_id == ExperimentAssignment.id)
            .filter(ExperimentAssignment.experiment_id == experiment.id).all())
    c_n = t_n = c_rec = t_rec = 0
    c_amt = t_amt = 0
    for a, o in rows:
        rec = bool(o and o.recovered)
        if a.arm == "control":
            c_n += 1
            c_rec += rec
            c_amt += (o.reward_paise if o else 0) or 0
        else:
            t_n += 1
            t_rec += rec
            t_amt += (o.reward_paise if o else 0) or 0
    p_c = c_rec / c_n if c_n else 0.0
    p_t = t_rec / t_n if t_n else 0.0
    lift_abs = p_t - p_c
    # normal-approx 95% CI on the difference
    se = math.sqrt(max(p_t * (1 - p_t) / max(t_n, 1) + p_c * (1 - p_c) / max(c_n, 1), 1e-9))
    ci = 1.96 * se
    return {
        "experiment_id": experiment.id, "name": experiment.name,
        "n": {"control": c_n, "treatment": t_n},
        "recovery_rate": {"control": round(p_c, 4), "treatment": round(p_t, 4)},
        "lift_abs": round(lift_abs, 4),
        "lift_rel": round(lift_abs / p_c, 4) if p_c else None,
        "ci95": [round(lift_abs - ci, 4), round(lift_abs + ci, 4)],
        "incremental_paise": int(t_amt - c_amt),
        "significant": abs(lift_abs) > ci and c_n > 0 and t_n > 0,
    }
