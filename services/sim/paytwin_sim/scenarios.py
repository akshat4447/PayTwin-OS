"""Incident scenario library — deterministic injections with counterfactual ground truth."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    kind: str
    cohort: dict                      # dims to match: issuer/method/psp/gateway (missing = any)
    failure_multiplier: float         # applied to (1 - sr) of matched payments
    latency_multiplier: float = 1.0
    traffic_multiplier: float = 1.0
    duration_min: int = 25
    label: str = ""


SCENARIOS = {
    "issuer_outage": Scenario(
        kind="issuer_outage", cohort={"issuer": "HDFC", "method": "upi_intent"},
        failure_multiplier=9.0, latency_multiplier=3.2, duration_min=25,
        label="HDFC × UPI intent degradation (all PSPs)"),
    "psp_degradation": Scenario(
        kind="psp_degradation", cohort={"psp": "cashfree"},
        failure_multiplier=4.5, latency_multiplier=2.5, duration_min=30,
        label="Cashfree PSP degradation"),
    "gateway_latency": Scenario(
        kind="gateway_latency", cohort={"gateway": "gw1"},
        failure_multiplier=2.2, latency_multiplier=5.0, duration_min=20,
        label="Gateway gw1 latency spike"),
    "checkout_regression": Scenario(
        kind="checkout_regression", cohort={"method": "card"},
        failure_multiplier=3.0, duration_min=40, label="Card checkout regression"),
    "webhook_lag": Scenario(
        kind="webhook_lag", cohort={}, failure_multiplier=1.0, latency_multiplier=1.0,
        duration_min=15, label="Webhook delivery lag (observation only)"),
    "auth_failures": Scenario(
        kind="auth_failures", cohort={"method": "netbanking"},
        failure_multiplier=5.0, duration_min=20, label="Netbanking auth failures"),
    "rate_limit": Scenario(
        kind="rate_limit", cohort={"issuer": "SBI"},
        failure_multiplier=3.5, duration_min=18, label="SBI rate limiting"),
    "flash_sale_surge": Scenario(
        kind="flash_sale_surge", cohort={}, failure_multiplier=1.0,
        traffic_multiplier=4.0, duration_min=20,
        label="4× flash-sale traffic surge"),
    "surge_bank_failure": Scenario(
        kind="surge_bank_failure", cohort={"issuer": "HDFC", "method": "upi_intent"},
        failure_multiplier=9.0, latency_multiplier=3.2, traffic_multiplier=4.0,
        duration_min=20, label="4× surge with HDFC × UPI intent degradation"),
}


def matches(cohort: dict, dims: dict) -> bool:
    return all(cohort.get(k) == v for k, v in dims.items() if v)
