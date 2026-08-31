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

from paytwin_api.models import ActionExecution, Experiment, ExperimentAssignment, Outcome


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
    # A control group must not carry an action execution reference. Keeping the
    # treatment rail explicit prevents a report from accidentally attributing
    # natural recoveries to PayTwin.
    a = ExperimentAssignment(experiment_id=experiment.id,
                             organization_id=experiment.organization_id,
                             payment_group_id=payment_group_id, arm=arm,
                             propensity=propensity,
                             action_execution_id=(action_execution_id if arm == "treatment" else None))
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
    control_rewards: list[int] = []
    treatment_rewards: list[int] = []
    execution_ids: set[str] = set()
    for a, o in rows:
        rec = bool(o and o.recovered)
        if a.arm == "control":
            c_n += 1
            c_rec += rec
            control_rewards.append(int((o.reward_paise if o else 0) or 0))
        else:
            t_n += 1
            t_rec += rec
            treatment_rewards.append(int((o.reward_paise if o else 0) or 0))
            if a.action_execution_id:
                execution_ids.add(a.action_execution_id)
    p_c = c_rec / c_n if c_n else 0.0
    p_t = t_rec / t_n if t_n else 0.0
    lift_abs = p_t - p_c
    # normal-approx 95% CI on the difference
    se = math.sqrt(max(p_t * (1 - p_t) / max(t_n, 1) + p_c * (1 - p_c) / max(c_n, 1), 1e-9))
    ci = 1.96 * se
    control_mean = sum(control_rewards) / c_n if c_n else 0.0
    treatment_mean = sum(treatment_rewards) / t_n if t_n else 0.0
    # Counterfactual money for the treated population. Raw treatment minus
    # control totals is biased whenever assignment sizes or payment amounts
    # differ; normalize per eligible group, then scale to treatment volume.
    incremental_gross = int(round((treatment_mean - control_mean) * t_n))

    def _sample_variance(values: list[int], mean: float) -> float:
        if len(values) < 2:
            return 0.0
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    money_se = math.sqrt(
        _sample_variance(treatment_rewards, treatment_mean) / max(t_n, 1)
        + _sample_variance(control_rewards, control_mean) / max(c_n, 1)
    )
    money_ci_width = 1.96 * money_se * t_n
    action_rows = (db.query(ActionExecution)
                   .filter(ActionExecution.id.in_(execution_ids)).all()
                   if execution_ids else [])
    action_cost = sum(int((row.outcome or {}).get("gross_action_cost_paise", 0) or 0)
                      for row in action_rows)
    stopping_events = [event for row in action_rows
                       for event in list((row.outcome or {}).get("stopping_events") or [])]
    net_incremental = incremental_gross - action_cost
    return {
        "experiment_id": experiment.id, "name": experiment.name,
        "n": {"control": c_n, "treatment": t_n},
        "recovery_rate": {"control": round(p_c, 4), "treatment": round(p_t, 4)},
        "lift_abs": round(lift_abs, 4),
        "lift_rel": round(lift_abs / p_c, 4) if p_c else None,
        "ci95": [round(lift_abs - ci, 4), round(lift_abs + ci, 4)],
        # Kept for backwards compatibility; it is now the correctly scaled
        # counterfactual amount, not a raw arm-total subtraction.
        "incremental_paise": incremental_gross,
        "incremental_gross_paise": incremental_gross,
        "incremental_gross_ci95_paise": [
            int(round(incremental_gross - money_ci_width)),
            int(round(incremental_gross + money_ci_width)),
        ],
        "intervention_cost_paise": action_cost,
        "net_incremental_paise": net_incremental,
        "net_incremental_ci95_paise": [
            int(round(incremental_gross - money_ci_width - action_cost)),
            int(round(incremental_gross + money_ci_width - action_cost)),
        ],
        "gross_recovered_paise": int(sum(treatment_rewards)),
        "control_expected_paise": int(round(control_mean * t_n)),
        "stopping_events": stopping_events,
        "audit_refs": [row.human_id for row in action_rows],
        "significant": abs(lift_abs) > ci and c_n > 0 and t_n > 0,
    }
