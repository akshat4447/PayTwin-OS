"""Provider-independent generic pack + Razorpay pack (requirement-traced).

Suite shape: base scenario runs against the CORRECT fixture and must be clean;
each mutation runs a KNOWN-BROKEN fixture and must produce exactly the listed
invariant violations. A suite passes only when both hold ("test the tester").
"""
from __future__ import annotations

E = dict  # event shorthand


def _pay(eid, amt, ok=True, tenant="t1", pid="pay_1", oid="order_1", typ="payment.captured"):
    return E(event_id=eid, type=typ, payment_id=pid, order_id=oid,
             tenant=tenant, amount=amt, signature_ok=ok)


GENERIC_WEBHOOKS = {
 "suite_id": "generic/webhooks",
 "title": "Generic webhook resilience",
 "source": "PAYTWIN_INVARIANT",
 "req_ids": ["PTWIN-INV-002", "PTWIN-INV-003"],
 "scenarios": [
  {"id": "GEN-WH-DUP", "title": "Duplicate captured-payment delivery",
   "events": [_pay("e1", 50000), _pay("e1", 50000)],
   "expect_violations": [],
   "mutations": [{"name": "no_dedupe", "preset": "no_dedupe",
                  "expect": ["PTWIN-INV-002"]}]},
  {"id": "GEN-WH-BADSIG", "title": "Forged callback rejected",
   "events": [E(event_id="e2", type="order.paid", payment_id="pay_1",
                order_id="order_1", tenant="t1", amount=50000,
                signature_ok=False)],
   "expect_violations": [],
   "mutations": [{"name": "forged_callback", "preset": "forged_callback",
                  "expect": ["PTWIN-INV-003", "PTWIN-INV-001"]}]},
 ]}

RAZORPAY_CORE = {
 "suite_id": "razorpay/core",
 "title": "Razorpay · core lifecycle & webhooks",
 "source": "RAZORPAY_REQUIREMENT",
 "req_ids": ["RZPREQ-WEBHOOK-001", "RZPREQ-WEBHOOK-003", "RZPREQ-WEBHOOK-006",
             "RZPREQ-PAYMENTS-001", "RZPREQ-REFUNDS-001", "RZPREQ-LATEAUTH-001"],
 "scenarios": [
  {"id": "RZP-WH-DUP-DELIVERY", "title": "At-least-once redelivery of payment.captured",
   "req_ids": ["RZPREQ-WEBHOOK-001", "RZPREQ-WEBHOOK-002"],
   "events": [_pay("rz1", 64000), _pay("rz1", 64000)],
   "expect_violations": [],
   "mutations": [{"name": "no_dedupe", "preset": "no_dedupe",
                  "expect": ["PTWIN-INV-002"]}]},
  {"id": "RZP-WH-FORGED", "title": "Unsigned webhook must not move money state",
   "req_ids": ["RZPREQ-WEBHOOK-006"],
   "events": [_pay("rz2", 64000, ok=False)],
   "expect_violations": [],
   "mutations": [{"name": "no_verify", "preset": "no_verify",
                  "expect": ["PTWIN-INV-003"]}]},
  {"id": "RZP-LATE-AUTH", "title": "Late authorization after terminal failure",
   "req_ids": ["RZPREQ-LATEAUTH-001", "RZPREQ-PAYMENTS-001"],
   "events": [_pay("rz3", 84000, typ="payment.failed"),
              _pay("rz4", 84000, typ="payment.authorized"),
              _pay("rz4", 84000, typ="payment.captured")],
   "expect_violations": [],
   "mutations": [{"name": "fulfil_on_authorized", "preset": "fulfil_on_authorized",
                  "expect": ["PTWIN-INV-001"]}]},
  {"id": "RZP-REFUND-CAP", "title": "Refund cannot exceed captured amount",
   "req_ids": ["RZPREQ-REFUNDS-001", "RZPREQ-REFUNDS-003"],
   "events": [_pay("rz5", 50000, typ="payment.captured"),
              E(event_id="rz6", type="refund.processed", payment_id="pay_1",
                order_id="order_1", tenant="t1", amount=120000,
                signature_ok=True)],
   "expect_violations": [],
   "mutations": [{"name": "refund_over_capture", "preset": "refund_over_capture",
                  "expect": ["PTWIN-INV-004"]}]},
  {"id": "RZP-WH-REORDER", "title": "Out-of-order arrival converges",
   "req_ids": ["RZPREQ-WEBHOOK-003"],
   "events": [_pay("rz8", 40000, typ="payment.captured"),
              _pay("rz7", 40000, typ="payment.authorized"),
              E(event_id="rz9", type="order.paid", payment_id="pay_1",
                order_id="order_1", tenant="t1", amount=40000,
                signature_ok=True)],
   "expect_violations": [], "mutations": []},
 ]}

TENANT_ISOLATION = {
 "suite_id": "paytwin/isolation",
 "title": "PayTwin · multi-tenant isolation",
 "source": "PAYTWIN_INVARIANT",
 "req_ids": ["PTWIN-INV-005"],
 "scenarios": [
  {"id": "ISO-TENANT-B", "title": "Tenant-B event never mutates tenant-A ledger",
   "events": [_pay("t9", 10000, tenant="tB")],
   "expect_violations": [],
   "mutations": [{"name": "cross_tenant_blind", "preset": "cross_tenant_blind",
                  "expect": ["PTWIN-INV-005"]}]}]}

AGENTIC = {
 "suite_id": "paytwin/agentic",
 "title": "PayTwin · agentic payment security",
 "source": "PAYTWIN_INVARIANT",
 "req_ids": ["PTWIN-INV-007"],
 "scenarios": [
  {"id": "AGT-REPLAY", "title": "Single-use mandate replay rejected",
   "single_use_mandate": True,
   "events": [_pay("a1", 25000, typ="agent.purchase"),
              _pay("a2", 25000, typ="agent.purchase")],
   "expect_violations": [],
   "mutations": [{"name": "mandate_limits_off", "preset": "mandate_limits_off",
                  "expect": ["PTWIN-INV-007"]}]}]}


def all_suites() -> list[dict]:
    return [GENERIC_WEBHOOKS, RAZORPAY_CORE, TENANT_ISOLATION, AGENTIC]


def find_suite(suite_id: str) -> dict | None:
    return next((s for s in all_suites() if s["suite_id"] == suite_id), None)
