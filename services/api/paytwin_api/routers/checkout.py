"""Authenticated Test Mode evidence endpoint for Razorpay Checkout callbacks."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db, require_write
from paytwin_api.models import Merchant
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.checkout_verification import verify_razorpay_checkout

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


class RazorpayVerifyBody(BaseModel):
    merchant_id: str = Field(max_length=40)
    razorpay_order_id: str = Field(min_length=3, max_length=200)
    razorpay_payment_id: str = Field(min_length=3, max_length=200)
    razorpay_signature: str = Field(min_length=16, max_length=200)


@router.post("/razorpay/verify")
def verify_razorpay(body: RazorpayVerifyBody,
                    p: Principal = Depends(current_principal),
                    db: Session = Depends(get_db)):
    """Verify a browser Checkout callback before any merchant fulfilment action.

    The hackathon app keeps this endpoint bearer-authenticated because it is an
    operator demo API.  A merchant integration can call the same service from
    its server-side callback handler with its own session boundary.
    """
    require_write(p)
    merchant = (db.query(Merchant)
                .filter(Merchant.organization_id == p.organization_id,
                        Merchant.id == body.merchant_id).one_or_none())
    if merchant is None:
        return err(404, "not_found", f"merchant {body.merchant_id}")
    result = verify_razorpay_checkout(
        db, organization_id=p.organization_id, merchant_id=merchant.id,
        order_ref=body.razorpay_order_id, payment_ref=body.razorpay_payment_id,
        signature=body.razorpay_signature,
    )
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="checkout.verified" if result.ok else "checkout.rejected",
        object_type="payment", object_id=body.razorpay_payment_id,
        summary=result.message,
        details={"merchant_id": merchant.id, "provider": "razorpay",
                 "order_ref": body.razorpay_order_id, "result": result.code,
                 "verification_id": result.verification_id},
    )
    db.commit()
    status = 200 if result.ok else 422
    payload = {"ok": result.ok, "code": result.code, "message": result.message,
               "verification_id": result.verification_id}
    return payload if status == 200 else err(status, result.code, result.message)
