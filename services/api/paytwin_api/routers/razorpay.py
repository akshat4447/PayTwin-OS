"""Local Razorpay-compatible Test Mode endpoints.

They make the full payment lifecycle demonstrable without a Razorpay account or
public webhook URL. Every response carries a provenance marker; these endpoints
are refused outside development/test environments.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.config import get_settings
from paytwin_api.deps import current_principal, err, get_db, require_write
from paytwin_api.models import Merchant, Payment
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.razorpay_local import (
    LocalProviderError, PROVENANCE, create_order, local_downtime,
    simulate_payment, simulate_refund,
)

router = APIRouter(prefix="/api/razorpay", tags=["razorpay-local-test"])


def _ensure_local() -> None:
    if get_settings().is_prod:
        # The local test provider is intentionally not a production payment rail.
        raise HTTPException(403, "local Razorpay Test Mode is unavailable in production")


def _merchant(db: Session, p: Principal, merchant_id: str) -> Merchant | None:
    return (db.query(Merchant)
            .filter(Merchant.organization_id == p.organization_id,
                    Merchant.id == merchant_id).one_or_none())


class CreateOrderBody(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=40)
    amount_paise: int = Field(ge=100, le=100_000_000)
    receipt: str | None = Field(default=None, max_length=80)
    currency: str = Field(default="INR", min_length=3, max_length=3)


class SimulatePaymentBody(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=40)
    order_id: str = Field(min_length=8, max_length=200)
    outcome: str = Field(default="captured", pattern="^(captured|failed|authorized)$")
    method: str = Field(default="upi", pattern="^(upi|card|netbanking|wallet)$")
    bank: str | None = Field(default="HDFC", max_length=60)
    vpa: str | None = Field(default="local@upi", max_length=120)
    failure_reason: str | None = Field(default=None, max_length=160)


class RefundBody(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=40)
    payment_id: str = Field(min_length=8, max_length=200)
    amount_paise: int = Field(ge=1, le=100_000_000)
    receipt: str | None = Field(default=None, max_length=80)


@router.get("/environment")
def environment(p: Principal = Depends(current_principal),
                db: Session = Depends(get_db)) -> dict:
    _ensure_local()
    return {
        "environment": PROVENANCE,
        "credentials_required": False,
        "public_webhook_url_required": False,
        "network_calls": False,
        "uses": ["orders", "captured/failed payment webhooks", "checkout proof", "refunds"],
        "data_provenance": "locally generated, Razorpay-shaped Test Mode data",
    }


@router.post("/orders")
def create_local_order(body: CreateOrderBody, p: Principal = Depends(current_principal),
                       db: Session = Depends(get_db)) -> dict:
    require_write(p)
    _ensure_local()
    merchant = _merchant(db, p, body.merchant_id)
    if merchant is None:
        return err(404, "not_found", f"merchant {body.merchant_id}")
    try:
        result = create_order(db, organization_id=p.organization_id, merchant_id=merchant.id,
                              amount_paise=body.amount_paise, receipt=body.receipt,
                              currency=body.currency.upper())
    except LocalProviderError as exc:
        return err(422, "invalid_local_order", str(exc))
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="razorpay_local.order_created",
        object_type="order", object_id=result.order.id,
        summary="Local Razorpay Test Mode order created",
        details={"merchant_id": merchant.id, "order_ref": result.order.order_ref,
                 "amount_paise": result.order.amount_paise, "provenance": PROVENANCE},
    )
    db.commit()
    return {"provenance": PROVENANCE, "order": result.provider_order}


@router.post("/payments/simulate")
def simulate_local_payment(body: SimulatePaymentBody,
                           p: Principal = Depends(current_principal),
                           db: Session = Depends(get_db)) -> dict:
    require_write(p)
    _ensure_local()
    merchant = _merchant(db, p, body.merchant_id)
    if merchant is None:
        return err(404, "not_found", f"merchant {body.merchant_id}")
    try:
        output = simulate_payment(db, merchant_id=merchant.id, order_ref=body.order_id,
                                  outcome=body.outcome, method=body.method,
                                  bank=body.bank, vpa=body.vpa,
                                  failure_reason=body.failure_reason)
    except LocalProviderError as exc:
        return err(422, "invalid_local_payment", str(exc))
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="razorpay_local.payment_simulated",
        object_type="payment", object_id=output["payment"]["id"],
        summary=f"Local Razorpay payment {body.outcome}",
        details={"merchant_id": merchant.id, "order_ref": body.order_id,
                 "outcome": body.outcome, "provenance": PROVENANCE},
    )
    # ``simulate_payment`` commits the verified inbound delivery. Commit the
    # accompanying audit record too, preserving one complete operator trail.
    db.commit()
    return output


@router.get("/payments/{payment_ref}")
def get_local_payment(payment_ref: str, merchant_id: str,
                      p: Principal = Depends(current_principal),
                      db: Session = Depends(get_db)) -> dict:
    _ensure_local()
    payment = (db.query(Payment)
               .filter(Payment.organization_id == p.organization_id,
                       Payment.merchant_id == merchant_id,
                       Payment.provider == "razorpay", Payment.payment_ref == payment_ref)
               .one_or_none())
    if payment is None:
        return err(404, "not_found", "local Razorpay payment")
    return {"provenance": PROVENANCE, "payment": {
        "id": payment.payment_ref, "order_id": payment.order_ref,
        "amount": payment.amount_paise, "currency": payment.currency,
        "status": "captured" if payment.status == "success" else payment.status,
        "method": payment.method, "bank": payment.issuer,
        "refunded_amount": payment.refunded_amount_paise,
    }}


@router.post("/refunds")
def simulate_local_refund(body: RefundBody, p: Principal = Depends(current_principal),
                          db: Session = Depends(get_db)) -> dict:
    require_write(p)
    _ensure_local()
    merchant = _merchant(db, p, body.merchant_id)
    if merchant is None:
        return err(404, "not_found", f"merchant {body.merchant_id}")
    try:
        output = simulate_refund(db, merchant_id=merchant.id, payment_ref=body.payment_id,
                                 amount_paise=body.amount_paise, receipt=body.receipt)
    except LocalProviderError as exc:
        return err(422, "invalid_local_refund", str(exc))
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="razorpay_local.refund_simulated",
        object_type="payment", object_id=body.payment_id,
        summary="Local Razorpay refund processed",
        details={"merchant_id": merchant.id, "amount_paise": body.amount_paise,
                 "provenance": PROVENANCE},
    )
    db.commit()
    return output


@router.get("/downtime")
def downtime(merchant_id: str | None = None, p: Principal = Depends(current_principal),
             db: Session = Depends(get_db)) -> dict:
    _ensure_local()
    if merchant_id and _merchant(db, p, merchant_id) is None:
        return err(404, "not_found", f"merchant {merchant_id}")
    return local_downtime(db, organization_id=p.organization_id, merchant_id=merchant_id)
