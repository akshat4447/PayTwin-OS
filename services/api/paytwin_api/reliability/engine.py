"""Deterministic scenario runner: events -> fixture handler -> world -> invariants."""
from __future__ import annotations

from typing import Any

from . import invariants
from .fixtures import FixturePolicy


def new_world(home_tenant: str = "t1",
              mandate_single_use: bool = False) -> World:
    return {"payments": {}, "orders": {}, "effects": [], "processed": [],
            "seen": set(), "home_tenant": home_tenant,
            "mandate_single_use": mandate_single_use}


def _fulfil(w: World, p: FixturePolicy, ev: dict) -> None:
    o = w["orders"].setdefault(ev["order_id"],
                               {"fulfilled_count": 0, "paid_expected": False})
    if p.single_fulfilment_per_order and o["fulfilled_count"]:
        return  # A second successful payment may never create a second fulfilment.
    o["fulfilled_count"] += 1
    w["effects"].append({"kind": "fulfilment", "payment_id": ev["payment_id"],
                         "order_id": ev["order_id"], "tenant": ev["tenant"],
                         "amount": ev["amount"],
                         "src_event_id": ev["event_id"]})


def handle(w: World, p: FixturePolicy, ev: dict) -> None:
    """Process one delivered provider event through the modeled integration."""
    rec = {"event_id": ev["event_id"], "signature_ok": ev["signature_ok"],
           "accepted": False, "note": ""}
    w["processed"].append(rec)

    if p.verify_signature and not ev["signature_ok"]:
        rec["note"] = "rejected: bad signature"
        return                                    # PTWIN-INV-003 path
    if p.dedupe_by_event_id and ev["event_id"] in w["seen"]:
        rec["note"] = "ignored: duplicate delivery"
        return                                    # RZPREQ-WEBHOOK-001/-002
    w["seen"].add(ev["event_id"])
    if p.enforce_tenant_scope and ev["tenant"] != w["home_tenant"]:
        rec["note"] = "dropped: foreign tenant"
        return                                    # PTWIN-INV-005 path
    rec["accepted"] = True

    t, pid, oid = ev["type"], ev["payment_id"], ev["order_id"]
    pay = w["payments"].setdefault(pid, {"status": "created",
        "captured_amount": 0, "refunded_total": 0, "tenant": ev["tenant"]})

    if t == "payment.authorized":
        # Late authorization: a previously-failed payment may still authorize.
        # Captured is TERMINAL — a late/duplicate authorized never downgrades it
        # (out-of-order convergence, PTWIN-INV-006).
        if pay["status"] != "captured":
            pay["status"] = "authorized"
        if not p.require_captured_for_fulfilment:
            _fulfil(w, p, ev)                     # broken gating
    elif t == "payment.captured":
        pay["status"] = "captured"
        pay["captured_amount"] = ev["amount"]
        if p.require_captured_for_fulfilment:
            _fulfil(w, p, ev)
        else:                                     # already fulfilled early;
            pass                                  # capture adds no new effect
    elif t == "payment.failed":
        if pay["status"] not in ("captured", "authorized"):
            pay["status"] = "failed"
    elif t == "order.paid":
        o = w["orders"].setdefault(oid, {"fulfilled_count": 0,
                                         "paid_expected": True})
        o["paid_expected"] = True
        # Naive integrations fulfil directly on order.paid without checking
        # that a payment was actually captured — exactly the forged-callback
        # bug the bad-signature scenario exists to catch.
        if not p.require_captured_for_fulfilment:
            _fulfil(w, p, ev)
    elif t == "refund.processed":
        if p.idempotent_refunds and (pay["refunded_total"] + ev["amount"]
                                     > pay["captured_amount"]):
            rec["note"] = "rejected: refund exceeds captured"
            rec["accepted"] = False
            return
        pay["refunded_total"] += ev["amount"]
        w["effects"].append({"kind": "refund", "payment_id": pid,
                             "order_id": oid, "tenant": ev["tenant"],
                             "amount": ev["amount"],
                             "src_event_id": ev["event_id"]})
    elif t == "agent.purchase":
        if p.enforce_mandate_limits and w.get("mandate_used"):
            rec["note"] = "rejected: single-use mandate replay"
            rec["accepted"] = False
            return
        w["mandate_used"] = True
        w["effects"].append({"kind": "agent_purchase", "payment_id": pid,
                             "order_id": oid, "tenant": ev["tenant"],
                             "amount": ev["amount"],
                             "src_event_id": ev["event_id"]})


def run_scenario(scenario: dict, policy: FixturePolicy) -> dict:
    w = new_world(mandate_single_use=scenario.get("single_use_mandate", False))
    for ev in scenario["events"]:
        handle(w, policy, ev)
    actual = invariants.evaluate(w)
    expected = set(scenario.get("expect_violations", []))
    passed = set(actual) == expected
    return {"scenario_id": scenario["id"], "fixture": policy.name,
            "passed": passed, "expected": sorted(expected),
            "violations": actual,
            "evidence": {"events": len(scenario["events"]),
                         "processed": len(w["processed"]),
                         "effects": len(w["effects"]),
                         "notes": [p_["note"] for p_ in w["processed"]
                                   if p_["note"]]}}
