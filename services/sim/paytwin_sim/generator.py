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
             tpm_scale: float = 1.0, event_namespace: str = "") -> GenerationResult:
    cfg = world.MERCHANTS[merchant_id]
    start = start or datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
    rng = np.random.default_rng(seed)
    total_min = int(hours * 60)
    active = [SCENARIOS[s] for s in (scenarios or [])]
    s_start = scenario_start_offset_min if scenario_start_offset_min is not None else int(total_min * 0.6)

    out = GenerationResult()
    seq = 0
    # A namespace makes independently injected sandbox runs independent at both
    # the webhook-id and payment-id layers. The blank default preserves stable
    # historical/demo fixtures and their expected ids.
    namespace = "".join(c if c.isalnum() or c in "_-" else "_"
                        for c in event_namespace)[:60]
    ref_prefix = f"{merchant_id}_{namespace}_" if namespace else f"{merchant_id}_"

    for minute in range(total_min):
        t = start + timedelta(minutes=minute)
        hod = world.HOD[t.hour] * (1.0 - 0.2 * (t.weekday() >= 5))
        active_now = _active_scenarios(active, minute, s_start)
        # Traffic pressure applies before payment dimensions are chosen. It can
        # coexist with a targeted bank/PSP failure in the same scenario.
        traffic_scale = float(np.prod([s.traffic_multiplier for s in active_now],
                                      dtype=float)) if active_now else 1.0
        n = rng.poisson(cfg["tpm"] * tpm_scale * hod * traffic_scale)
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

            matched = _matching_scenarios(active_now, method, issuer, psp, gateway)
            # Preserve the historical scenario-library contract: overlapping
            # independent fault drills use the first matching fault rather than
            # multiplying failure rates together.  Traffic pressure is already
            # applied above and can coexist with that one targeted fault. The
            # compound surge+bank drill is represented as one explicit Scenario.
            fault_drivers = [s for s in matched
                             if s.failure_multiplier != 1.0 or s.latency_multiplier != 1.0]
            matched = fault_drivers[:1]
            actual_sr = sr
            latency_ms = int(LATENCY_BASE_MS[method] * float(rng.lognormal(0, 0.35)))
            if matched:
                failure_multiplier = float(np.prod([s.failure_multiplier for s in matched],
                                                    dtype=float))
                latency_multiplier = float(np.prod([s.latency_multiplier for s in matched],
                                                    dtype=float))
                actual_sr = 1.0 - min(0.92, (1.0 - sr) * failure_multiplier)
                latency_ms = int(latency_ms * latency_multiplier)
            succeeded = float(rng.random()) < actual_sr

            if succeeded:
                etype, fc = "success", None
            else:
                r = float(rng.random())
                if r < 0.06:
                    etype, fc = "timeout", "timeout"
                else:
                    etype = "failed"
                    fc = _failure_class(rng, matched, method)
            out.n_failures += etype in ("failed", "timeout")

            cust = f"c_{int(rng.integers(1, 60000)):05d}"
            ref = f"pay_{ref_prefix}{seq:07d}"
            grp = f"grp_{ref_prefix}{seq:07d}"
            out.n_payments += 1
            out.events.append(SimEvent(
                ext_id=f"evt_{ref_prefix}{seq:07d}_c", etype="created", ref=ref, group_id=grp,
                epoch=int(t.timestamp()), amount=amount, method=method, issuer=issuer,
                psp=psp, gateway=gateway, latency_ms=latency_ms, customer_ref=cust))
            out.events.append(SimEvent(
                ext_id=f"evt_{ref_prefix}{seq:07d}_t", etype=etype, ref=ref, group_id=grp,
                epoch=int(t.timestamp()) + int(latency_ms / 1000) + 1, amount=amount,
                method=method, issuer=issuer, psp=psp, gateway=gateway,
                latency_ms=latency_ms, failure_class=fc, customer_ref=cust))

            if matched and would_succeed and not succeeded:
                for scenario in matched:
                    # A traffic-only surge has no direct failure mechanism;
                    # ground truth remains attributable to the actual failure
                    # scenario rather than falsely blaming volume alone.
                    if scenario.failure_multiplier > 1:
                        out.truth.append(_truth_record(
                            scenario, t, amount, method, issuer, psp, gateway))
    return out


# __PART2__

def _active_scenarios(active: list[Scenario], minute: int, s_start: int) -> list[Scenario]:
    return [sc for sc in active if s_start <= minute < s_start + sc.duration_min]


def _matching_scenarios(active: list[Scenario], method: str, issuer: str,
                        psp: str, gateway: str) -> list[Scenario]:
    dims = {"method": method, "issuer": issuer, "psp": psp, "gateway": gateway}
    return [sc for sc in active if matches(dims, sc.cohort)]


def _failure_class(rng, scenarios: list[Scenario], method):
    kinds = {sc.kind for sc in scenarios}
    if "auth_failures" in kinds:
        return "auth"
    if "rate_limit" in kinds:
        return "rate_limit"
    if "gateway_latency" in kinds:
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
