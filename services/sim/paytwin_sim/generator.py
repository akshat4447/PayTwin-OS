"""Seeded payment-event generator with per-payment counterfactual ground truth.

Determinism: same seed + same config ⇒ identical events (tested). Each generated payment
carries `would_succeed` (counterfactual, no scenario) alongside the actual outcome, so
excess failures / true revenue-at-risk are measured, not guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from paytwin_sim import world
from paytwin_sim.scenarios import SCENARIOS, Scenario, matches

LATENCY_BASE_MS = {"upi_intent": 1400, "upi_collect": 2100, "card": 2600,
                   "netbanking": 3400, "mandate": 900}


@dataclass
class SimEvent:
    ext_id: str
    etype: str          # created|success|failed|timeout
    ref: str
    group_id: str
    epoch: int
    amount: int
    method: str
    issuer: str
    psp: str
    gateway: str
    latency_ms: int
    failure_class: str | None = None
    customer_ref: str = ""
    attempt_no: int = 1


@dataclass
class GenerationResult:
    events: list[SimEvent] = field(default_factory=list)
    truth: list[dict] = field(default_factory=list)  # ground-truth excess-failure records
    n_payments: int = 0
    n_failures: int = 0


def generate(merchant_id: str, hours: float, seed: int, start: datetime | None = None,
             scenarios: list[str] | None = None, scenario_start_offset_min: int | None = None,
             tpm_scale: float = 1.0) -> GenerationResult:
    cfg = world.MERCHANTS[merchant_id]
    start = start or datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
    rng = np.random.default_rng(seed)
    total_min = int(hours * 60)
    active = [SCENARIOS[s] for s in (scenarios or [])]
    s_start = scenario_start_offset_min if scenario_start_offset_min is not None else int(total_min * 0.6)

    out = GenerationResult()
    seq = 0

    for minute in range(total_min):
        t = start + timedelta(minutes=minute)
        hod = world.HOD[t.hour] * (1.0 - 0.2 * (t.weekday() >= 5))
        n = rng.poisson(cfg["tpm"] * tpm_scale * hod)
        for _ in range(n):
            seq += 1
            method = world.pick(rng, world.METHODS)
            issuer = world.pick(rng, world.ISSUERS)
            psp = world.pick(rng, world.PSPS)
            gateway = world.GATEWAYS[int(rng.integers(0, len(world.GATEWAYS)))]
            amount = int(max(9900, float(rng.lognormal(mean=np.log(cfg["aov_paise"]), sigma=0.55))))

            # baseline success probability (multiplicative health model)
            sr = (cfg["sr_base"] * world.METHODS[method]["sr"]
                  * world.ISSUERS[issuer]["sr"] * world.PSPS[psp]["sr"]) / 0.9
            sr = min(0.995, sr)
            would_succeed = float(rng.random()) < sr

            sc = _match_scenario(active, minute, s_start, method, issuer, psp, gateway)
            actual_sr = sr
            latency_ms = int(LATENCY_BASE_MS[method] * float(rng.lognormal(0, 0.35)))
            if sc is not None:
                actual_sr = 1.0 - min(0.92, (1.0 - sr) * sc.failure_multiplier)
                latency_ms = int(latency_ms * sc.latency_multiplier)
            succeeded = float(rng.random()) < actual_sr

            if succeeded:
                etype, fc = "success", None
            else:
                r = float(rng.random())
                if r < 0.06:
                    etype, fc = "timeout", "timeout"
                else:
                    etype = "failed"
                    fc = _failure_class(rng, sc, method)
            out.n_failures += etype in ("failed", "timeout")

            cust = f"c_{int(rng.integers(1, 60000)):05d}"
            ref = f"pay_{merchant_id}_{seq:07d}"
            grp = f"grp_{merchant_id}_{seq:07d}"
            out.n_payments += 1
            out.events.append(SimEvent(
                ext_id=f"evt_{merchant_id}_{seq:07d}_c", etype="created", ref=ref, group_id=grp,
                epoch=int(t.timestamp()), amount=amount, method=method, issuer=issuer,
                psp=psp, gateway=gateway, latency_ms=latency_ms, customer_ref=cust))
            out.events.append(SimEvent(
                ext_id=f"evt_{merchant_id}_{seq:07d}_t", etype=etype, ref=ref, group_id=grp,
                epoch=int(t.timestamp()) + int(latency_ms / 1000) + 1, amount=amount,
                method=method, issuer=issuer, psp=psp, gateway=gateway,
                latency_ms=latency_ms, failure_class=fc, customer_ref=cust))

            if sc is not None and would_succeed and not succeeded:
                out.truth.append(_truth_record(sc, t, amount, method, issuer, psp, gateway))
    return out


# __PART2__

def _match_scenario(active: list[Scenario], minute, s_start, method, issuer, psp, gateway):
    for sc in active:
        if s_start <= minute < s_start + sc.duration_min:
            dims = {"method": method, "issuer": issuer, "psp": psp, "gateway": gateway}
            if matches(dims, sc.cohort):
                return sc
    return None


def _failure_class(rng, sc, method):
    if sc is not None and sc.kind == "auth_failures":
        return "auth"
    if sc is not None and sc.kind == "rate_limit":
        return "rate_limit"
    if sc is not None and sc.kind == "gateway_latency":
        return "timeout"
    r = float(rng.random())
    if r < 0.55:
        return "issuer_decline"
    if r < 0.7:
        return "insufficient_funds"
    if r < 0.85 and method == "card":
        return "auth"
    return "psp_error"


def _truth_record(sc, t, amount, method, issuer, psp, gateway):
    return {"kind": sc.kind,
            "cohort": {"issuer": issuer, "method": method, "psp": psp, "gateway": gateway},
            "at": t.isoformat(), "amount_paise": amount}


def to_webhook_payloads(events: list[SimEvent], provider: str = "simulator") -> list[dict]:
    """SimEvent → signed-ready simulator webhook payloads (dialect of SimulatorConnector)."""
    out = []
    for e in events:
        data = {"payment_id": e.ref, "order_id": e.group_id, "amount": e.amount,
                "method": e.method, "issuer": e.issuer, "psp": e.psp, "gateway": e.gateway,
                "customer_ref": e.customer_ref, "group_id": e.group_id,
                "attempt_no": e.attempt_no, "latency_ms": e.latency_ms}
        if e.failure_class:
            data["error_reason"] = e.failure_class
        out.append({"event": {"created": "created", "success": "success", "failed": "failed",
                              "timeout": "timeout"}[e.etype],
                    "id": e.ext_id, "created_at": e.epoch, "data": data})
    return out

