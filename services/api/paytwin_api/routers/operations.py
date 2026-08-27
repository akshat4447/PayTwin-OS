"""Tenant-scoped operational readiness and safe local reconciliation APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, get_db, require_admin
from paytwin_api.services import audit as audit_svc
from paytwin_api.services.reconciliation import operational_status, reconcile_financial_state

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/status")
def status(p: Principal = Depends(current_principal),
           db: Session = Depends(get_db)) -> dict:
    return operational_status(db, p.organization_id)


@router.post("/reconcile")
def reconcile(p: Principal = Depends(current_principal),
              db: Session = Depends(get_db)) -> dict:
    """Run the narrow, no-provider-call repair sweep for this tenant."""
    require_admin(p)
    result = reconcile_financial_state(db, p.organization_id)
    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="operations.reconciled",
        object_type="organization", object_id=p.organization_id,
        summary="Local payment reconciliation completed",
        details=result,
    )
    db.commit()
    return {"ok": True, **result, "status": operational_status(db, p.organization_id)}
