"""Twin: deterministic seeded Monte-Carlo over HTTP (same seed => same bytes)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db
from paytwin_api.models import Incident, Merchant, Payment, Simulation
from paytwin_ml.twin import run_twin

router = APIRouter(prefix="/api/twin", tags=["twin"])


class SimulateBody(BaseModel):
    scope: str
    scenario: str = "retry_burst"
    alloc_pct: int = 25
    duration_min: int = 30
    seed: int | None = None


@router.post("/simulate")
def simulate(body: SimulateBody, p: Principal = Depends(current_principal),
             db: Session = Depends(get_db)):
    seed = body.seed if body.seed is not None else 42
    merchant = (db.query(Merchant)
                .filter(Merchant.organization_id == p.organization_id,
                        Merchant.id == body.scope).one_or_none())
    if merchant is None:
        return err(404, "not_found", f"merchant {body.scope}")
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=max(60, body.duration_min * 2))
    rows = (db.query(Payment).filter(Payment.merchant_id == merchant.id,
                                     Payment.status.in_(("failed", "timeout")))
            .all())
    recent = [r for r in rows if _utc(r) >= since]
    src = recent or rows[:200]
    fp = [{"amount": r.amount_paise,
           "age_min": max(0.0, (now - _utc(r)).total_seconds() / 60.0)}
          for r in src[:200]]
    industry = (merchant.config or {}).get("industry", "grocery")
    twin = run_twin(merchant.id, industry, fp, body.scenario, seed=seed,
                    trials=400, alloc_pct=body.alloc_pct,
                    duration_min=body.duration_min)
    params_hash = hashlib.sha256(json.dumps({
        "scope": merchant.id, "scenario": body.scenario,
        "alloc_pct": body.alloc_pct, "duration_min": body.duration_min,
        "n": len(fp), "seed": seed}, sort_keys=True).encode()).hexdigest()[:32]
    existing = (db.query(Simulation)
                .filter(Simulation.organization_id == p.organization_id,
                        Simulation.merchant_id == merchant.id,
                        Simulation.incident_id.is_(None),
                        Simulation.scenario == body.scenario,
                        Simulation.seed == seed,
                        Simulation.params_hash == params_hash)
                .one_or_none())
    if existing is None:
        db.add(Simulation(
            organization_id=p.organization_id, merchant_id=merchant.id,
            incident_id=None, scenario=body.scenario, seed=seed, trials=400,
            params={"alloc_pct": body.alloc_pct,
                    "duration_min": body.duration_min, "inputs": len(fp)},
            params_hash=params_hash,
            result={"p50_paise": twin.p50_paise, "lo_paise": twin.lo_paise,
                    "hi_paise": twin.hi_paise, "lift_pct": twin.lift_pct,
                    "traj": twin.traj, "cost_paise": twin.cost_paise}))
        db.commit()
    return {
        "scenario": twin.scenario, "p50_paise": twin.p50_paise,
        "lo_paise": twin.lo_paise, "hi_paise": twin.hi_paise,
        "lift_pct": twin.lift_pct, "traj": twin.traj,
        "trials": twin.trials, "seed": twin.seed,
        "cost_paise": twin.cost_paise, "policy_compat": twin.policy_compat,
        "per_scenario": [],
    }


def _utc(r: Payment) -> datetime:
    dt = r.occurred_at
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt