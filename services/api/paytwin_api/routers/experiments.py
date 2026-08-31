"""Experiments: list + detail with arms/lift/CI/incremental rupees."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db
from paytwin_api.models import Experiment
from paytwin_api.services.experiments import results as experiment_results

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.get("")
def list_experiments(p: Principal = Depends(current_principal),
                     db: Session = Depends(get_db), scope: str | None = None):
    q = db.query(Experiment).filter(Experiment.organization_id == p.organization_id)
    if scope and scope != "org":
        q = q.filter(Experiment.merchant_id == scope)
    rows = q.order_by(Experiment.started_at.desc()).limit(50).all()
    return [{"id": e.id, "name": e.name, "status": e.status,
             "started_at": e.started_at.isoformat(),
             # The list view is used in the operating workspace, so it includes
             # the same measured treatment/control summary as the detail route.
             "summary": experiment_results(db, e)} for e in rows]


@router.get("/{experiment_id}")
def detail(experiment_id: str, p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)):
    e = (db.query(Experiment)
         .filter(Experiment.organization_id == p.organization_id,
                 Experiment.id == experiment_id).one_or_none())
    if e is None:
        return err(404, "not_found", f"experiment {experiment_id}")
    r = experiment_results(db, e)
    return {"id": e.id, "name": e.name, "status": e.status,
            "started_at": e.started_at.isoformat(), **r,
            "lift_pct": round(r.get("lift_abs", 0.0) * 100, 2)}
