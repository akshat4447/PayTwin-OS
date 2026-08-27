"""Chaos console (demo control): inject a seeded scenario into a live merchant."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.config import get_settings
from paytwin_api.deps import current_principal, err, get_db, require_write
from paytwin_api.models import Merchant, SimScenario
from paytwin_api.services.bus import publish_outbox
from paytwin_api.services.ingest import ingest_webhook
from paytwin_api.services.scenario_forecast import scenario_forecast
from paytwin_sim.generator import generate, to_webhook_payloads
from paytwin_sim.scenarios import SCENARIOS as SCENARIO_SPECS

router = APIRouter(prefix="/api/chaos", tags=["chaos"])
SCENARIOS = ("psp_degradation", "issuer_outage", "gateway_latency",
             "checkout_regression", "webhook_lag", "auth_failures", "rate_limit",
             "flash_sale_surge", "surge_bank_failure")


class ChaosBody(BaseModel):
    scope: str                 # merchant id
    duration_min: int = Field(default=15, ge=1, le=60)
    seed: int | None = Field(default=None, ge=1, le=2_147_483_647)


def _merchant_for_scope(db: Session, p: Principal, scope: str) -> Merchant | None:
    return (db.query(Merchant)
            .filter(Merchant.organization_id == p.organization_id,
                    Merchant.id == scope).one_or_none())


@router.get("/scenarios")
def scenarios(p: Principal = Depends(current_principal)) -> dict:
    """Catalog of sandbox drills; no production execution path exists."""
    return {"mode": "SANDBOX_ONLY", "scenarios": [
        {"id": scenario, "label": SCENARIO_SPECS[scenario].label,
         "cohort": SCENARIO_SPECS[scenario].cohort,
         "failure_multiplier": SCENARIO_SPECS[scenario].failure_multiplier,
         "traffic_multiplier": SCENARIO_SPECS[scenario].traffic_multiplier,
         "duration_min": SCENARIO_SPECS[scenario].duration_min}
        for scenario in SCENARIOS
    ]}


@router.post("/preview/{scenario}")
def preview(scenario: str, body: ChaosBody,
            p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)):
    """Read-only, explicit-assumption forecast before injecting sandbox traffic."""
    if scenario not in SCENARIOS:
        return err(404, "unknown_scenario", f"choose one of {SCENARIOS}")
    merchant = _merchant_for_scope(db, p, body.scope)
    if merchant is None:
        return err(404, "not_found", f"merchant {body.scope}")
    return scenario_forecast(db, merchant, scenario, duration_min=body.duration_min,
                             seed=body.seed or 20260827)


@router.post("/{scenario}")
def inject(scenario: str, body: ChaosBody,
           p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)):
    # Chaos writes synthetic traffic into the live ledger and can trigger
    # autopilot — demo/sandbox only, and only for admin roles (a write role
    # like ops_oncall must never be able to contaminate production data).
    if get_settings().is_prod:
        return err(403, "chaos_disabled_in_production",
                   "chaos injection is disabled outside demo/sandbox environments")
    if p.role not in ("org_admin", "risk_admin"):
        return err(403, "forbidden_role",
                   "chaos injection requires org_admin or risk_admin")
    require_write(p)
    if scenario not in SCENARIOS:
        return err(404, "unknown_scenario", f"choose one of {SCENARIOS}")
    merchant = _merchant_for_scope(db, p, body.scope)
    if merchant is None:
        return err(404, "not_found", f"merchant {body.scope}")
    from paytwin_sim.world import MERCHANTS as WORLD

    world_id = (merchant.config or {}).get("world_id")
    if world_id not in WORLD:
        return err(422, "missing_world_config",
                   "merchant config lacks a known world_id (e.g. 'mgro')")
    seed = body.seed or int(datetime.now(timezone.utc).timestamp()) % 2_147_483_647
    start = datetime.now(timezone.utc) - timedelta(minutes=body.duration_min // 2)
    forecast = scenario_forecast(db, merchant, scenario, duration_min=body.duration_min,
                                 seed=seed)
    namespace = f"chaos_{scenario}_{seed}_{int(start.timestamp())}"
    res = generate(world_id, hours=body.duration_min / 60.0, seed=seed, start=start,
        scenarios=[scenario], scenario_start_offset_min=0, event_namespace=namespace)
    secret = get_settings().webhook_secret_simulator
    ingested = 0
    for index, payload in enumerate(to_webhook_payloads(res.events), start=1):
        body_bytes = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body_bytes,
                                   hashlib.sha256).hexdigest()
        r = ingest_webhook(db, "simulator", merchant.id, body_bytes, sig, commit=False)
        ingested += 1 if r.status == 200 and not r.body.get("duplicate") else 0
        # Bounded transactions make a 4× surge usable live in the demo without
        # bypassing a single connector, inbox, or state-machine check.
        if index % 250 == 0:
            db.commit()
    spec = SCENARIO_SPECS[scenario]
    db.add(SimScenario(
        organization_id=p.organization_id, merchant_id=merchant.id, kind=scenario,
        seed=seed, start_at=start, end_at=start + timedelta(minutes=body.duration_min),
        cohort_issuer=spec.cohort.get("issuer"), cohort_method=spec.cohort.get("method"),
        cohort_psp=spec.cohort.get("psp"),
        params={"mode": "SANDBOX_INJECTION", "duration_min": body.duration_min,
                "namespace": namespace, "forecast": forecast["forecast"]},
        true_excess_failures=len(res.truth),
        true_rar_paise=sum(row["amount_paise"] for row in res.truth),
        true_top_cause={"kind": scenario, "cohort": spec.cohort},
    ))
    publish_outbox(db, p.organization_id, "chaos_injected",
                   {"scenario": scenario, "merchant": merchant.id,
                    "events_ingested": ingested})
    db.commit()
    return {"scenario": scenario, "merchant": merchant.id,
            "seed": seed, "mode": "SANDBOX_INJECTION",
            "events_generated": len(res.events), "events_ingested": ingested,
            "ground_truth_rows": len(res.truth), "forecast": forecast,
            "ground_truth": {"true_excess_failures": len(res.truth),
                               "true_rar_paise": sum(row["amount_paise"] for row in res.truth),
                               "top_cause": {"kind": scenario, "cohort": spec.cohort}}}
