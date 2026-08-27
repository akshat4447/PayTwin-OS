"""Sandbox-only Razorpay checks against PayTwin's real ingestion path.

This module deliberately makes no provider network calls. It creates synthetic
Razorpay-shaped webhook bodies, signs them with the locally configured test
secret, and sends them through ``ingest_webhook`` so the connector, inbox,
canonical-event persistence, and payment state machine are all exercised.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from paytwin_api.config import get_settings
from paytwin_api.models import Integration, Merchant, Payment, Refund
from paytwin_api.services.ingest import IngestResult, ingest_webhook
from paytwin_api.reliability.requirements import requirement_details


class SandboxOnlyError(RuntimeError):
    """Raised when a caller tries to run synthetic provider checks in production."""


def _body(event: str, payment_id: str, order_id: str, occurred_at: int,
          amount: int = 64_000) -> bytes:
    """Build the small Razorpay webhook shape consumed by RazorpayConnector."""
    payload = {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount,
                    "method": "upi",
                    "bank": "HDFC",
                    "created_at": occurred_at,
                    "order_id": order_id,
                }
            }
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _refund_body(event: str, payment_id: str, order_id: str, refund_id: str,
                 payment_amount: int, refund_amount: int, occurred_at: int,
                 status: str) -> bytes:
    """Build the real Razorpay refund webhook shape with separate entities."""
    payload = {
        "event": event,
        "payload": {
            "payment": {"entity": {
                "id": payment_id, "amount": payment_amount, "method": "upi",
                "bank": "HDFC", "created_at": occurred_at - 10, "order_id": order_id,
            }},
            "refund": {"entity": {
                "id": refund_id, "payment_id": payment_id, "amount": refund_amount,
                "status": status, "created_at": occurred_at,
            }},
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _signature(db: Session, merchant_id: str, body: bytes) -> str:
    integration = (db.query(Integration)
                   .filter(Integration.merchant_id == merchant_id,
                           Integration.provider == "razorpay")
                   .one_or_none())
    secret = (None if integration is None or not integration.secret_ref
              else os.environ.get(integration.secret_ref))
    secret = secret or get_settings().webhook_secret_razorpay
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _deliver(db: Session, merchant_id: str, body: bytes, event_id: str,
             signature: str | None = None) -> IngestResult:
    return ingest_webhook(
        db,
        "razorpay",
        merchant_id,
        body,
        signature if signature is not None else _signature(db, merchant_id, body),
        headers={"x-razorpay-event-id": event_id},
    )


def _payment_status(db: Session, merchant: Merchant, payment_ref: str) -> str | None:
    row = (db.query(Payment)
           .filter(Payment.organization_id == merchant.organization_id,
                   Payment.merchant_id == merchant.id,
                   Payment.provider == "razorpay",
                   Payment.payment_ref == payment_ref)
           .one_or_none())
    return row.status if row is not None else None


def _check(check_id: str, title: str, requirement_ids: list[str], expected: Any,
           actual: Any, evidence: dict) -> tuple[dict, dict | None]:
    passed = actual == expected
    check = {
        "scenario": check_id,
        "title": title,
        "fixture": "paytwin_runtime_sandbox",
        "source": "SIMULATED",
        "mode": "SANDBOX_RUNTIME",
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "requirement_ids": requirement_ids,
        "requirement_trace": requirement_details(requirement_ids),
        "evidence": evidence,
    }
    if passed:
        return check, None
    finding = {
        "finding_id": "F-" + uuid.uuid4().hex[:8],
        "scenario": check_id,
        "title": f"{check_id}: runtime behavior differs from the safety contract",
        "severity": "critical",
        "fixture": "paytwin_runtime_sandbox",
        "source": "SIMULATED",
        "requirement_ids": requirement_ids,
        "requirement_trace": requirement_details(requirement_ids),
        "evidence": {"expected": expected, "actual": actual, **evidence},
        "recommended_fix": "Fix the real ingestion/state-machine path, then rerun this sandbox check.",
    }
    return check, finding


def run_razorpay_runtime_checks(db: Session, merchant_id: str) -> dict:
    """Run synthetic Razorpay lifecycle checks through the *real* runtime.

    The supplied merchant must exist in the caller's organization; that tenant
    authorization belongs to the router. Synthetic identifiers make every run
    idempotency-safe and prevent collision with ordinary test traffic.
    """
    if get_settings().is_prod:
        raise SandboxOnlyError(
            "Razorpay runtime verification is sandbox-only and disabled in production")

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).one_or_none()
    if merchant is None:
        raise ValueError(f"merchant not found: {merchant_id}")

    token = uuid.uuid4().hex[:16]
    base = int(datetime.now(timezone.utc).timestamp())
    checks: list[dict] = []
    findings: list[dict] = []

    # At-least-once duplicate delivery: same Razorpay event-id must be a no-op.
    duplicate_payment = f"pay_rel_dup_{token}"
    duplicate_body = _body("payment.captured", duplicate_payment,
                           f"order_rel_dup_{token}", base)
    duplicate_event = f"evt_rel_dup_{token}"
    first = _deliver(db, merchant.id, duplicate_body, duplicate_event)
    second = _deliver(db, merchant.id, duplicate_body, duplicate_event)
    check, finding = _check(
        "RZP-RUNTIME-DUPLICATE",
        "Razorpay duplicate delivery is idempotent in the real ingress path",
        ["RZPREQ-WEBHOOK-001", "RZPREQ-WEBHOOK-002"],
        {"first_status": 200, "duplicate": True},
        {"first_status": first.status, "duplicate": bool(second.body.get("duplicate"))},
        {"first_response": first.body, "second_response": second.body,
         "external_event_id": duplicate_event},
    )
    checks.append(check)
    if finding:
        findings.append(finding)

    # Forged signatures must be rejected before canonical state is changed.
    forged_body = _body("payment.failed", f"pay_rel_forged_{token}",
                        f"order_rel_forged_{token}", base + 1)
    forged = _deliver(db, merchant.id, forged_body, f"evt_rel_forged_{token}",
                      signature="not-a-valid-razorpay-signature")
    check, finding = _check(
        "RZP-RUNTIME-FORGED-SIGNATURE",
        "Forged Razorpay webhook is rejected by the real ingress path",
        ["RZPREQ-WEBHOOK-006"],
        401,
        forged.status,
        {"response": forged.body},
    )
    checks.append(check)
    if finding:
        findings.append(finding)

    # Capture can arrive before its earlier authorization; the settled state may
    # not regress when the late authorization is ingested afterwards.
    reorder_payment = f"pay_rel_reorder_{token}"
    captured = _deliver(
        db, merchant.id,
        _body("payment.captured", reorder_payment, f"order_rel_reorder_{token}", base + 20),
        f"evt_rel_captured_{token}",
    )
    authorized = _deliver(
        db, merchant.id,
        _body("payment.authorized", reorder_payment, f"order_rel_reorder_{token}", base + 10),
        f"evt_rel_authorized_{token}",
    )
    reordered_status = _payment_status(db, merchant, reorder_payment)
    check, finding = _check(
        "RZP-RUNTIME-OUT-OF-ORDER",
        "Captured-before-authorized converges in the real payment state machine",
        ["RZPREQ-WEBHOOK-003", "RZPREQ-PAYMENTS-001"],
        "success",
        reordered_status,
        {"captured_response": captured.body, "authorized_response": authorized.body,
         "payment_ref": reorder_payment},
    )
    checks.append(check)
    if finding:
        findings.append(finding)

    # Razorpay documents late authorization after an earlier failure. This is a
    # deliberately observed runtime assertion, not a fixture-model assertion.
    late_payment = f"pay_rel_late_{token}"
    failed = _deliver(
        db, merchant.id,
        _body("payment.failed", late_payment, f"order_rel_late_{token}", base + 30),
        f"evt_rel_failed_{token}",
    )
    late_authorized = _deliver(
        db, merchant.id,
        _body("payment.authorized", late_payment, f"order_rel_late_{token}", base + 60),
        f"evt_rel_late_authorized_{token}",
    )
    late_status = _payment_status(db, merchant, late_payment)
    check, finding = _check(
        "RZP-RUNTIME-LATE-AUTH",
        "Late authorization after failure updates the real payment state",
        ["RZPREQ-LATEAUTH-001", "RZPREQ-PAYMENTS-001"],
        "authorized",
        late_status,
        {"failed_response": failed.body,
         "authorized_response": late_authorized.body,
         "payment_ref": late_payment},
    )
    checks.append(check)
    if finding:
        findings.append(finding)

    # A Razorpay refund carries a separate refund entity.  This proves the
    # live normalizer/state-machine uses that amount, keeps a partial refund
    # distinct from the payment status, and remains idempotent by refund id.
    refund_payment = f"pay_rel_refund_{token}"
    refund_order = f"order_rel_refund_{token}"
    _deliver(db, merchant.id,
             _body("payment.captured", refund_payment, refund_order, base + 70,
                   amount=64_000), f"evt_rel_refund_capture_{token}")
    refund_delivery = _deliver(
        db, merchant.id,
        _refund_body("refund.processed", refund_payment, refund_order,
                     f"rfnd_rel_{token}", 64_000, 16_000, base + 80, "processed"),
        f"evt_rel_refund_processed_{token}")
    refund_payment_row = (db.query(Payment)
                          .filter(Payment.merchant_id == merchant.id,
                                  Payment.provider == "razorpay",
                                  Payment.payment_ref == refund_payment).one())
    refund_row = (db.query(Refund)
                  .filter(Refund.merchant_id == merchant.id,
                          Refund.provider == "razorpay",
                          Refund.refund_ref == f"rfnd_rel_{token}").one_or_none())
    check, finding = _check(
        "RZP-RUNTIME-PARTIAL-REFUND",
        "Partial refund uses Razorpay's refund amount and preserves captured payment",
        ["RZPREQ-REFUNDS-001", "RZPREQ-REFUNDS-003"],
        {"delivery": 200, "payment_status": "success", "refunded_amount_paise": 16_000,
         "refund_status": "processed"},
        {"delivery": refund_delivery.status, "payment_status": refund_payment_row.status,
         "refunded_amount_paise": refund_payment_row.refunded_amount_paise,
         "refund_status": refund_row.status if refund_row else None},
        {"payment_ref": refund_payment, "refund_ref": f"rfnd_rel_{token}",
         "refund_delivery": refund_delivery.body},
    )
    checks.append(check)
    if finding:
        findings.append(finding)

    # A failed refund must remain recorded as a failed refund, without turning
    # the original captured payment into a refunded transaction.
    failed_refund_payment = f"pay_rel_refund_failed_{token}"
    failed_refund_order = f"order_rel_refund_failed_{token}"
    _deliver(db, merchant.id,
             _body("payment.captured", failed_refund_payment, failed_refund_order, base + 90,
                   amount=64_000), f"evt_rel_refund_failed_capture_{token}")
    failed_delivery = _deliver(
        db, merchant.id,
        _refund_body("refund.failed", failed_refund_payment, failed_refund_order,
                     f"rfnd_rel_failed_{token}", 64_000, 16_000, base + 100, "failed"),
        f"evt_rel_refund_failed_{token}")
    failed_payment_row = (db.query(Payment)
                          .filter(Payment.merchant_id == merchant.id,
                                  Payment.provider == "razorpay",
                                  Payment.payment_ref == failed_refund_payment).one())
    failed_refund_row = (db.query(Refund)
                         .filter(Refund.merchant_id == merchant.id,
                                 Refund.provider == "razorpay",
                                 Refund.refund_ref == f"rfnd_rel_failed_{token}").one_or_none())
    check, finding = _check(
        "RZP-RUNTIME-FAILED-REFUND",
        "Failed refund never changes the captured payment aggregate",
        ["RZPREQ-REFUNDS-001"],
        {"delivery": 200, "payment_status": "success", "refunded_amount_paise": 0,
         "refund_status": "failed"},
        {"delivery": failed_delivery.status, "payment_status": failed_payment_row.status,
         "refunded_amount_paise": failed_payment_row.refunded_amount_paise,
         "refund_status": failed_refund_row.status if failed_refund_row else None},
        {"payment_ref": failed_refund_payment, "refund_ref": f"rfnd_rel_failed_{token}",
         "refund_delivery": failed_delivery.body},
    )
    checks.append(check)
    if finding:
        findings.append(finding)

    return {
        "suite_id": "razorpay/runtime",
        "title": "Razorpay · sandbox runtime ingestion checks",
        "mode": "SANDBOX_RUNTIME",
        "merchant_id": merchant.id,
        "checks": checks,
        "findings": findings,
        "passed": not findings,
    }
