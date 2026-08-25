"""Digital Twin (TWIN-001): seeded merchant Monte-Carlo over recovery scenarios.

Same incident + same seed ⇒ byte-identical result (contract test). Scenarios model the
merchant's own traffic/mix/costs; recovery curves come from measured recovery history
(simulator ground truth in v1) — assumptions are explicit and challengeable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SCENARIOS = ("do_nothing", "retry_burst", "reroute_psp", "payment_links",
             "notify_customer", "calendar_shift", "wait")

# explicit assumption sheet (₹, printed in the UI's "assumptions on the record")
ASSUMPTIONS = {
    "recovery_curve": "TECHNICAL → 62% @5m, decays exp(-t/45m)",
    "cost_retry_paise": 180,
    "cost_msg_paise": 35,
    "friction_gamma": 1.4,          # convex customer-friction per contact
    "reroute_efficiency": 0.72,     # share of rerouted traffic that succeeds
    "link_conversion": 0.34,        # payment-link conversion within window
    "notify_conversion": 0.12,      # bare notification conversion
    "calendar_shift_conversion": 0.55,  # mandate retry on better day
    "clv_mult": {"subscriptions": 4.2, "travel": 1.6, "grocery": 1.1, "fashion": 1.2},
}


@dataclass
class TwinResult:
    scenario: str
    seed: int
    trials: int
    p50_paise: int
    lo_paise: int
    hi_paise: int
    lift_pct: float            # vs do_nothing
    traj: list[int]            # cumulative recovered per 10% of horizon
    cost_paise: int
    policy_compat: str         # ok|approval_required|likely_block
    detail: dict


def _recovery_weight(minutes_since: float) -> float:
    return 0.62 * np.exp(-max(0.0, minutes_since) / 45.0)


def run_twin(merchant_id: str, industry: str, failed_payments: list[dict],
             scenario: str, seed: int, trials: int = 400,
             alloc_pct: int = 25, duration_min: int = 30) -> TwinResult:
    """Monte-Carlo incremental recovery for `scenario` vs do-nothing baseline."""
    rng = np.random.default_rng(seed)
    n = len(failed_payments)
    if n == 0:
        return TwinResult(scenario, seed, trials, 0, 0, 0, 0.0, [0] * 10, 0, "ok", {})

    amounts = np.array([p["amount"] for p in failed_payments], dtype=float)
    ages = np.array([float(p.get("age_min", 0)) for p in failed_payments])
    clv = ASSUMPTIONS["clv_mult"].get(industry, 1.0)
    alloc = alloc_pct / 100.0
    horizon = max(5, duration_min)

    base = np.zeros(trials)
    treat = np.zeros(trials)
    cost = np.zeros(trials)

    # do-nothing: organic recovery of a small share
    p_organic = _recovery_weight(ages.mean()) * 0.15
    base += (rng.random((trials, n)) < p_organic) @ amounts

    if scenario == "do_nothing" or scenario == "wait":
        recovered = base
        cost[:] = 0
    elif scenario == "retry_burst":
        sel = rng.random((trials, n)) < alloc
        p_ok = _recovery_weight(ages.mean()) * 0.62
        succ = sel & (rng.random((trials, n)) < p_ok)
        treat = base + succ @ amounts
        cost = sel.sum(axis=1) * ASSUMPTIONS["cost_retry_paise"]
    elif scenario == "reroute_psp":
        sel = rng.random((trials, n)) < alloc
        succ = sel & (rng.random((trials, n)) < ASSUMPTIONS["reroute_efficiency"] * _recovery_weight(ages.mean()) + 0.05)
        treat = base + succ @ amounts
        cost = sel.sum(axis=1) * ASSUMPTIONS["cost_retry_paise"] * 1.2
    elif scenario == "payment_links":
        sel = rng.random((trials, n)) < alloc
        succ = sel & (rng.random((trials, n)) < ASSUMPTIONS["link_conversion"])
        treat = base + succ @ amounts * clv * 0.4 + succ @ amounts * 0.6
        cost = sel.sum(axis=1) * ASSUMPTIONS["cost_msg_paise"] * 2
    elif scenario == "notify_customer":
        sel = rng.random((trials, n)) < min(1.0, alloc * 2)
        succ = sel & (rng.random((trials, n)) < ASSUMPTIONS["notify_conversion"])
        treat = base + succ @ amounts
        cost = sel.sum(axis=1) * ASSUMPTIONS["cost_msg_paise"]
    elif scenario == "calendar_shift":
        sel = rng.random((trials, n)) < alloc
        succ = sel & (rng.random((trials, n)) < ASSUMPTIONS["calendar_shift_conversion"] * 0.8)
        treat = base + succ @ amounts * clv * 0.5 + succ @ amounts * 0.5
        cost = sel.sum(axis=1) * ASSUMPTIONS["cost_msg_paise"]
    else:
        treat = base
        cost = np.zeros(trials)

    inc = treat - base - cost
    inc = np.maximum(inc, -cost)  # never worse than the cost you paid
    p50 = float(np.percentile(inc, 50))
    lo = float(np.percentile(inc, 10))
    hi = float(np.percentile(inc, 90))

    # trajectory: cumulative recovered share across the horizon (deterministic shape)
    traj = [int(p50 * (i + 1) / 10 * (1 - np.exp(-(i + 1) / 6.0)) / (1 - np.exp(-1.0)))
            for i in range(10)]

    if scenario in ("do_nothing", "wait"):
        compat = "ok"
    elif scenario in ("retry_burst", "reroute_psp") and alloc > 0.5:
        compat = "approval_required"
    else:
        compat = "ok"

    base_p50 = float(np.percentile(base, 50)) or 1.0
    return TwinResult(
        scenario=scenario, seed=seed, trials=trials,
        p50_paise=int(p50), lo_paise=int(lo), hi_paise=int(hi),
        lift_pct=round((p50 / max(1.0, abs(base_p50))) * 100 - 100 * (1 if base_p50 > 0 else 0), 1),
        traj=traj, cost_paise=int(float(np.percentile(cost, 50))),
        policy_compat=compat,
        detail={"assumptions": ASSUMPTIONS, "n_failed": n, "alloc_pct": alloc_pct,
                "duration_min": duration_min, "industry": industry},
    )
