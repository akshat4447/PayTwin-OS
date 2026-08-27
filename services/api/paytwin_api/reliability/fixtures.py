"""App-under-test abstraction: merchant webhook-handler policies ("fixtures").

A fixture is a tiny deterministic model of how a merchant's integration reacts to
provider events. `correct()` encodes the safe behavior demanded by Razorpay
requirements + PayTwin invariants; the other presets are KNOWN-BROKEN integrations
used to prove the Reliability Lab actually detects real defect classes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FixturePolicy:
    name: str
    verify_signature: bool = True
    dedupe_by_event_id: bool = True          # RZPREQ-WEBHOOK-001/-002
    require_captured_for_fulfilment: bool = True  # PTWIN-INV-001 / RZPREQ-PAYMENTS-001
    idempotent_refunds: bool = True          # RZPREQ-REFUNDS-003
    enforce_tenant_scope: bool = True        # PTWIN-INV-005
    enforce_mandate_limits: bool = True      # PTWIN-INV-007
    single_fulfilment_per_order: bool = True  # PTWIN-INV-008


def correct() -> FixturePolicy:
    return FixturePolicy("correct")


def no_signature_verification() -> FixturePolicy:
    """Mutation: signature verification removed (RZPREQ-WEBHOOK-006)."""
    return FixturePolicy("no_verify", verify_signature=False)


def no_dedupe() -> FixturePolicy:
    """Mutation: at-least-once duplicates are re-processed (RZPREQ-WEBHOOK-001/-002)."""
    # The modeled broken handler has no independent fulfilment idempotency key
    # either, so the duplicate is observable as a duplicated business effect.
    return FixturePolicy("no_dedupe", dedupe_by_event_id=False,
                         single_fulfilment_per_order=False)


def fulfil_on_authorized() -> FixturePolicy:
    """Mutation: fulfils on authorized (ignores capture gating) — breaks
    PTWIN-INV-001 and mishandles RZPREQ-LATEAUTH-001."""
    return FixturePolicy("fulfil_on_authorized",
                         require_captured_for_fulfilment=False)


def refund_over_capture() -> FixturePolicy:
    """Mutation: accepts refunds exceeding captured amount (breaks PTWIN-INV-004,
    violates RZPREQ-REFUNDS-001 gating spirit)."""
    return FixturePolicy("refund_over_capture", idempotent_refunds=False)


def cross_tenant_blind() -> FixturePolicy:
    """Mutation: processes events for any tenant into the local tenant."""
    return FixturePolicy("cross_tenant_blind", enforce_tenant_scope=False)


def mandate_limits_off() -> FixturePolicy:
    """Mutation: agent mandate spending limits ignored (PTWIN-INV-007)."""
    return FixturePolicy("mandate_limits_off", enforce_mandate_limits=False)


def forged_callback() -> FixturePolicy:
    """Mutation: trusts unverified callbacks AND fulfils on order.paid —
    the classic forged-webhook fulfilment bug (PTWIN-INV-003 + PTWIN-INV-001)."""
    return FixturePolicy("forged_callback", verify_signature=False,
                         require_captured_for_fulfilment=False)


def duplicate_fulfilment() -> FixturePolicy:
    """Mutation: two successful payments may fulfil the same order twice."""
    return FixturePolicy("duplicate_fulfilment",
                         single_fulfilment_per_order=False)


PRESETS = {
    "correct": correct,
    "no_verify": no_signature_verification,
    "no_dedupe": no_dedupe,
    "fulfil_on_authorized": fulfil_on_authorized,
    "refund_over_capture": refund_over_capture,
    "cross_tenant_blind": cross_tenant_blind,
    "mandate_limits_off": mandate_limits_off,
    "forged_callback": forged_callback,
    "duplicate_fulfilment": duplicate_fulfilment,
}
