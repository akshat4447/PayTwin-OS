"""Small, explicit traceability registry for the Razorpay demo assurance pack.

This is deliberately curated rather than scraped at runtime: a demo or release
gate must stay reproducible even when a documentation website is unavailable.
Each Razorpay requirement carries its public source URL; PayTwin invariants are
product controls and are labelled as such.
"""
from __future__ import annotations

_DOCS = {
    "webhook_validation": "https://razorpay.com/docs/webhooks/validate-test/",
    "webhook_faq": "https://razorpay.com/docs/webhooks/faqs/",
    "webhooks": "https://razorpay.com/docs/webhooks/",
    "checkout": "https://razorpay.com/docs/developer-tools/integrations/standard-checkout/",
    "refund_webhooks": "https://razorpay.com/docs/webhooks/refunds/",
    "refund_idempotency": "https://razorpay.com/docs/api/refunds/normal-refunds-idempotent/",
    "downtime": "https://razorpay.com/docs/api/payments/downtime/",
}


def _rz(title: str, doc: str) -> dict:
    return {"source": "RAZORPAY_DOCUMENTATION", "title": title, "source_url": _DOCS[doc]}


def _pt(title: str) -> dict:
    return {"source": "PAYTWIN_INVARIANT", "title": title, "source_url": None}


REGISTRY: dict[str, dict] = {
    "RZPREQ-WEBHOOK-001": _rz("Webhook deliveries are processed idempotently", "webhook_faq"),
    "RZPREQ-WEBHOOK-002": _rz("Razorpay event id anchors duplicate-delivery handling", "webhook_validation"),
    "RZPREQ-WEBHOOK-003": _rz("Out-of-order webhook delivery converges safely", "webhook_validation"),
    "RZPREQ-WEBHOOK-004": _rz("Webhook retry failures are surfaced operationally", "webhook_faq"),
    "RZPREQ-WEBHOOK-006": _rz("Raw webhook payload HMAC is verified before processing", "webhook_validation"),
    "RZPREQ-LATEAUTH-001": _rz("A late authorization must not corrupt a settled lifecycle", "webhook_validation"),
    "RZPREQ-PAYMENTS-001": _rz("Checkout signature and captured payment are verified server-side", "checkout"),
    "RZPREQ-REFUNDS-001": _rz("Refund lifecycle is read from the refund entity", "refund_webhooks"),
    "RZPREQ-REFUNDS-003": _rz("Refund requests and events preserve idempotency", "refund_idempotency"),
    "RZPREQ-DOWNTIME-001": _rz("Provider downtime signals are available for routing decisions", "downtime"),
    "PTWIN-INV-001": _pt("No fulfilment without a captured payment"),
    "PTWIN-INV-002": _pt("One business effect per provider event"),
    "PTWIN-INV-003": _pt("Invalid signatures have zero state or business effect"),
    "PTWIN-INV-004": _pt("Refund total never exceeds captured amount"),
    "PTWIN-INV-005": _pt("An event never crosses its tenant boundary"),
    "PTWIN-INV-006": _pt("Out-of-order events converge to a safe state"),
    "PTWIN-INV-007": _pt("Single-use agent mandates cannot replay"),
    "PTWIN-INV-008": _pt("One merchant order has at most one fulfilment"),
}


def requirement_details(ids: list[str]) -> list[dict]:
    return [{"id": rid, **REGISTRY.get(rid, {
        "source": "UNREGISTERED", "title": "Unregistered requirement", "source_url": None,
    })} for rid in ids]


def summary() -> dict:
    return {"provider": "razorpay", "docs_verified": len(_DOCS),
            "requirements": len(REGISTRY), "last_refresh": "2026-08-27"}
