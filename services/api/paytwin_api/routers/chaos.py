"""Chaos console (demo control): inject a seeded scenario into a live merchant."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.config import get_settings
from paytwin_api.deps import current_principal, err, get_db, require_write
from paytwin_api.models import Merchant
from paytwin_api.services.bus import publish_outbox
from paytwin_api.services.ingest import ingest_webhook
from paytwin_sim.generator import generate, to_webhook_payloads

router = APIRouter(prefix="/api/chaos", tags=["chaos"])
SCENARIOS = ("psp_degradation", "issuer_outage", "gateway_latency",
             "checkout_regression", "webhook_lag", "auth_failures", "rate_limit")


class ChaosBody(BaseModel):
    scope: str                 # merchant id
    duration_min: int = 15


@router.post("/{scenario}")
def inject(scenario: str, body: ChaosBody,
           p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)):
    require_write(p)
    if scenario not in SCENARIOS:
        return err(404, "unknown_scenario", f"choose one of {SCENARIOS}")
    merchant = (db.query(Merchant)
                .filter(Merchant.organization_id == p.organization_id,
                        Merchant.id == body.scope).one_or_none())
    if merchant is None:
        return err(404, "not_found", f"merchant {body.scope}")
    from paytwin_sim.world import MERCHANTS as WORLD

    world_id = (merchant.config or {}).get("world_id")
    if world_id not in WORLD:
        return err(422, "missing_world_config",
                   "merchant config lacks a known world_id (e.g. 'mgro')")
    start = datetime.now(timezone.utc) - timedelta(minutes=body.duration_min // 2)
    res = generate(world_id, hours=body.duration_min / 60.0, seed=int(
        datetime.now(timezone.utc).timestamp()) % 100000, start=start,
        scenarios=[scenario], scenario_start_offset_min=0)
    secret = get_settings().webhook_secret_simulator
    ingested = 0
    for payload in to_webhook_payloads(res.events):
        body_bytes = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body_bytes,
                                   hashlib.sha256).hexdigest()
        r = ingest_webhook(db, "simulator", merchant.id, body_bytes, sig)
        ingested += 1 if r.status == 200 and not r.body.get("duplicate") else 0
    publish_outbox(db, p.organization_id, "chaos_injected",
                   {"scenario": scenario, "merchant": merchant.id,
                    "events_ingested": ingested})
    db.commit()
    return {"scenario": scenario, "merchant": merchant.id,
            "events_generated": len(res.events), "events_ingested": ingested,
            "ground_truth_rows": len(res.truth)}