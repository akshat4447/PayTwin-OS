"""Executable business invariants (PayTwin safety layer).

Each evaluator receives the post-run World and returns None when the invariant
holds, otherwise a human-readable violation string. Invariant ids are stable and
registered in project-memory/razorpay-invariants.json.
"""
from __future__ import annotations

from typing import Any

World = dict[str, Any]


def no_fulfilment_without_captured(w: World) -> str | None:
    for f in w["effects"]:
        if f["kind"] == "fulfilment":
            pay = w["payments"].get(f["payment_id"])
            if not pay or pay["status"] != "captured":
                return (f"fulfilment for {f['payment_id']} while status="
                        f"{pay['status'] if pay else 'missing'}")
    return None


def one_effect_per_event(w: World) -> str | None:
    seen: dict[str, int] = {}
    for e in w["effects"]:
        seen[e["src_event_id"]] = seen.get(e["src_event_id"], 0) + 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    return f"duplicate business effects from events {dupes}" if dupes else None


def invalid_signature_zero_effect(w: World) -> str | None:
    bad_ids = {e["event_id"] for e in w["processed"] if not e["signature_ok"]}
    leaked = [e for e in w["effects"] if e["src_event_id"] in bad_ids]
    accepted = [p for p in w["processed"]
                if not p["signature_ok"] and p["accepted"]]
    if leaked or accepted:
        return f"unsigned events produced effects/acceptance: {leaked or accepted}"
    return None


def refund_le_captured(w: World) -> str | None:
    for pid, pay in w["payments"].items():
        if pay["refunded_total"] > pay["captured_amount"]:
            return (f"refunded {pay['refunded_total']} > captured "
                    f"{pay['captured_amount']} for {pid}")
    return None


def tenant_isolation(w: World) -> str | None:
    stray = [e for e in w["effects"] if e["tenant"] != w["home_tenant"]]
    return f"tenant leakage: {stray}" if stray else None


def out_of_order_converges(w: World) -> str | None:
    for oid, o in w["orders"].items():
        if o["paid_expected"] and o["fulfilled_count"] < 1:
            return f"order {oid} paid but never fulfilled after full delivery"
    return None


def agent_mandate_single_use(w: World) -> str | None:
    n = sum(1 for e in w["effects"] if e["kind"] == "agent_purchase")
    if w.get("mandate_single_use") and n > 1:
        return f"single-use mandate produced {n} purchases"
    return None


def one_fulfilment_per_order(w: World) -> str | None:
    """Multiple payment attempts can settle one order, never two deliveries."""
    counts: dict[str, int] = {}
    for effect in w["effects"]:
        if effect["kind"] == "fulfilment":
            order_id = effect["order_id"]
            counts[order_id] = counts.get(order_id, 0) + 1
    dupes = {order_id: count for order_id, count in counts.items() if count > 1}
    return f"orders fulfilled more than once: {dupes}" if dupes else None


EVALUATORS = {
    "PTWIN-INV-001": no_fulfilment_without_captured,
    "PTWIN-INV-002": one_effect_per_event,
    "PTWIN-INV-003": invalid_signature_zero_effect,
    "PTWIN-INV-004": refund_le_captured,
    "PTWIN-INV-005": tenant_isolation,
    "PTWIN-INV-006": out_of_order_converges,
    "PTWIN-INV-007": agent_mandate_single_use,
    "PTWIN-INV-008": one_fulfilment_per_order,
}


def evaluate(world: World) -> dict[str, str]:
    return {iid: msg for iid, fn in EVALUATORS.items()
            if (msg := fn(world)) is not None}
