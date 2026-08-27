"""Transparent, sandbox-only pre-incident scenario forecast for the demo.

This is intentionally not presented as a live PSP prediction.  It combines a
merchant's observed baseline with an explicit scenario prior, then uses the
existing seeded Digital Twin to compare bounded response options.  The response
labels every estimate as simulated so a judge can see exactly what is measured
and what is assumed.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from paytwin_api.models import Merchant, ModelVersion, Payment
from paytwin_ml.twin import run_twin
from paytwin_sim.scenarios import SCENARIOS
from paytwin_sim.world import MERCHANTS as WORLD

_ACTION_SET = ("reroute_psp", "retry_burst", "payment_links", "wait")

_PLAYBOOK = {
    "issuer_outage": {
        "prevent": ["Hold automatic retries until issuer recovery is observed",
                    "Offer a consent-safe payment link fallback", "Protect retry budget"],
        "why": "An issuer-specific failure usually will not improve by changing PSP alone.",
    },
    "psp_degradation": {
        "prevent": ["Stage a bounded backup-PSP allocation", "Monitor approval/error mix",
                    "Keep a rollback threshold before wider routing"],
        "why": "A PSP-local drop is the strongest case for a policy-bounded reroute.",
    },
    "flash_sale_surge": {
        "prevent": ["Reserve capacity and rate-limit nonessential retries", "Pre-warm support routing",
                    "Keep checkout fallback messaging ready"],
        "why": "Volume pressure needs capacity controls before customer-contact actions.",
    },
    "surge_bank_failure": {
        "prevent": ["Reserve capacity while isolating the failing issuer cohort",
                    "Hold retries to the degraded issuer", "Stage payment-link fallback"],
        "why": "This is a compound volume-and-issuer scenario; broad rerouting is deliberately bounded.",
    },
}


def scenario_forecast(db: Session, merchant: Merchant, scenario: str, *,
                      duration_min: int, seed: int = 20260827) -> dict:
    """Calculate a deterministic sandbox preflight forecast and action comparison."""
    spec = SCENARIOS.get(scenario)
    if spec is None:
        raise ValueError(f"unknown scenario {scenario}")
    cfg = WORLD.get((merchant.config or {}).get("world_id"), {})
    history = (db.query(Payment)
               .filter(Payment.merchant_id == merchant.id)
               .order_by(Payment.occurred_at.desc()).limit(500).all())
    observed_n = len(history)
    if observed_n:
        baseline_failure = sum(p.status in {"failed", "timeout"} for p in history) / observed_n
        avg_amount = int(sum(p.amount_paise for p in history) / observed_n)
    else:
        baseline_failure = max(0.005, 1 - merchant.sr_base_bp / 10_000)
        avg_amount = int(cfg.get("aov_paise", 75_000))
    tpm = float(cfg.get("tpm", max(1.0, observed_n / 60.0)))
    traffic_multiplier = float(spec.traffic_multiplier)
    expected_attempts = max(1, round(tpm * duration_min * traffic_multiplier))
    projected_failure = min(0.92, baseline_failure * float(spec.failure_multiplier))
    excess_failures = max(0, round(expected_attempts * (projected_failure - baseline_failure)))
    rar = excess_failures * avg_amount

    # The twin requires candidate failed payments. These are a fixed synthetic
    # slice representing the forecasted at-risk population, never real payment
    # ids or customer data.
    sample_n = min(500, max(1, excess_failures))
    at_risk = [{"amount": avg_amount, "age_min": 2 + (i % 10)} for i in range(sample_n)]
    industry = (merchant.config or {}).get("industry", cfg.get("industry", "grocery"))
    action_results = []
    for index, action in enumerate(_ACTION_SET):
        twin = run_twin(merchant.id, industry, at_risk, action, seed=seed + index,
                        trials=400, alloc_pct=25, duration_min=duration_min)
        action_results.append({
            "scenario": action, "p50_recovered_paise": twin.p50_paise,
            "lo_recovered_paise": twin.lo_paise, "hi_recovered_paise": twin.hi_paise,
            "cost_paise": twin.cost_paise, "policy_compat": twin.policy_compat,
        })
    action_results.sort(key=lambda row: row["p50_recovered_paise"], reverse=True)
    model = (db.query(ModelVersion)
             .filter(ModelVersion.stage.in_(("CHAMPION", "VALIDATED")))
             .order_by(ModelVersion.promoted_at.desc(), ModelVersion.trained_at.desc()).first())
    playbook = _PLAYBOOK.get(scenario, {
        "prevent": ["Observe the cohort before acting", "Use a bounded, approved response"],
        "why": "The scenario requires cohort-specific validation before action.",
    })
    uncertainty = max(1, int(math.sqrt(max(1, excess_failures)) * avg_amount))
    return {
        "mode": "SANDBOX_FORECAST",
        "scenario": scenario,
        "scenario_label": spec.label,
        "seed": seed,
        "forecast": {
            "duration_min": duration_min, "traffic_multiplier": traffic_multiplier,
            "baseline_failure_rate": round(baseline_failure, 4),
            "projected_failure_rate": round(projected_failure, 4),
            "expected_attempts": expected_attempts, "excess_failures": excess_failures,
            "revenue_at_risk_paise": rar,
            "rar_lo_paise": max(0, rar - uncertainty), "rar_hi_paise": rar + uncertainty,
            "average_amount_paise": avg_amount, "observed_baseline_payments": observed_n,
        },
        "risk_model": {
            "kind": "scenario-conditioned risk prior", "version": "surge-v1",
            "supporting_model": (f"{model.name}:{model.version}" if model else None),
            "supporting_model_metrics": model.metrics if model else None,
            "inputs": ["merchant baseline", "scenario failure multiplier", "traffic multiplier", "AOV"],
            "limitation": "Simulated preflight estimate; not live Razorpay telemetry or a production forecast.",
        },
        "recommended_actions": action_results,
        "prevention": playbook["prevent"],
        "decision_note": playbook["why"],
    }
