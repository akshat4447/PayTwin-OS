"""Models registry: list + promote (risk_admin only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, err, get_db, require_admin
from paytwin_api.models import ModelVersion
from paytwin_api.services.bus import publish_outbox

router = APIRouter(prefix="/api/models", tags=["models"])

ALLOWED_STAGES = ("VALIDATED", "CHAMPION", "ARCHIVED")


@router.get("")
def list_models(p: Principal = Depends(current_principal),
                db: Session = Depends(get_db)):
    rows = (db.query(ModelVersion)
            .order_by(ModelVersion.trained_at.desc()).limit(100).all())
    return [{"id": m.id, "name": m.name, "version": m.version, "stage": m.stage,
             "kind": m.kind, "metrics": m.metrics,
             "feature_version": m.feature_version,
             "trained_at": m.trained_at.isoformat(),
             "drift": None} for m in rows]


class PromoteBody(BaseModel):
    stage: str


@router.post("/{model_id}/promote")
def promote(model_id: str, body: PromoteBody,
            p: Principal = Depends(current_principal),
            db: Session = Depends(get_db)):
    require_admin(p)
    if body.stage not in ALLOWED_STAGES:
        return err(422, "bad_stage", f"stage must be one of {ALLOWED_STAGES}")
    # model_versions is a GLOBALLY shared registry (no tenant column) — champion
    # promotion changes runtime behavior for every tenant, so it is a platform
    # operation: org_admin only. risk_admin stays tenant-scoped.
    if body.stage == "CHAMPION" and p.role != "org_admin":
        return err(403, "forbidden_role",
                   "CHAMPION promotion is a platform operation (org_admin only)")
    m = db.query(ModelVersion).filter(ModelVersion.id == model_id).one_or_none()
    if m is None:
        return err(404, "not_found", f"model {model_id}")
    if body.stage == "CHAMPION":
        for other in (db.query(ModelVersion)
                      .filter(ModelVersion.name == m.name,
                              ModelVersion.stage == "CHAMPION").all()):
            other.stage = "ARCHIVED"
    m.stage = body.stage
    from datetime import datetime, timezone

    m.promoted_at = datetime.now(timezone.utc)
    from paytwin_api.services import audit as audit_svc

    audit_svc.append_audit(
        db, p.organization_id, actor=p.user_id or f"{p.role}@{p.key_prefix}",
        actor_role=p.role, action_type="model.promoted", object_type="model_version",
        object_id=f"{m.name}:{m.version}",
        summary=f"{m.name} {m.version} → {m.stage}",
        details={"stage": m.stage, "kind": m.kind})
    publish_outbox(db, p.organization_id, "model_promoted",
                   {"model": m.name, "version": m.version, "stage": m.stage})
    db.commit()
    return {"id": m.id, "name": m.name, "version": m.version, "stage": m.stage}